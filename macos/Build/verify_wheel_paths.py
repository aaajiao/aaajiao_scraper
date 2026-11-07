#!/usr/bin/env python3
"""Reject local build-machine paths in wheel members, including native binaries."""

import argparse
import zipfile
from pathlib import Path

LOCAL_PREFIXES = (
    b"/Users/",
    b"/opt/homebrew/",
    b"/private/var/folders/",
    b"/var/folders/",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheelhouse", type=Path)
    args = parser.parse_args()
    wheels = sorted(args.wheelhouse.glob("*.whl"))
    if not wheels:
        raise RuntimeError("No wheels to check")
    members = 0
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                content = archive.read(name)
                for prefix in LOCAL_PREFIXES:
                    if prefix in content:
                        raise RuntimeError(
                            f"Local build path {prefix.decode()} found in {wheel.name}: {name}"
                        )
                members += 1
    print(f"Verified {members} members in {len(wheels)} wheels: no local build-machine paths")


if __name__ == "__main__":
    main()
