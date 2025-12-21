# 使用示例

本目录包含 aaajiao Portfolio Scraper 的各种使用示例。

## 📚 示例列表

### 1. 快速开始 - `quick_start.py`

**适合**: 第一次使用  
**学习内容**: 基本初始化、单个作品提取、结果导出

```bash
python examples/quick_start.py
```

**输出**:
- `output/quick_start_results.json` - JSON格式的作品数据
- `output/quick_start_portfolio.md` - Markdown格式的作品集

---

### 2. 批量提取 - `batch_extraction.py`

**适合**: 需要高效处理多个作品  
**学习内容**: 批量API使用、缓存策略、进度跟踪

```bash
python examples/batch_extraction.py
```

**特点**:
- 使用 Firecrawl 批量提取API
- 自动利用缓存减少API消耗
- 显示提取统计（缓存命中、新提取数量）

---

### 3. 增量爬取 - `incremental_scrape.py`

**适合**: 定期更新数据  
**学习内容**: 增量模式、sitemap比较、只处理更新

```bash
python examples/incremental_scrape.py
```

**工作原理**:
1. 第一次运行：获取所有作品
2. 后续运行：只获取新增或修改的作品（基于sitemap的lastmod）
3. 节省时间和API消耗

---

## 🎯 使用前准备

1. **配置API Key**
   ```bash
   cp ../.env.example ../.env
   # 编辑 .env 文件，添加你的 FIRECRAWL_API_KEY
   ```

2. **创建输出目录**
   ```bash
   mkdir -p output
   ```

3. **运行示例**
   ```bash
   python examples/quick_start.py
   ```

---

## 💡 最佳实践

### 节省API消耗

1. **启用缓存**（默认已启用）
   ```python
   scraper = AaajiaoScraper(use_cache=True)
   ```

2. **使用增量模式**
   ```python
   work_urls = scraper.get_all_work_links(incremental=True)
   ```

3. **选择合适的提取级别**
   - `quick` - 基本信息，消耗最少
   - `full` - 完整信息，消耗较多
   - `images_only` - 仅图片，适中

### 错误处理

```python
work_data = scraper.extract_work_details(url)
if work_data:
    # 处理数据
    print(f"成功：{work_data['title']}")
else:
    # 提取失败（可能是网络问题或API限制）
    print(f"失败：{url}")
```

### 查看日志

```python
import logging
logging.basicConfig(level=logging.INFO)  # 或 DEBUG 查看详细信息
```

---

## 🔧 自定义示例

基于这些示例，您可以轻松创建自己的脚本：

```python
from scraper import AaajiaoScraper

# 初始化
scraper = AaajiaoScraper(use_cache=True)

# 自定义处理逻辑
work_urls = scraper.get_all_work_links()
for url in work_urls:
    # 你的处理逻辑
    pass
```

---

## 📖 更多资源

- **API文档**: 查看 `scraper/` 目录下各模块的文档字符串
- **测试用例**: `tests/` 目录包含更多使用示例
- **主README**: `../README.md` 有完整的功能说明
- **贡献指南**: `../CONTRIBUTING.md` 了解开发流程

---

## ❓ 常见问题

**Q: 示例运行失败？**  
A: 确保已配置 `.env` 文件，并且 API key 有效

**Q: 如何处理大量作品？**  
A: 使用 `batch_extraction.py`，并考虑分批处理

**Q: 如何清除缓存重新爬取？**  
A: 删除 `.cache/` 目录

**Q: 可以并发提取吗？**  
A: 当前版本有速率限制保护，未来版本会支持async并发
