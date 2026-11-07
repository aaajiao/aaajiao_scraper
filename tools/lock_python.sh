#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

uv_bin="${UV_BIN:-.venv/bin/uv}"
if [[ "$("$uv_bin" --version | awk '{print $2}')" != 0.13.7 ]]; then
  echo 'Lock generation requires uv 0.13.7.' >&2
  exit 1
fi
python_version="$(cat .python-version)"
"$uv_bin" pip compile requirements/bootstrap.in --python-version "$python_version" \
  --universal --generate-hashes --no-annotate --no-header -o requirements/bootstrap.lock
"$uv_bin" pip compile pyproject.toml requirements/python315.in --extra dev \
  --python-version "$python_version" --universal --generate-hashes \
  --no-annotate --no-header -o requirements/python315.lock
