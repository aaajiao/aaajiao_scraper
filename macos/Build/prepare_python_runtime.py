#!/usr/bin/env python3
"""Prepare the checksum-pinned, relocatable Python distribution for the app."""

import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


def clean_python_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE", "PYTHONUSERBASE"):
        env.pop(name, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    build_dir = Path(__file__).resolve().parent
    macos_dir = build_dir.parent
    manifest = json.loads((build_dir / "python_runtime_manifest.json").read_text())
    development_version = (macos_dir.parent / ".python-version").read_text().strip()
    if manifest["version"] != development_version:
        raise RuntimeError(
            "Bundled Python version must match the repository .python-version before building"
        )
    downloads = macos_dir / ".build/runtime-downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / manifest["archive"]
    if not archive.exists() or sha256(archive) != manifest["sha256"]:
        partial = archive.with_suffix(".download")
        try:
            subprocess.run(
                [
                    "/usr/bin/curl",
                    "--fail",
                    "--location",
                    "--retry",
                    "2",
                    "--connect-timeout",
                    "10",
                    "--max-time",
                    "180",
                    manifest["url"],
                    "--output",
                    str(partial),
                ],
                check=True,
            )
            if sha256(partial) != manifest["sha256"]:
                raise RuntimeError("Python runtime archive failed its pinned SHA-256 check")
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    # Do not permit extraction outside the one expected archive root, even if
    # the pinned release manifest is later edited incorrectly.
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] != "python"
            ):
                raise RuntimeError("Python runtime archive contains an unsafe member path")
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                if link.is_absolute():
                    raise RuntimeError("Python runtime archive contains an absolute link")
                base = path.parent if member.issym() else PurePosixPath()
                resolved = []
                for part in (base / link).parts:
                    if part == "..":
                        if not resolved:
                            raise RuntimeError("Python runtime archive link escapes its root")
                        resolved.pop()
                    elif part != ".":
                        resolved.append(part)
                if not resolved or resolved[0] != "python":
                    raise RuntimeError("Python runtime archive link escapes its root")
    vendor = macos_dir / "Vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".runtime-", dir=vendor) as temporary:
        staging = Path(temporary)
        subprocess.run(["/usr/bin/tar", "-xzf", str(archive), "-C", str(staging)], check=True)
        replacement = staging / "python"
        python = replacement / "bin/python3"
        actual = subprocess.check_output(
            [
                str(python),
                "-I",
                "-c",
                "import json,platform,sysconfig; print(json.dumps({'version':platform.python_version(),"
                "'machine':platform.machine(),'gil':not bool(sysconfig.get_config_var('Py_GIL_DISABLED'))}))",
            ],
            env=clean_python_environment(),
            text=True,
        )
        actual = json.loads(actual)
        if actual != {"version": manifest["version"], "machine": "arm64", "gil": manifest["gil"]}:
            raise RuntimeError(f"Unexpected Python runtime identity: {actual}")
        (replacement / "runtime_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        target = vendor / "python_runtime"
        previous = staging / "previous"
        if target.exists():
            target.replace(previous)
        try:
            replacement.replace(target)
        except BaseException:
            if previous.exists():
                previous.replace(target)
            raise
    print(
        f"Prepared standalone Python {manifest['version']} ({manifest['target']}, SHA-256 verified)"
    )


if __name__ == "__main__":
    main()
