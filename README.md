# aaajiao 作品集爬虫 / aaajiao Portfolio Scraper

从 [eventstructure.com](https://eventstructure.com) 自动抓取 aaajiao 的全部作品信息，生成结构化的 JSON 和 Markdown 文档。

---

## ✨ 功能特性

- 🤖 **AI 智能提取**：使用 Firecrawl AI 精准识别标题、年份、材质、描述等信息
- 💾 **本地缓存**：已抓取的作品自动缓存，避免重复调用 API
- 🚦 **速率控制**：内置智能限流，不会触发 API 限制
- 📊 **实时进度**：tqdm 进度条显示抓取状态
- 🔒 **安全配置**：API Key 通过环境变量管理，不会泄露

---

## 📦 安装

### 1. 安装依赖

```bash
pip3 install requests beautifulsoup4 tqdm
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

### 方式一：双击启动（最简单）

1. 在 Finder 中双击 `start_gui.command` 文件
2. 浏览器会自动打开 Web 界面

> 💡 如果双击没反应，先运行：`chmod +x start_gui.command`

### 方式二：命令行运行

```bash
cd /Users/aaajiao/Documents/aaajiao_scraper
python3 aaajiao_scraper.py
```

### 方式三：Web GUI

```bash
python3 -m streamlit run app.py
```

然后在浏览器中打开 `http://localhost:8501`

### 方式四：作为模块导入

```python
from aaajiao_scraper import AaajiaoScraper

scraper = AaajiaoScraper()
scraper.scrape_all()
scraper.save_to_json('output.json')
scraper.generate_markdown('output.md')
```

---

## ⚙️ 配置选项

### 禁用缓存

如需强制重新抓取所有作品：

```python
scraper = AaajiaoScraper(use_cache=False)
```

### 清除缓存

```bash
rm -rf .cache/
```

---

## 📁 输出文件

| 文件 | 格式 | 说明 |
|------|------|------|
| `aaajiao_works.json` | JSON | 结构化数据，适合程序处理 |
| `aaajiao_portfolio.md` | Markdown | 人类可读，适合浏览和导出 |

### JSON 数据结构

```json
{
  "url": "https://eventstructure.com/work-name",
  "title": "Work Title",
  "title_cn": "作品中文名",
  "year": "2024",
  "type": "Video Installation",
  "materials": "LED screen, 3D printing",
  "description_en": "English description...",
  "description_cn": "中文描述...",
  "video_link": "https://vimeo.com/..."
}
```

---

## ⏱️ 性能说明

| 场景 | 预计时间 |
|------|----------|
| 首次运行（约 180 个作品） | ~36 分钟 |
| 再次运行（有缓存） | ~10 秒 |
| 部分更新（新增作品） | 视数量而定 |

> 🔧 速率限制：每 12 秒调用一次 Firecrawl API（5 calls/min）

---

## 🗂️ 项目结构

```
aaajiao_scraper/
├── aaajiao_scraper.py    # 主爬虫脚本
├── app.py                # Streamlit Web GUI
├── .env                  # API Key 配置（需自行创建）
├── .gitignore            # Git 忽略规则
├── .cache/               # 缓存目录（自动创建）
├── aaajiao_works.json    # 输出：JSON
└── aaajiao_portfolio.md  # 输出：Markdown
```

---

## ❓ 常见问题

### Q: 提示 "未找到 Firecrawl API Key"

确保 `.env` 文件存在且格式正确：
```
FIRECRAWL_API_KEY=fc-xxxxxxxxxxxx
```

### Q: 出现 429 Rate Limit 错误

正常现象，程序会自动等待并重试（最多 3 次）。

### Q: 如何只抓取部分作品？

修改代码中的 `get_all_work_links()` 方法，添加过滤条件。

### Q: 缓存数据在哪里？

`.cache/` 目录下，以 URL 的 MD5 哈希命名的 `.pkl` 文件。

---

## 📝 更新日志

### v3.0 (2024-12-16)
- ✨ 集成 Firecrawl AI 提取引擎
- 🔒 API Key 安全管理
- 💾 本地缓存系统
- 📊 tqdm 进度条
- 🚦 智能速率控制

### v2.0
- 使用 sitemap.xml 获取完整作品列表
- 优化 HTML 解析逻辑

### v1.0
- 初始版本

---

## 📄 License

MIT License

---

*Made with ❤️ for aaajiao*
