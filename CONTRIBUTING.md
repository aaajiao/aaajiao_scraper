# Contributing to aaajiao Scraper

感谢您对 aaajiao Scraper 项目的关注！我们欢迎任何形式的贡献。

## 🚀 快速开始

### 1. 环境设置

```bash
# Clone the repository
git clone https://github.com/yourusername/aaajiao-scraper.git
cd aaajiao-scraper

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Edit .env and add your FIRECRAWL_API_KEY
```

### 2. 配置 API Key

在 `.env` 文件中填入您的 Firecrawl API Key：

```
FIRECRAWL_API_KEY=fc-your-actual-key
```

## 📝 开发流程

### 代码规范

我们使用以下工具确保代码质量：

- **Ruff**: 代码检查和自动格式化
- **Black**: 代码格式化（备用）
- **MyPy**: 类型检查
- **Pytest**: 单元测试

### 开发前检查

运行以下命令确保代码符合规范：

```bash
# 格式化代码
ruff format .

# 检查代码质量
ruff check .

# 自动修复可修复的问题
ruff check --fix .

# 类型检查
mypy scraper/

# 运行测试
pytest

# 查看测试覆盖率
pytest --cov=scraper --cov-report=html
```

### Git Commit 规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**类型 (Type)**:
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `style`: 代码格式调整（不影响功能）
- `refactor`: 重构（既不是新功能也不是 bug 修复）
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建过程或辅助工具的变动

**示例**:
```
feat(firecrawl): add async extraction support

Implement async/await pattern for batch extraction to improve performance.
Uses aiohttp for concurrent API calls.

Closes #42
```

## 🧪 测试指南

### 编写测试

测试文件应放在 `tests/` 目录下，命名为 `test_*.py`。

```python
# tests/test_cache.py
import pytest
from scraper import AaajiaoScraper

def test_cache_hit():
    """Test cache returns cached data on second call"""
    scraper = AaajiaoScraper(use_cache=True)
    # Test implementation
    ...

@pytest.mark.slow
def test_large_dataset():
    """Test handling of large datasets"""
    ...
```

### 运行特定测试

```bash
# 运行单个文件
pytest tests/test_cache.py

# 运行单个测试
pytest tests/test_cache.py::test_cache_hit

# 跳过慢速测试
pytest -m "not slow"

# 跳过需要网络的测试
pytest -m "not requires_network"
```

## 📚 文档规范

### Docstring 格式

使用 Google 风格的文档字符串：

```python
def extract_work_details(
    self, 
    url: str, 
    retry_count: int = 0
) -> Optional[Dict[str, Any]]:
    """
    使用 Firecrawl AI 提取作品详情。
    
    Args:
        url: 作品页面 URL
        retry_count: 当前重试次数，默认为 0
    
    Returns:
        提取的作品数据字典，失败返回 None
        
    Raises:
        RequestException: 网络请求失败时抛出
        
    Example:
        >>> scraper = AaajiaoScraper()
        >>> data = scraper.extract_work_details("https://example.com/work/1")
        >>> print(data['title'])
        'Work Title'
    """
    ...
```

## 🔀 Pull Request 流程

1. **Fork** 本仓库
2. 创建 **feature branch** (`git checkout -b feat/amazing-feature`)
3. **Commit** 您的更改 (`git commit -m 'feat: add amazing feature'`)
4. **Push** 到分支 (`git push origin feat/amazing-feature`)
5. 提交 **Pull Request**

### PR 检查清单

在提交 PR 前，请确保：

- [ ] 所有测试通过 (`pytest`)
- [ ] 代码格式正确 (`ruff format .` 和 `ruff check .`)
- [ ] 类型检查通过 (`mypy scraper/`)
- [ ] 添加了必要的测试
- [ ] 更新了相关文档
- [ ] 提交信息符合规范
- [ ] 代码覆盖率未降低

## 🐛 报告 Bug

通过 [GitHub Issues](https://github.com/yourusername/aaajiao-scraper/issues) 报告 bug。

请包含：
- Bug 描述
- 复现步骤
- 期望行为
- 实际行为
- 环境信息（Python 版本、OS 等）
- 相关日志或截图

## 💡 功能建议

我们欢迎新功能建议！请先创建 Issue 讨论，避免重复工作。

---

## 📧 联系方式

如有问题，请通过以下方式联系：

- GitHub Issues
- Email: your-email@example.com

再次感谢您的贡献！ 🎉
