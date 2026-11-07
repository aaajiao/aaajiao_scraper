#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
# 使用项目虚拟环境启动 Streamlit，避免系统 Python 和 PATH 差异
if [[ ! -x .venv/bin/python ]]; then
  echo "缺少项目环境，请先运行 ./tools/bootstrap_python.sh" >&2
  exit 1
fi
exec ./.venv/bin/python -m streamlit run portfolio_scraper/app.py "$@"
