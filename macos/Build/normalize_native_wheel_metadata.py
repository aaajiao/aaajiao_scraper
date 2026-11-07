#!/usr/bin/env python3
"""Replace local SBOM source references with the pinned official source URL."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def normalize(value: object, source_url: str, package_ref: str) -> object:
    if isinstance(value, dict):
        return {key: normalize(item, source_url, package_ref) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item, source_url, package_ref) for item in value]
    if isinstance(value, str) and value.startswith("path+file://"):
        _, separator, fragment = value.partition("#")
        if not separator or not fragment.startswith(package_ref):
            raise RuntimeError(
                "Unexpected local SBOM package reference; refusing to rewrite provenance"
            )
        return source_url + "#" + fragment.replace(" ", "%20")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheelhouse", type=Path)
    args = parser.parse_args()
    source = json.loads((Path(__file__).parent / "native_wheel_sources.json").read_text())[
        "pydantic-core"
    ]
    wheels = list(args.wheelhouse.glob(f"pydantic_core-{source['version']}-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("Expected exactly one native core wheel")
    wheel = wheels[0]
    with tempfile.TemporaryDirectory(prefix="native-wheel-metadata-") as directory:
        root = Path(directory)
        subprocess.run(
            [sys.executable, "-m", "wheel", "unpack", str(wheel), "-d", str(root)], check=True
        )
        unpacked = root / f"pydantic_core-{source['version']}"
        sboms = list(unpacked.glob("*.dist-info/sboms/*.json"))
        if not sboms:
            raise RuntimeError("Expected the native wheel's SBOM")
        for path in sboms:
            content = json.loads(path.read_text())
            normalized = normalize(content, source["url"], f"pydantic-core@{source['version']}")
            path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n")
        packed = root / "packed"
        packed.mkdir()
        # wheel pack regenerates all RECORD sizes/hashes after the SBOM-only edit.
        subprocess.run(
            [sys.executable, "-m", "wheel", "pack", str(unpacked), "-d", str(packed)], check=True
        )
        (packed / wheel.name).replace(wheel)
    print("Normalized native SBOM source references; dependency and license data retained")


if __name__ == "__main__":
    main()
