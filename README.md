# aaajiao 作品集爬虫 / aaajiao Portfolio Scraper

从 [eventstructure.com](https://eventstructure.com) 自动抓取 aaajiao 的全部作品信息，生成结构化的 JSON 和 Markdown 文档。

---

## ✨ 核心特性

- 🤖 **多模态 AI 提取**：
  - **Basic Scraper**: 基于规则的快速提取，成本低（1 credit/页）。
  - **Smart Agent**: 基于 LLM (v2/extract) 的智能理解，支持自定义 Prompt。
  - **Discovery Mode**: 智能滚屏扫描，解决无限滚动加载问题。
- 💰 **成本透明**：GUI 界面实时显示预估积分消耗（Batch/Extract）。
- 🎨 **一键高清图**：自动识别 `src_o` 属性，优先下载高清作品原图。
- 📊 **增量更新**：Basic Scraper 支持基于 sitemap `lastmod` 的增量检测，只抓取新页面。
- 💾 **自动保存**：爬虫运行期间每 5 个作品自动保存，防止数据丢失。
- 📦 **模块化架构**：代码重构为 `scraper/` 包结构，更易维护和扩展。
- 🔒 **安全配置**：API Key 通过环境变量管理，不会泄露。

---

## 📦 安装与配置

### 1. 安装依赖

```bash
pip3 install requests beautifulsoup4 tqdm streamlit pandas python-dotenv
```

### 2. 项目结构

```
aaajiao_scraper/
├── app.py                  # Streamlit GUI 入口
├── scraper/                # 核心爬虫包 (Package)
│   ├── basic.py            # 基础爬虫 Mixin
│   ├── firecrawl.py        # Firecrawl AI Mixin
│   ├── cache.py            # 缓存 Mixin
│   └── ...
├── scripts/                # 调试与工具脚本
│   ├── debug_extract.py    # 提取调试
│   ├── verify_portfolio.py # 结果验证
│   └── ...
└── .env                    # 配置文件
```

### 3. 配置 API Key

在项目根目录创建 `.env` 文件：

```bash
# .env
FIRECRAWL_API_KEY=your-api-key-here
```

---

## 🚀 使用方法

### 方式一：Web GUI (推荐)

启动 Streamlit 界面：

```bash
streamlit run app.py
```
浏览器会自动打开 `http://localhost:8501`.

#### 界面功能详解：

1.  **Tab 1: Basic Scraper / 基础爬虫**
    *   **原理**: 读取 `sitemap.xml` 爬取。适合全量备份。
    *   **新增**: 勾选 **Incremental Update** 可跳过未变动的作品。
    *   **优点**: 速度快，无需大量 Credits。

2.  **Tab 2: Quick Extract / 快速提取**
    *   **原理**: 使用 `v2/extract` (LLM) 分析单页。
    *   **单页模式**: 输入 URL，直接提取所有文字和高清图。
    *   **开放搜索**: 不输 URL，直接问问题 (Agent Research)。

3.  **Tab 3: Batch Discovery / 批量发现**
    *   **适用**: 针对作品列表页（如主页）。
    *   **流程**: **Scan** (自动滚屏) -> **Filter** (选择作品) -> **Extract** (批量提取)。

### 方式二：命令行脚本

所有调试和功能脚本现已移至 `scripts/` 目录。

例如，手动测试提取：

```bash
cd scripts
python3 debug_extract.py
```

---

## ⚙️ 成本说明 (Cost Model)

Firecrawl V2 计费机制如下：

| 模式 | 底层技术 | 典型成本 | 适用场景 |
|------|---------|----------|----------|
| **HTML Scrape** | 纯 HTML 下载 | ~1 Credit | 基础爬虫 (Tab 1) |
| **LLM Extract** | HTML + AI 分析 | ~50 Credits | 快速提取 (Tab 2) / 批量提取 (Tab 3) |
| **Agent Search** | 自主搜索 + 浏览 | >100 Credits | 开放式提问 (Tab 2 无 URL) |

> 💡 **Tip**: 为了省钱，建议启用缓存功能（默认开启），重复抓取相同 URL 且 Prompt 不变时，**0 消耗**。

---

## 📁 输出文件

自动生成的文件结构：

```
aaajiao_scraper/
├── aaajiao_works.json      # 基础爬虫数据
├── aaajiao_portfolio.md    # 基础爬虫 Markdown
├── agent_output/           # Agent/Extract 模式输出
│   ├── report_TIMESTAMP.md
│   ├── data_TIMESTAMP.json
│   └── images_TIMESTAMP/   # 下载的高清图片
└── .cache/                 # 缓存文件
```

---

## 📝 更新日志

### v5.3 (2025-12-21) [Current]
- ♻️ **代码重构**: 拆分 monolithic 文件为 `scraper/` 包，提升维护性。
- 📦 **脚本整理**: 移动调试脚本至 `scripts/` 目录。
- 🔧 **Schema 修复**: 修复 `type` 字段冲突问题，重命名为 `category`。

### v5.2 (2025-12-21)
- 🔄 **Basic Scraper 增量更新**: 基于 sitemap `lastmod`。
- 💾 **Auto-Save**: 防止数据丢失。
- 🖼️ **本地图片报告**: Markdown 报告包含本地图片。

### v5.1 (2025-12-21)
- 💾 **智能缓存系统**: Extract 和 Discovery 结果持久化缓存。
- ⚡ **Quick/Full 模式**: 提取级别选择 (Quick/Full/Images Only)。
- 🔧 **Prompt 模板库**: 内置优化模板。

### v5.0 (2025-12-21)
- ✨ **Smart Discovery**: UI 重构，支持 Batch Discovery。
- 🔄 **V2 API**: 全面迁移至 Firecrawl V2。

---

## 📄 License

MIT License

*Made with ❤️ for aaajiao*
