#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python_bin="${PYTHON_BIN:-python3.15}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "Install Python $(cat .python-version), or set PYTHON_BIN to that interpreter." >&2
  exit 1
fi
"$python_bin" - <<'PY'
from pathlib import Path
import sys
import sysconfig

expected = Path('.python-version').read_text().strip()
if sys.version.split()[0] != expected or sysconfig.get_config_var('Py_GIL_DISABLED'):
    raise SystemExit(f'Expected standard CPython {expected}; got {sys.version.split()[0]}')
PY

if [[ -e .venv && ! -x .venv/bin/python ]]; then
  echo 'Incomplete .venv: move it aside, then rerun this script.' >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  "$python_bin" -m venv .venv
fi
.venv/bin/python - <<'PY'
from pathlib import Path
import sys
import sysconfig

expected = Path('.python-version').read_text().strip()
if sys.version.split()[0] != expected or sysconfig.get_config_var('Py_GIL_DISABLED'):
    raise SystemExit(f'.venv is not standard CPython {expected}; move it aside and rebuild.')
PY

export PIP_DISABLE_PIP_VERSION_CHECK=1
export UV_PYTHON_DOWNLOADS=never
.venv/bin/python -m pip install --require-hashes --no-deps -r requirements/bootstrap.lock
.venv/bin/uv pip sync --python .venv/bin/python --require-hashes \
  --build-constraints requirements/python315.lock --require-build-hashes \
  requirements/python315.lock
.venv/bin/uv pip install --python .venv/bin/python --no-deps --no-build-isolation -e '.[dev]'
.venv/bin/python -m pip check
.venv/bin/python tools/check_environment.py
