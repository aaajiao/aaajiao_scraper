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
- 📦 **本地图片报告**：生成的 Markdown 报告包含本地下载的高清图片，支持离线查看。
- 🔒 **安全配置**：API Key 通过环境变量管理，不会泄露。

---

## 📦 安装

### 1. 安装依赖

```bash
pip3 install requests beautifulsoup4 tqdm streamlit pandas
```

### 2. 配置 API Key

在项目根目录创建 `.env` 文件：

```bash
# .env
FIRECRAWL_API_KEY=your-api-key-here
```

> 💡 获取 API Key：访问 [firecrawl.dev](https://firecrawl.dev) 注册账号

---

## 🚀 使用方法

### 方式一：Web GUI (推荐)

```bash
python3 -m streamlit run app.py
```
浏览器会自动打开 `http://localhost:8501`.

#### 界面功能详解：

1.  **Tab 1: Basic Scraper / 基础爬虫**
    *   **原理**: 读取 `sitemap.xml`，使用固定规则爬取。
    *   **优点**: 速度快，成本极低 (仅 URL 获取费)。
    *   **新增**: 支持 **Incremental Update**，自动跳过未更新页面。
    *   **缺点**: 只能抓标准作品页，无法自定义字段。

2.  **Tab 2: Quick Extract / 快速提取**
    *   **原理**: 使用 `v2/extract` (LLM) 分析单页。
    *   **单页模式**: 输入 URL，直接提取所有文字和高清图。成本 ~75 credits/页。
    *   **开放搜索**: 不输 URL，直接问问题 (Agent Research)。

3.  **Tab 3: Batch Discovery / 批量发现**
    *   **适用**: 针对作品列表页、画廊页（如主页）。
    *   **流程**: 
        1. **Scan**: 自动滚动屏幕 (Auto/Horizontal/Vertical) 扫描所有链接。
        2. **Filter**: 勾选你感兴趣的作品。
        3. **Extract**: 批量发送给 AI 进行提取。

### 方式二：命令行 CLI

#### 1. 简单 Agent 查询

```bash
python3 aaajiao_scraper.py --agent "Find all video installations by aaajiao"
```

#### 2. 批量已知 URL 提取 (New!)

新版支持将 `--agent` 配合 `--urls` 使用，调用高效的 `v2/extract` 接口：

```bash
python3 aaajiao_scraper.py \
  --agent "Extract details and high-res images" \
  --urls "https://link1.com, https://link2.com" \
  --max-credits 2  # 限制处理前2个链接
```

#### 3. 智能发现模式 (Discovery)

```bash
python3 aaajiao_scraper.py \
  --discovery-url "https://eventstructure.com" \
  --scroll-mode auto \
  --output-dir ./hybrid_output
```

---

## ⚙️ 成本说明 (Cost Model)

Firecrawl V2 计费机制如下：

| 模式 | 底层技术 | 典型成本 | 适用场景 |
|------|---------|----------|----------|
| **HTML Scrape** | 纯 HTML 下载 | ~1 Credit | 基础爬虫 (Tab 1) |
| **LLM Extract** | HTML + AI 分析 | ~50-80 Credits | 快速提取 (Tab 2) / 批量发现 (Tab 3) |
| **Agent Search** | 自主搜索 + 浏览 | >100 Credits | 开放式提问 (Tab 2 无 URL) |

> 💡 **Tip**: 为了省钱，建议先用 Discovery 模式扫描出链接，然后只勾选真正需要的作品进行 Extract。

---

## 📁 输出文件

自动生成的文件结构：

```
aaajiao_scraper/
├── aaajiao_works.json      # 基础爬虫数据
├── aaajiao_portfolio.md    # 基础爬虫 Markdown
├── agent_output/           # Agent/Extract 模式输出
│   ├── artwork_report.md
│   ├── agent_result.json
│   └── images/             # 下载的高清图片
└── .cache/                 # 缓存文件
```

---

## 📝 更新日志

### v5.1 (2024-12-21)
- 💾 **智能缓存系统**: Extract 和 Discovery 结果自动缓存，重复调用成本→0。
- ⚡ **Quick/Full 模式**: 支持快速提取(核心字段)和完整提取(全部信息+图片)两种模式。
- 📊 **缓存统计**: GUI 实时显示缓存命中数和预估节省成本。
- 🔧 **Prompt 模板库**: 内置优化的提取模板，开箱即用。

### v5.2 (2024-12-21)
- 🔄 **Basic Scraper 增量更新**: 检测 sitemap `lastmod`，只抓取更新页面。
- 💾 **Auto-Save**: 每 5 个作品自动保存，防止中断丢失数据。
- 🖼️ **本地图片报告**: Markdown 报告引用本地下载的图片，支持离线预览。
- 📐 **GUI 优化**: 提取模式选择器移至扫描结果后，符合直觉。

### v5.0 (2024-12-21)
- ✨ **Smart Discovery**: 完整的“扫描-筛选-提取”工作流。
- 🔄 **V2 Extract**: 修复 400 错误，支持批量 URL 的 AI 提取。
- 🖼️ **高清图支持**: 自动提取 `src_o` 属性，拒绝缩略图。
- 🖥️ **GUI 重构**: Tab 重命名为 Quick Extract / Batch Discovery。

### v4.0
- ⚡️ V2 API 迁移：全面升级到 Firecrawl V2。

---

## 📄 License

MIT License

*Made with ❤️ for aaajiao*
