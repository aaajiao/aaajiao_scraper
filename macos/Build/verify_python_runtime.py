#!/usr/bin/env python3
"""Check runtime identity and every bundled Mach-O load path before shipping."""

import argparse
import json
import os
import plistlib
import re
import subprocess
from pathlib import Path

MAGIC = {
    bytes.fromhex(value)
    for value in (
        "feedface",
        "cefaedfe",
        "feedfacf",
        "cffaedfe",
        "cafebabe",
        "bebafeca",
        "cafebabf",
        "bfbafeca",
    )
}
SYSTEM_PREFIXES = ("/usr/lib/", "/System/Library/")


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def tool(*arguments: str) -> str:
    return subprocess.check_output(arguments, text=True, stderr=subprocess.STDOUT)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_root", type=Path)
    parser.add_argument("--app", type=Path)
    args = parser.parse_args()
    runtime = args.runtime_root.resolve()
    manifest = json.loads((runtime / "runtime_manifest.json").read_text())
    expected = json.loads((Path(__file__).parent / "python_runtime_manifest.json").read_text())
    development_version = (
        (Path(__file__).resolve().parents[2] / ".python-version").read_text().strip()
    )
    assert expected["version"] == development_version, "Bundled Python pin differs from development"
    assert manifest == expected, "Bundled runtime provenance differs from the pinned manifest"
    python = runtime / manifest["executable"]
    env = os.environ.copy()
    for name in (
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONEXECUTABLE",
        "PYTHONUSERBASE",
        "__PYVENV_LAUNCHER__",
    ):
        env.pop(name, None)
    actual = json.loads(
        subprocess.check_output(
            [
                str(python),
                "-B",
                "-I",
                "-c",
                "import json,platform,sys,sysconfig,ssl,sqlite3,requests,bs4,pydantic,pydantic_core; "
                "print(json.dumps({'version':platform.python_version(),'machine':platform.machine(),"
                "'prefix':sys.prefix,'purelib':sysconfig.get_path('purelib'),'soabi':sysconfig.get_config_var('SOABI'),"
                "'gil':not bool(sysconfig.get_config_var('Py_GIL_DISABLED')),"
                "'core':pydantic_core._pydantic_core.__file__}))",
            ],
            env=env,
            text=True,
        )
    )
    assert actual["version"] == manifest["version"] and actual["machine"] == "arm64", actual
    assert actual["gil"] == manifest["gil"], actual
    for name in ("prefix", "purelib", "core"):
        assert inside(Path(actual[name]), runtime), (
            f"Python {name} escapes the runtime: {actual[name]}"
        )
    assert Path(actual["purelib"]).resolve() == (runtime / manifest["site_packages"]).resolve(), (
        actual
    )
    expected_abi = "cpython-" + manifest["abi"].removeprefix("cp") + "-darwin"
    assert actual["soabi"] == expected_abi, actual
    requirements = (Path(__file__).parent / "wheelhouse_requirements.txt").read_text().splitlines()
    versions = json.loads(
        subprocess.check_output(
            [
                str(python),
                "-B",
                "-I",
                "-c",
                "import importlib.metadata as m,json,sys; print(json.dumps({name:m.version(name) for name in sys.argv[1:]}))",
                *[
                    line.split("==")[0]
                    for line in requirements
                    if line and not line.startswith("#")
                ],
            ],
            env=env,
            text=True,
        )
    )
    for line in requirements:
        if line and not line.startswith("#"):
            name, version = line.split("==")
            assert versions[name] == version, (name, versions[name], version)

    scan_root = args.app.resolve() if args.app else runtime
    minimum = "14.0"
    if args.app:
        with (scan_root / "Contents/Info.plist").open("rb") as handle:
            minimum = plistlib.load(handle)["LSMinimumSystemVersion"]
    native = []
    for path in scan_root.rglob("*"):
        if path.is_symlink():
            assert inside(path, scan_root), f"Bundled symlink escapes app: {path}"
            continue
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            if handle.read(4) in MAGIC:
                native.append(path)
    assert native, "No Mach-O runtime files found"
    highest = (0,)
    for path in native:
        executable_dir = python.parent if inside(path, runtime) else scan_root / "Contents/MacOS"
        executable_rpaths = [python.parent / "../lib"] if inside(path, runtime) else []
        arches = tool("/usr/bin/lipo", "-archs", str(path)).split()
        assert "arm64" in arches, f"Missing arm64 architecture: {path} ({arches})"
        commands = tool("/usr/bin/otool", "-l", str(path))
        rpaths = re.findall(r"cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset", commands)
        local_rpaths = []
        for entry in rpaths:
            if entry.startswith(SYSTEM_PREFIXES):
                local_rpaths.append(Path(entry))
                continue
            if entry.startswith("@loader_path/"):
                resolved = path.parent / entry[len("@loader_path/") :]
            elif entry.startswith("@executable_path/"):
                resolved = executable_dir / entry[len("@executable_path/") :]
            else:
                raise AssertionError(f"Nonportable RPATH in {path}: {entry}")
            assert inside(resolved, scan_root), f"RPATH escapes bundle in {path}: {entry}"
            local_rpaths.append(resolved)
        deployment = re.findall(
            r"cmd LC_BUILD_VERSION\s+cmdsize \d+\s+platform \S+\s+minos ([\d.]+)", commands
        )
        deployment += re.findall(
            r"cmd LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version ([\d.]+)", commands
        )
        for value in deployment:
            highest = max(highest, version_tuple(value))
            assert version_tuple(value) <= version_tuple(minimum), (
                f"{path} needs macOS {value}, app declares {minimum}"
            )
        install_names = set(tool("/usr/bin/otool", "-D", str(path)).splitlines()[1:])
        for line in tool("/usr/bin/otool", "-L", str(path)).splitlines()[1:]:
            entry = line.strip().split(" (compatibility version", 1)[0]
            if entry in install_names or entry.startswith(SYSTEM_PREFIXES):
                continue
            if entry.startswith("@loader_path/"):
                candidates = [path.parent / entry[len("@loader_path/") :]]
            elif entry.startswith("@executable_path/"):
                candidates = [executable_dir / entry[len("@executable_path/") :]]
            elif entry.startswith("@rpath/"):
                candidates = [
                    base / entry[len("@rpath/") :] for base in local_rpaths + executable_rpaths
                ]
            else:
                raise AssertionError(
                    f"External or absolute non-system dependency in {path}: {entry}"
                )
            assert any(
                str(candidate).startswith(SYSTEM_PREFIXES)
                or (candidate.exists() and inside(candidate, scan_root))
                for candidate in candidates
            ), f"Unresolved bundled dependency in {path}: {entry}"
    print(
        json.dumps(
            {
                "python": actual["version"],
                "abi": actual["soabi"],
                "native_files": len(native),
                "highest_macos_minimum": ".".join(map(str, highest)),
                "declared_macos_minimum": minimum,
                "external_non_system_dependencies": 0,
                "runtime_root": str(runtime),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
