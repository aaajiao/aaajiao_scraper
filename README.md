# aaajiao 作品集爬虫 / aaajiao Portfolio Scraper

从 [eventstructure.com](https://eventstructure.com) 自动抓取 aaajiao 的作品信息，生成结构化 JSON / Markdown，
并提供一个本地优先的 macOS 导入器，用于审阅、确认后再写回仓库。

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## 当前项目状态

截至 2026-03-12，这个仓库有两条并行主线：

1. **Python 抓取器 / Streamlit GUI**  
   负责抓取、校验、缓存、清洗和导出作品数据。
2. **aaajiao Importer for macOS**  
   一个本地菜单栏应用，带 review queue、workspace、baseline refresh 和显式 git apply 流程。

最近一轮开发重点集中在 `macos/`：

- workspace bootstrap / reset
- 从 GitHub `main` 刷新 baseline
- OpenAI 严格结构化校验 + 本地二次校验
- review / apply 流程简化
- dirty repo 下的 managed publish repo
- 离线 wheelhouse、acceptance checks、git transaction checks、live import check

---

## 核心能力

### 1. 两层混合提取策略（Strategy B）

当前推荐提取路径是 `extract_work_details_v2()`：

1. **Layer 0**：缓存命中与旧数据修正
2. **Layer 1**：本地 BeautifulSoup 提取
3. **Layer 2**：Firecrawl Extract API v2 + Pydantic schema
4. **Post-pipeline**：跨作品污染清理

字段优先级：

- **Layer 1 权威字段**：`year`, `type`, `images`
- **Layer 1 验证基线**：`title`
- **Layer 2 权威字段**：`title`, `title_cn`, `materials`, `size`, `duration`, `credits`, `description_en`, `description_cn`

### 2. SPA 感知校验链

`eventstructure.com` 是 Cargo Collective SPA，主要风险是导航栏污染和跨作品内容泄漏。

当前校验链包括：

1. `_is_type_string()`
2. `_is_known_sidebar_title()`
3. `_validate_title_against_url()`
4. `_titles_are_similar()`
5. 标题失败时拒绝 materials / descriptions
6. `_is_description_contaminated()`
7. `_clean_cross_contamination()`

### 3. 增量更新与缓存

- 四级缓存：general / sitemap / extract / discovery
- 基于 sitemap `lastmod` 的增量更新
- 发现缓存 TTL 24 小时
- 重复抓取已缓存 URL 时接近 0 成本

### 4. 本地优先的 macOS 导入器

macOS 导入器不是直接修改仓库，而是：

1. 从 seed 数据启动独立 workspace
2. 在安全条件下从 GitHub 刷新 `aaajiao_works.json` 和 `aaajiao_portfolio.md`
3. 执行 incremental sync 或手动提交 URL
4. 在 app 内审阅 `ready_for_review` / `needs_review`
5. 预览 apply transaction
6. 显式确认后再写回仓库

---

## 技术栈

- **Python**: 3.9+
- **GUI**: Streamlit
- **抓取**: requests, BeautifulSoup4, Firecrawl API v2
- **验证**: Pydantic v2
- **macOS 应用**: Swift, AppKit, SwiftUI
- **本地存储**: JSON, Markdown, SQLite, `.cache/`
- **开发工具**: pytest, pytest-cov, ruff, black, mypy

---

## 目录结构

```text
aaajiao_scraper/
├── scraper/                        # 核心 Python 抓取包
├── app.py                          # Streamlit GUI（中文界面）
├── macos/                          # 本地 macOS 导入器
│   ├── App/                        # Swift 菜单栏 UI
│   ├── Helper/                     # Python 导入引擎
│   ├── HelperBridge/               # Swift <-> Python bridge
│   ├── Shared/                     # DTOs
│   ├── Build/                      # 构建/验收/发布脚本
│   ├── Seed/                       # seed 数据与 manifest
│   └── Vendor/wheelhouse/          # 离线 Python wheels
├── scripts/                        # 清洗、验证、批处理脚本
├── tests/                          # scraper + macOS helper 测试
├── examples/                       # 使用示例
├── aaajiao_works.json              # 输出数据
├── aaajiao_portfolio.md            # 输出 Markdown
├── AGENTS.md                       # 面向 agent 的仓库说明
└── pyproject.toml                  # 依赖与工具配置
```

---

## 安装

### 前置要求

- Python 3.9+
- Firecrawl API Key（如需 AI 提取）
- macOS 构建仅在需要本地导入器时使用

### 安装 Python 依赖

```bash
git clone https://github.com/your-username/aaajiao_scraper.git
cd aaajiao_scraper
pip install -e .
```

开发环境建议：

```bash
pip install -e ".[dev]"
```

### 配置环境变量

```bash
cp .env.example .env
```

`.env` 示例：

```bash
FIRECRAWL_API_KEY=your_api_key_here
# CACHE_ENABLED=true
# RATE_LIMIT_CALLS_PER_MINUTE=10
```

说明：

- 没有 `FIRECRAWL_API_KEY` 时，本地 BS4 提取仍可运行，但信息完整度有限
- macOS 导入器如需 AI 校验，还需要 `OPENAI_API_KEY`

---

## 使用方式

### 方式一：Streamlit GUI

```bash
streamlit run app.py
```

或：

```bash
./start_gui.command
```

主要功能：

1. 状态仪表板
2. 一键抓取
3. 增量更新
4. JSON / Markdown 导出
5. 图片整合与 Web 报告

### 方式二：Python API

```python
from scraper import AaajiaoScraper

scraper = AaajiaoScraper(use_cache=True)

result = scraper.run_full_pipeline(
    incremental=True,
    max_workers=4,
)

print(result["stats"])
```

也可以直接调用：

```python
work = scraper.extract_work_details_v2("https://eventstructure.com/example-work")
```

### 方式三：脚本

```bash
python scripts/batch_update_works.py --limit 10 --dry-run
python scripts/clean_size_materials.py --dry-run
python scripts/clean_materials_credits.py
python scripts/generate_web_report.py
python scripts/verify_portfolio.py
```

---

## macOS 导入器

`macos/` 下提供一个本地菜单栏应用 `aaajiao Importer.app`。

它的设计目标是：

- 不直接污染仓库工作区
- 先在独立 workspace 内处理
- 先 review，再 apply
- 在 source repo 不干净时，通过 managed publish repo 完成发布写回

### 构建

```bash
./macos/Build/refresh_wheelhouse.sh
./macos/Build/verify_wheelhouse.sh
./macos/Build/build_local_app.sh
```

构建输出：

```bash
dist/aaajiao\ Importer.app
```

### 验收与发布前检查

```bash
./macos/Build/run_acceptance_checks.sh
./macos/Build/run_git_transaction_checks.sh
./macos/Build/check_repo_apply_prereqs.sh
```

可选真实导入检查：

```bash
OPENAI_API_KEY=... ./macos/Build/run_live_import_check.sh
```

更多细节见：

- `macos/README.md`
- `macos/Build/RELEASE_CHECKLIST.md`

---

## 开发

### 运行测试

```bash
python3 -m pytest tests/ -v
python3 -m pytest tests/ --cov=scraper --cov-report=html
python3 -m pytest tests/test_macos_helper.py -v
```

注意：

- `pyproject.toml` 默认通过 `addopts` 注入 coverage 参数，所以本地需要安装 `pytest-cov`
- 没有安装 `requests`、`beautifulsoup4` 等依赖时，测试会在 collection 阶段失败
- 最稳妥的本地环境是先执行 `pip install -e ".[dev]"`
- 如需临时跳过默认 coverage 参数，可使用：

```bash
python3 -m pytest tests/ -o addopts=
```

### 代码质量

```bash
ruff format .
ruff check .
mypy scraper/
```

---

## Firecrawl 成本参考

| 模式 | 方法 | 大致成本 | 说明 |
|------|------|----------|------|
| 缓存命中 | 本地读取 | 0 credits | 重复请求 |
| Layer 1 | BeautifulSoup | 0 credits | year/type/images |
| Markdown 抓取 | `scrape_markdown()` | 1 credit | 原始内容 |
| Extract v2 | `extract_work_details_v2()` | ~5-20 credits | 推荐路径 |
| Scrape+JSON | `scrape_with_json()` | ~5 credits | 同步结构化兜底 |

建议：

- 默认开启缓存
- 常规更新优先使用增量模式
- 新改动先小批量验证，再全量跑

---

## 输出文件

常见输出包括：

- `aaajiao_works.json`
- `aaajiao_portfolio.md`
- `.cache/`
- `reports/`
- `output/`
- `output/images/`
- `macos/Seed/seed_manifest.json`
- importer workspace 下的 `workspace_manifest.json`
- importer workspace 下的 `jobs.sqlite`

---

## 已知风险

`eventstructure.com` 的 SPA 特性会带来三类典型问题：

1. 导航栏标题污染
2. 邻近作品的 materials / description 泄漏
3. 动态内容延迟渲染

当前仓库已经有对应的校验与清理逻辑，新改动应尽量复用这条验证链，而不是绕开它。

---

## License

MIT License
