# aaajiao Scraper Repository

这个仓库现在是一个 umbrella repo，包含两个平行的产品面：

1. `portfolio_scraper/`
   Python 抓取器、Streamlit GUI、批处理脚本、示例、Python 测试
2. `macos/`
   本地 macOS importer，带 workspace、review queue、baseline refresh 和显式 git apply

根目录只保留仓库级说明、共享数据产物和兼容入口：

- `aaajiao_works.json`
- `aaajiao_portfolio.md`
- `start_gui.command`
- `pyproject.toml`

## 目录结构

```text
aaajiao_scraper/
├── portfolio_scraper/
│   ├── app.py
│   ├── scraper/
│   ├── scripts/
│   ├── examples/
│   ├── tests/
│   └── README.md
├── macos/
├── tests/
│   └── test_macos_helper.py
├── aaajiao_works.json
├── aaajiao_portfolio.md
├── start_gui.command
├── AGENTS.md
└── pyproject.toml
```

## 快速入口

Python 产品线：

```bash
./start_gui.command
python3 -m pytest portfolio_scraper/tests/ -v
python portfolio_scraper/scripts/batch_update_works.py --limit 10 --dry-run
```

macOS 产品线：

```bash
./macos/Build/prepare_seed.sh
./macos/Build/build_local_app.sh
python3 -m pytest tests/test_macos_helper.py -v
```

## 文档导航

- Python 抓取器与 GUI：`portfolio_scraper/README.md`
- macOS importer：`macos/README.md`
- agent 仓库说明：`AGENTS.md`

## 共享产物

`aaajiao_works.json` 和 `aaajiao_portfolio.md` 继续保留在仓库根目录。

- Python 抓取器默认写回这两个文件
- macOS importer 的 seed、baseline refresh 和 apply 也继续以这两个根级文件为目标
