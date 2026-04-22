# Claude Code 快速参考 - claw-code-tingfeng

## 📁 关键目录

| 目录 | 用途 | 文件数 |
|------|------|--------|
| `src/tools_runtime/` | **工具系统** (最重要!) | 42 .py |
| `src/agent/` | Agent 实现 | 34 .py |
| `src/core/` | 核心引擎 | 68 .py |
| `src/llm/` | LLM 集成 | 36 .py |
| `src/workflow/` | 工作流引擎 | 38 .py |
| `src/cli/` | 命令行界面 | 34 .py |

## 🔍 正确的搜索模式

### ✅ 推荐
```python
# 查找工具文件
Glob(pattern="src/tools_runtime/*.py")
Grep(pattern="class.*Tool", path="src/tools_runtime/")

# 查找特定工具
Read(file_path="src/tools_runtime/bash_tool.py")
Read(file_path="src/tools_runtime/grep_tool.py")

# 列出目录
ListDir(path="src/tools_runtime/")
```

### ❌ 避免
```python
# 这些模式会失败或很慢
Glob(pattern="src/**/tool*.py")      # 找不到文件
Glob(pattern="**/*.py")               # 太宽泛
Grep(pattern="TODO")                  # 没有指定路径
```

## 🛠️ 常用命令

### 运行测试
```bash
# 所有测试
python -m pytest tests/ -v

# 特定测试文件
python -m pytest tests/core/test_replay_engine.py -v

# 带覆盖率
python -m pytest tests/ --cov=src --cov-report=html
```

### 清理缓存
```bash
# Windows
cleanup.bat

# Linux/Mac
find . -type d -name __pycache__ -exec rm -rf {} +
rm -rf .pytest_cache htmlcov .coverage
```

### 检查项目结构
```bash
python check_tools_structure.py
```

## ⚡ 性能提示

1. **优先使用 Grep** - 比 Glob + Read 快
2. **指定具体路径** - 避免全局搜索
3. **批量读取** - 一次读取多个相关文件
4. **利用缓存** - 重复访问相同文件更快

## 🐛 常见问题

### Q: Glob 找不到文件?
**A:** 检查路径是否正确,使用 `ListDir` 确认

### Q: Bash 命令卡住?
**A:** 
- 检查是否有交互式输入
- 添加超时
- 后台运行: `command &`

### Q: 文件编辑失败?
**A:**
- 检查文件锁
- 避免并发编辑
- 运行 `cleanup.bat`

## 📊 工具文件分类

```
src/tools_runtime/
├── 基础工具 (4)
│   ├── base.py
│   ├── types.py
│   ├── tool_interface.py
│   └── registry.py
├── 文件操作 (3)
│   ├── file_read_tool.py
│   ├── file_edit_tool.py
│   └── file_processor.py
├── 代码编辑 (4)
│   ├── search_replace.py
│   ├── edit_parser.py
│   ├── udiff_tool.py
│   └── udiff_parser.py
├── 搜索工具 (4)
│   ├── grep_tool.py
│   ├── glob_tool.py
│   ├── symbol_find_tool.py
│   └── search_v2_tool.py
├── Bash (4)
│   ├── bash_tool.py
│   ├── bash_executor.py
│   ├── bash_security.py
│   └── bash_constants.py
├── Lint (4)
│   ├── linter.py
│   ├── linter_linter.py
│   ├── linter_python.py
│   └── linter_tree_sitter.py
└── 其他 (4+)
    ├── clipboard_tool.py
    ├── scrape_tool.py
    ├── voice_tool.py
    └── watch_tool.py
```

## 🔗 相关文档

- [CLAUDE_CODE_OPTIMIZATION.md](./CLAUDE_CODE_OPTIMIZATION.md) - 详细优化指南
- [check_tools_structure.py](./check_tools_structure.py) - 工具检查脚本
- [cleanup.bat](./cleanup.bat) - 清理脚本
- [CLAUDE.md](./CLAUDE.md) - 项目上下文

---

**最后更新:** 2026-04-16  
**版本:** 1.0
