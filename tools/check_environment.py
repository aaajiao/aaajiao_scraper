"""Verify the selected interpreter and every active dependency in the reviewed lock."""

import importlib.metadata
from pathlib import Path
import sys
import sysconfig

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = (root / ".python-version").read_text().strip()
    if sys.version.split()[0] != expected or sysconfig.get_config_var("Py_GIL_DISABLED"):
        raise SystemExit(f"Expected standard CPython {expected}; got {sys.version.split()[0]}")
    checked = 0
    for line in (root / "requirements/python315.lock").read_text().splitlines():
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        requirement = Requirement(line.removesuffix(" \\").strip())
        if requirement.marker and not requirement.marker.evaluate():
            continue
        installed = importlib.metadata.version(canonicalize_name(requirement.name))
        if installed not in requirement.specifier:
            raise SystemExit(f"Lock mismatch: {requirement.name} {installed}; expected {requirement.specifier}")
        checked += 1
    print(f"CPython {expected}; {checked} locked dependencies verified.")


if __name__ == "__main__":
    main()
