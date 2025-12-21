# aaajiao 作品集爬虫 / aaajiao Portfolio Scraper

从 [eventstructure.com](https://eventstructure.com) 自动抓取 aaajiao 的全部作品信息，生成结构化的 JSON 和 Markdown 文档。

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Tests](https://img.shields.io/badge/tests-70%20passing-green.svg)]()

---

## ✨ 核心特性

### 🚀 多模式爬取
- **基础模式**：从 sitemap.xml 解析作品链接
- **AI 提取模式**：使用 Firecrawl 智能提取结构化数据
- **批量提取模式**：高效处理多个作品页面
- **Discovery 模式**：处理无限滚动页面，自动发现新内容

### 💾 智能缓存系统
- 自动缓存提取结果，节省 API 调用成本
- 支持增量更新，只处理新增或修改的作品
- 多级缓存策略（通用缓存、sitemap 缓存、提取缓存）
- TTL 过期控制

### 🎯 灵活的提取级别
- **Quick 模式**：快速提取基本信息（标题、年份、类型）
- **Full 模式**：提取完整的作品数据（包含描述、材料、尺寸等）
- **Images Only**：仅提取高清图片链接

### 🛠️ 现代化架构
- ✅ **完整类型注解** - 支持 IDE 智能提示和类型检查
- ✅ **Google 风格文档** - 所有公共 API 都有详细说明
- ✅ **模块化设计** - 清晰的包结构，易于维护和扩展
- ✅ **自动化测试** - 70+测试用例，核心模块90%+覆盖率
- ✅ **代码质量工具** - Ruff, Black, MyPy 集成

### 📊 友好的界面
- **Streamlit GUI** - 零代码使用的图形界面
- **Python API** - 可编程接口，支持脚本集成
- **详细日志** - 完整的调试信息

---

## 📦 安装

### 前置要求

- Python 3.9+
- Firecrawl API Key（从 [firecrawl.dev](https://firecrawl.dev) 获取）

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
# 必需：Firecrawl API密钥
FIRECRAWL_API_KEY=your_api_key_here

# 可选：自定义配置
# CACHE_ENABLED=true
# RATE_LIMIT_CALLS_PER_MINUTE=10
```

---

## 📁 项目结构

```
aaajiao_scraper/
├── scraper/                  # 核心爬虫包
│   ├── __init__.py          # 导出主类 AaajiaoScraper
│   ├── constants.py         # 常量和配置（JSON schemas, prompts等）
│   ├── core.py              # 核心基类（RateLimiter, CoreScraper）
│   ├── basic.py             # 基础爬虫（sitemap解析、URL验证）
│   ├── firecrawl.py         # Firecrawl API集成
│   ├── cache.py             # 缓存系统（多级缓存策略）
│   ├── report.py            # 报告生成（JSON/Markdown导出）
│   └── py.typed             # 类型检查标记
├── tests/                   # 测试套件（70+测试用例）
│   ├── conftest.py          # pytest配置和fixtures
│   ├── test_core.py         # 核心功能测试
│   ├── test_cache.py        # 缓存系统测试
│   ├── test_basic.py        # 基础爬虫测试
│   ├── test_firecrawl.py    # Firecrawl集成测试
│   └── test_report.py       # 报告生成测试
├── examples/                # 使用示例
│   ├── quick_start.py       # 快速开始示例
│   ├── batch_extraction.py  # 批量提取示例
│   ├── incremental_scrape.py # 增量爬取示例
│   └── README.md            # 示例说明文档
├── scripts/                 # 调试脚本
├── app.py                   # Streamlit GUI应用
├── pyproject.toml           # 项目配置和依赖管理
├── .ruff.toml               # 代码质量配置
├── .env.example             # 环境变量模板
├── CONTRIBUTING.md          # 贡献指南
└── README.md                # 本文档
```

### 架构设计亮点

- **Mixin 模式**：功能模块化，`AaajiaoScraper` 继承多个 Mixin 类
- **分离关注点**：每个模块职责单一（缓存、爬取、报告分离）
- **类型安全**：完整的类型注解，支持 `mypy` 静态检查
- **测试覆盖**：核心模块达到 90%+ 测试覆盖率

---

## 🚀 使用方法

### 方式一：Web GUI (推荐)

启动 Streamlit 界面：

```bash
streamlit run app.py
```

浏览器会自动打开 `http://localhost:8501`

#### GUI 功能详解：

1. **Tab 1: Basic Scraper / 基础爬虫**
   - **原理**: 读取 `sitemap.xml` 爬取，适合全量备份
   - **增量模式**: 勾选 **Incremental Update** 可跳过未变动的作品
   - **优点**: 速度快，无需大量 Credits

2. **Tab 2: Quick Extract / 快速提取**
   - **原理**: 使用 `v2/extract` (LLM) 分析单页
   - **单页模式**: 输入 URL，直接提取所有文字和高清图
   - **开放搜索**: 不输 URL，直接问问题 (Agent Research)

3. **Tab 3: Batch Discovery / 批量发现**
   - **适用**: 针对作品列表页（如主页）
   - **流程**: **Scan** (自动滚屏) -> **Filter** (选择作品) -> **Extract** (批量提取)

### 方式二：Python API

查看 `examples/` 目录获取详细示例：

```python
from scraper import AaajiaoScraper

# 初始化
scraper = AaajiaoScraper(use_cache=True)

# 获取所有作品链接
work_urls = scraper.get_all_work_links(incremental=False)

# 提取单个作品
work_data = scraper.extract_work_details(work_urls[0])

# 保存结果
scraper.save_to_json("output/works.json")
scraper.generate_markdown("output/portfolio.md")
```

**更多示例**:
- `examples/quick_start.py` - 基础使用流程
- `examples/batch_extraction.py` - 批量提取模式
- `examples/incremental_scrape.py` - 增量爬取模式

---

## 🧪 开发

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

### 贡献指南

请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解：
- 开发环境设置
- 代码规范
- 提交规范
- Pull Request 流程

---

## ⚙️ 成本说明

Firecrawl V2 计费机制：

| 模式 | 底层技术 | 典型成本 | 适用场景 |
|------|---------|----------|----------|
| **HTML Scrape** | 纯 HTML 下载 | ~1 Credit | 基础爬虫 (Tab 1) |
| **LLM Extract** | HTML + AI 分析 | ~50 Credits | 快速提取 (Tab 2) / 批量提取 (Tab 3) |
| **Agent Search** | 自主搜索 + 浏览 | >100 Credits | 开放式提问 (Tab 2 无 URL) |

> 💡 **Tip**: 启用缓存功能（默认开启），重复抓取相同 URL 且 Prompt 不变时，**0 消耗**。

---

## 📁 输出文件

自动生成的文件结构：

```
aaajiao_scraper/
├── output/                  # 输出目录
│   ├── quick_start_results.json
│   ├── batch_extraction_results.json
│   └── incremental_TIMESTAMP.json
├── agent_output/            # Agent/Extract 模式输出
│   ├── report_TIMESTAMP.md
│   ├── data_TIMESTAMP.json
│   └── images_TIMESTAMP/    # 下载的高清图片
└── .cache/                  # 缓存文件
```

---

## 📝 更新日志

### v6.0 (2025-12-21) [Current] - 质量升级
- ✅ **类型注解**: 所有核心模块添加完整类型注解
- ✅ **文档字符串**: Google 风格文档，40+方法详细说明
- ✅ **测试框架**: 70个测试用例，核心模块90%+覆盖率
- ✅ **代码质量**: pytest, ruff, black, mypy 集成
- ✅ **使用示例**: 3个完整示例脚本
- ✅ **现代配置**: pyproject.toml, .ruff.toml 等

### v5.3 (2025-12-21)
- ♻️ **代码重构**: 拆分 monolithic 文件为 `scraper/` 包
- 📦 **脚本整理**: 移动调试脚本至 `scripts/` 目录
- 🔧 **Schema 修复**: 修复 `type` 字段冲突

### v5.2 (2025-12-21)
- 🔄 **增量更新**: 基于 sitemap `lastmod`
- 💾 **Auto-Save**: 防止数据丢失
- 🖼️ **本地图片报告**: Markdown 报告包含本地图片

---

## 🤝 贡献

欢迎贡献！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详情。

---

## 📄 License

MIT License

*Made with ❤️ for aaajiao*
