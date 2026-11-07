# aaajiao Portfolio Scraper

`portfolio_scraper/` 是这个仓库里的 Python 产品线。

它包含：

- `app.py`：Streamlit GUI
- `scraper/`：核心 Python package
- `scripts/`：批处理、清洗、验证脚本
- `examples/`：使用示例
- `tests/`：Python 侧测试

共享数据产物仍然写在仓库根目录：

- `../aaajiao_works.json`
- `../aaajiao_portfolio.md`

## 快速开始

开发与 GUI 固定使用 CPython **3.15.2**。在仓库根目录重建锁定环境：

```bash
./tools/bootstrap_python.sh
```

启动 GUI：

```bash
./start_gui.command
```

或直接运行：

```bash
./.venv/bin/python -m streamlit run portfolio_scraper/app.py
```

依赖版本、SHA-256 校验、原生构建工具、干净环境验证与 macOS helper
独立运行时的说明见 [`DEVELOPMENT.md`](../DEVELOPMENT.md)。

## 常用命令

测试：

```bash
./.venv/bin/python tools/run_tests.py
./.venv/bin/python tools/check_gui.py
./.venv/bin/python tools/check_wheel.py
./.venv/bin/python -m pytest portfolio_scraper/tests/ --cov=portfolio_scraper/scraper --cov-report=html
```

脚本：

```bash
./.venv/bin/python portfolio_scraper/scripts/batch_update_works.py --limit 10 --dry-run
./.venv/bin/python portfolio_scraper/scripts/clean_size_materials.py aaajiao_works.json --dry-run
./.venv/bin/python portfolio_scraper/scripts/clean_materials_credits.py --dry-run
./.venv/bin/python portfolio_scraper/scripts/generate_web_report.py
./.venv/bin/python portfolio_scraper/scripts/verify_portfolio.py
```

质量工具：

```bash
./.venv/bin/ruff format portfolio_scraper
./.venv/bin/ruff check portfolio_scraper
./.venv/bin/mypy portfolio_scraper/scraper/
```

## 架构摘要

主入口仍然是 `extract_work_details_v2(url)`，采用两层混合提取：

1. Layer 1：本地 BeautifulSoup 提取 `year`、`type`、`images` 和标题基线
2. Layer 2：Firecrawl Extract API v2 + schema validation
3. Post-pipeline：去重与跨作品污染清理

字段优先级：

- Layer 1 权威：`year`, `type`, `images`
- Layer 2 经校验后权威：`title`, `title_cn`, `materials`, `size`, `duration`, `credits`, `description_en`, `description_cn`

## 路径约定

Python 产品线不再依赖“当前工作目录刚好是仓库根目录”。

- 共享 JSON / Markdown 产物通过 `scraper.paths` 定位到仓库根
- `portfolio_scraper/output/` 和 `portfolio_scraper/reports/` 属于 Python 产品线自身产物
- 从任意目录运行 `portfolio_scraper/scripts/*.py` 时，默认相对仓库根解析共享产物路径
