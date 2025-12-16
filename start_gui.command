#!/bin/bash
cd "$(dirname "$0")"
# 使用 python3 -m streamlit 确保能找到命令，避免 PATH 问题
/usr/bin/python3 -m streamlit run app.py
