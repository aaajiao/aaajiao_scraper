# aaajiao 作品集爬虫 / aaajiao Portfolio Scraper

从 [eventstructure.com](https://eventstructure.com) 自动抓取 aaajiao 的全部作品信息，生成结构化的 JSON 和 Markdown 文档。

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Tests](https://img.shields.io/badge/tests-70%20passing-green.svg)]()

---

## 核心特性

### 两层混合提取策略 + SPA 标题验证（v6.4.0 Strategy B）

采用优化的两层混合策略 + 四层标题验证，确保 100% 数据准确性：

1. **Layer 0**: 缓存检查（免费）
2. **Layer 1**: 本地 BeautifulSoup 解析（0 Credits）- 快速过滤 + 提取 year/type/images + 标题验证基准
3. **Layer 2**: Firecrawl Extract API **v2** + Pydantic（~5 Credits）- **始终调用**获取内容字段

**重要：所有 Firecrawl API 调用使用 v2 端点：**
- Extract: `https://api.firecrawl.dev/v2/extract`
- Scrape: `https://api.firecrawl.dev/v2/scrape`
- Agent: `https://api.firecrawl.dev/v2/agent`

**字段优先级（Strategy B）：**
- **Layer 1 权威字段**: `year`, `type`（从 tags 提取，~100% 准确）, `images`（从 slideshow 容器提取）
- **Layer 1 验证字段**: `title`（作为基准验证 Layer 2 标题）
- **Layer 2 权威字段**: `title`（验证通过后）, `title_cn`, `materials`, `size`, `duration`, `credits`, `description_en`, `description_cn`

**SPA 标题验证链（防止导航栏污染）：**
1. `_is_type_string()` - 拒绝类型字符串（如 "video installation / 视频装置"）
2. `_is_known_sidebar_title()` - 拒绝已知侧边栏标题在错误页面使用
3. `_validate_title_against_url()` - 验证标题与 URL slug 匹配
4. `_titles_are_similar()` - 与 Layer 1 标题模糊匹配

所有作品都经过 Layer 2 获取内容字段。Layer 1 负责过滤非作品页面（exhibition/catalog）以节省 API 成本。

### 智能缓存系统

- **四级缓存**：通用缓存、sitemap 缓存、提取缓存、发现缓存
- **增量更新**：基于 sitemap `lastmod` 跳过未变更作品
- **TTL 过期控制**：发现缓存 24 小时自动过期
- **离线图片整合**：利用缓存元数据补全图片，无需 API

### 现代化架构

- **Mixin 模式**：模块化设计，易于维护扩展
- **完整类型注解**：支持 IDE 智能提示和 MyPy 检查
- **Google 风格文档**：所有公共 API 详细说明
- **自动化测试**：70+ 测试用例，核心模块 90%+ 覆盖率
- **代码质量工具**：Ruff, Black, MyPy 集成

### 友好的界面

- **Streamlit GUI**：中文图形界面，零代码使用
- **Python API**：可编程接口，支持脚本集成
- **批处理脚本**：命令行工具处理批量任务

---

## 安装

### 前置要求

- Python 3.9+
- Firecrawl API Key（从 [firecrawl.dev](https://firecrawl.dev) 获取，可选）

### 快速安装

```bash
# 克隆仓库
git clone https://github.com/your-username/aaajiao_scraper.git
cd aaajiao_scraper

# 安装依赖（推荐）
pip install -e .

# 或安装开发依赖（包含测试、linting工具）
pip install -e ".[dev]"
```

### 配置 API Key

```bash
# 1. 复制环境变量模板
cp .env.example .env

# 2. 编辑 .env 文件，添加你的 API key
nano .env  # 或使用你喜欢的编辑器
```

`.env` 文件内容：
```bash
# 必需（如需 AI 提取功能）
FIRECRAWL_API_KEY=your_api_key_here

# 可选
# CACHE_ENABLED=true
# RATE_LIMIT_CALLS_PER_MINUTE=10
```

> 注：本地 BeautifulSoup 提取无需 API Key，但精度有限

---

## 项目结构

```
aaajiao_scraper/
├── scraper/                      # 核心爬虫包
│   ├── __init__.py              # 导出主类 AaajiaoScraper
│   ├── core.py                  # RateLimiter, CoreScraper 基类
│   ├── basic.py                 # HTML 解析、sitemap、URL 验证
│   ├── firecrawl.py             # Firecrawl API 集成
│   ├── cache.py                 # 多级缓存系统
│   ├── report.py                # JSON/Markdown 报告生成
│   └── constants.py             # Schema、Prompt、配置常量
├── app.py                       # Streamlit GUI（中文界面）
├── tests/                       # 测试套件
│   ├── conftest.py             # pytest fixtures
│   ├── test_core.py            # 核心功能测试
│   ├── test_cache.py           # 缓存系统测试
│   ├── test_basic.py           # HTML 解析测试
│   ├── test_firecrawl.py       # API 集成测试
│   └── test_report.py          # 报告生成测试
├── scripts/                     # 实用脚本
│   ├── batch_update_works.py   # 批量 Markdown 抓取（1 credit/页）
│   ├── clean_size_materials.py # 从 materials 提取 size/duration
│   ├── clean_materials_credits.py # 清理 materials 和 credits 字段
│   ├── generate_web_report.py  # 生成 Web 报告
│   ├── firecrawl_test.py       # Firecrawl API 测试
│   ├── update_scraper.py       # 爬虫更新工具
│   └── verify_portfolio.py     # 数据验证
├── reports/                     # 生成的 Markdown 报告
├── examples/                    # 使用示例
│   ├── quick_start.py          # 快速开始
│   ├── batch_extraction.py     # 批量提取
│   └── incremental_scrape.py   # 增量爬取
├── pyproject.toml              # 项目配置
├── .ruff.toml                  # Ruff 配置
└── .env.example                # 环境变量模板
```

### 架构设计

```
AaajiaoScraper
├── CoreScraper          # 会话管理、重试、API Key 加载
├── BasicScraperMixin    # Sitemap 解析、BS4 提取、URL 验证
├── FirecrawlMixin       # Firecrawl API、批量提取
├── CacheMixin           # 多级缓存（sitemap、extract、discovery）
└── ReportMixin          # JSON、Markdown、Agent 报告生成
```

---

## 使用方法

### 方式一：Web GUI（推荐）

启动 Streamlit 界面：

```bash
streamlit run app.py
```

浏览器会自动打开 `http://localhost:8501`

#### GUI 功能：

1. **状态仪表板**：显示作品总数、尺寸完成率、时长统计
2. **一键爬取**：支持增量模式和并发控制
3. **文件下载**：JSON 和 Markdown 导出
4. **数据预览**：DataFrame 展示提取结果
5. **图片工具**：
   - **图片整合**：下载图片到本地，生成报告
   - **网络图片报告**：使用在线图片链接，生成轻量报告
   - **合并完整元数据**：可选将图片与 `aaajiao_works.json` 中的完整作品信息合并（类型、材料、尺寸、描述等）

### 方式二：Python API

```python
from scraper import AaajiaoScraper

# 初始化
scraper = AaajiaoScraper(use_cache=True)

# 运行完整流程（推荐）
stats, files = scraper.run_full_pipeline(incremental=True)
print(f"提取了 {stats['total']} 个作品")

# 或手动控制流程
work_urls = scraper.get_all_work_links(incremental=False)
work_data = scraper.extract_work_details(work_urls[0])

# 保存结果
scraper.save_to_json("output/works.json")
scraper.generate_markdown("output/portfolio.md")
```

### 方式三：命令行脚本

```bash
# 批量更新（使用 Markdown 抓取，1 credit/页）
python scripts/batch_update_works.py --limit 10 --dry-run

# 清理数据（从 materials 提取 size/duration）
python scripts/clean_size_materials.py --dry-run

# 生成 Web 报告
python scripts/generate_web_report.py
```

---

## 开发

### 运行测试

```bash
# 运行所有测试
python3 -m pytest tests/ -v

# 查看覆盖率
python3 -m pytest tests/ --cov=scraper --cov-report=html
open htmlcov/index.html

# 运行特定测试
python3 -m pytest tests/test_core.py -v
```

### 代码质量检查

```bash
# 格式化代码
ruff format .

# 检查代码质量
ruff check .

# 类型检查
mypy scraper/
```

---

## 成本说明

Firecrawl v2 API 计费机制（Extract API 按 token 计费，15 tokens = 1 credit）：

| 模式 | 方法 | 成本 | 适用场景 |
|------|------|------|----------|
| **缓存命中** | 本地读取 | 0 Credit | 重复请求 |
| **本地解析** | BeautifulSoup (Layer 1) | 0 Credit | 过滤 + year/type/images |
| **Markdown 抓取** | `scrape_markdown()` | 1 Credit | 需要原始内容 |
| **Extract v2** | `extract_work_details_v2()` | ~5-20 Credits | 推荐方式（v2 比 v1 便宜 10 倍） |
| **LLM 提取** | `extract_work_details()` | ~30 Credits | 旧方法（已弃用） |

> - Extract v2 API 实际消耗 5-25 credits/页，比 v1 便宜约 10 倍
> - 启用缓存（默认开启），重复抓取相同 URL 时 **0 消耗**
> - 预计总成本：~166 作品 × ~15 credits ≈ 2,500 credits（使用 v2）

---

## 输出文件

```
aaajiao_scraper/
├── aaajiao_works.json          # 结构化数据（根目录）
├── aaajiao_portfolio.md        # Markdown 作品集文档
├── output/                     # 基础爬虫输出
│   └── images/                 # 下载的图片
├── reports/                    # 生成的 Markdown 报告
└── .cache/                     # 缓存目录
    ├── {url_hash}.pkl          # 通用缓存
    ├── sitemap_lastmod.json    # Sitemap 时间戳
    └── extract_{hash}.pkl      # 提取结果缓存
```

---

## 更新日志

### v6.4.0（当前版本）

- **Strategy B 架构**：Layer 2 始终调用获取内容字段，Layer 1 提供 year/type/images 和标题验证
- **SPA 标题验证链**：四层验证防止导航栏污染
  - `_is_type_string()` - 拒绝类型字符串（如 "video installation"）
  - `_is_known_sidebar_title()` - 拒绝已知侧边栏标题在错误页面使用（如 "Guard, I…"、"One ritual"）
  - `_validate_title_against_url()` - 验证标题与 URL slug 匹配
  - `_titles_are_similar()` - 与 Layer 1 标题模糊匹配
- **数据污染修复**：修复 15 个被错误标题覆盖的作品（"Guard, I…"、"video installation"、"One ritual"）
- **title_cn 提取优化**：BS4 现在检查行长度和标题起始位置，避免提取描述片段
- **ARTWORK_EXTRACT_PROMPT 更新**：明确警告 LLM 忽略 SPA 侧边栏内容
- **已知侧边栏标题映射**：`SIDEBAR_TITLE_TO_URL` 映射表用于精确检测

### v6.3.0

- **升级到 Firecrawl v2 API**：所有 API 调用使用 v2 端点，成本降低约 10 倍
  - Extract: `/v2/extract`（~5-20 credits vs v1 的 ~30 credits）
  - Scrape: `/v2/scrape`
  - Agent: `/v2/agent`
- **100% 数据验证**：所有作品都经过 Layer 2 (AI) 验证，确保数据准确性
- **字段优先级优化**：
  - Layer 1 权威：`year`, `type`（从 tags 提取，~100% 准确）, `images`
  - Layer 2 权威：`title`, `title_cn`, `materials`, `size`, `duration`, `credits`, `description_en`, `description_cn`
- **API 调用追踪**：添加调用计数器，便于调试重复调用问题
- **URL 去重安全检查**：确保并发执行时不会重复处理同一 URL
- **图片显示优化**：
  - 移除图片数量限制，显示全部图片
  - 添加可点击缩略图（400px 宽度，点击查看大图）
- **Markdown 报告格式统一**：
  - 使用 `**Field**: value` 格式替代表格
  - 添加 Year 字段到单个作品元数据
  - 描述使用普通文本格式（非 blockquote）
- **验证脚本**：新增 `scripts/verify_layer2.py` 用于测试 Layer 2 提取质量

### v6.2.0

- **两层混合提取策略**：全新架构，Layer 1 (BS4) + Layer 2 (Firecrawl Schema Extract)
- **Pydantic Schema**：使用 ArtworkSchema 进行结构化提取，字段描述引导 LLM
- **90%+ 完整度**：优化后覆盖率从 37% 提升至 90%+
- **智能合并**：Layer 1 和 Layer 2 结果自动合并，取长补短
- **图片工具增强**：新增「合并完整元数据」选项，可将图片与已有作品信息合并输出
- **富文本报告**：支持生成包含类型、材料、尺寸、时长、描述等完整信息的 Markdown 报告

### v6.1.0

- **移除 AI Agent**：简化界面，移除 Agent Research 功能
- **批处理脚本**：新增 `batch_update_works.py` 和 `clean_size_materials.py`
- **数据清洗**：支持从 materials 字段提取 size 和 duration
- **UI 优化**：界面重构，更清晰的状态显示

### v6.0.0

- **类型注解**：所有核心模块完整类型注解
- **测试框架**：70+ 测试用例，90%+ 覆盖率
- **代码质量**：pytest, ruff, black, mypy 集成
- **使用示例**：3 个完整示例脚本

### v5.x

- **代码重构**：拆分为 `scraper/` 包结构
- **增量更新**：基于 sitemap `lastmod`
- **本地解析**：BeautifulSoup 零成本提取

---

## License

MIT License

---

*Made for aaajiao*
