# Claude Code 工具调用优化指南

**项目:** claw-code-tingfeng  
**生成时间:** 2026-04-16

---

## 📋 问题描述

Claude Code 在搜索文件时使用了错误的模式 `src/**/tool*.py`,导致:
1. Glob 工具找不到匹配的文件
2. Bash 命令执行卡住或超时
3. 工具调用效率低下

---

## 🔍 根本原因

### 1. **错误的文件搜索模式**

❌ **错误:** `src/**/tool*.py`
- 这个模式期望文件名以 "tool" 开头
- 但实际的工具文件命名是 `*_tool.py` 或其他格式

✅ **正确:** `src/tools_runtime/*.py`
- 所有工具文件都在 `tools_runtime/` 目录中
- 直接指定目录更高效

### 2. **项目结构不匹配预期**

Claude Code 可能基于其他项目的经验,假设工具文件分散在各个子目录中,但实际上:

```
src/
├── tools_runtime/          ← 所有工具都在这里
│   ├── bash_tool.py
│   ├── grep_tool.py
│   ├── file_read_tool.py
│   └── ... (42 个 Python 文件)
├── agent/
├── core/
├── llm/
└── ...
```

---

## 💡 解决方案

### 方案 A: 使用正确的搜索路径(推荐)

当需要查找工具相关文件时,使用:

```python
# ✅ 正确 - 直接指定目录
Glob(pattern="src/tools_runtime/*.py")

# ✅ 正确 - 搜索特定工具
Grep(pattern="class.*Tool", path="src/tools_runtime/")

# ❌ 错误 - 过于宽泛的模式
Glob(pattern="src/**/tool*.py")
```

### 方案 B: 创建项目索引文件

创建一个索引文件帮助 Claude Code 快速定位:

**文件:** `PROJECT_INDEX.md`

```markdown
# 项目文件索引

## 工具系统 (Tools Runtime)
- 位置: `src/tools_runtime/`
- 文件数: 42 个 Python 文件
- 主要工具:
  - Bash: `bash_tool.py`, `bash_executor.py`
  - 文件操作: `file_read_tool.py`, `file_edit_tool.py`
  - 搜索: `grep_tool.py`, `glob_tool.py`
  - 代码编辑: `search_replace.py`, `udiff_tool.py`

## Agent 系统
- 位置: `src/agent/`
- ...

## 核心引擎
- 位置: `src/core/`
- ...
```

### 方案 C: 优化 Claude Code 配置

在 `.claude/settings.json` 或项目级别的配置中添加提示:

```json
{
  "projectContext": {
    "toolsLocation": "src/tools_runtime/",
    "preferredSearchPatterns": [
      "src/tools_runtime/*.py",
      "src/agent/*.py",
      "src/core/*.py"
    ]
  }
}
```

---

## 🛠️ 实用技巧

### 1. **优先使用 Grep 而非 Glob**

当你知道要搜索的内容时,Grep 比 Glob 更高效:

```python
# ✅ 更好 - 直接搜索内容
Grep(pattern="def execute", path="src/tools_runtime/")

# ⚠️ 较慢 - 先找文件再读取
Glob(pattern="src/tools_runtime/*.py")
# 然后对每个文件 Read
```

### 2. **批量读取相关文件**

如果需要检查多个工具文件,一次性列出目录:

```python
# 第一步: 列出目录
ListDir(path="src/tools_runtime/")

# 第二步: 根据需要读取特定文件
Read(file_path="src/tools_runtime/bash_tool.py")
Read(file_path="src/tools_runtime/grep_tool.py")
```

### 3. **使用项目特定的搜索快捷方式**

创建常用的搜索命令别名:

```bash
# 在 .bashrc 或 PowerShell profile 中
alias find-tools="ls src/tools_runtime/*.py"
alias find-agents="ls src/agent/*.py"
```

---

## 📊 当前项目工具文件统计

运行 `python check_tools_structure.py` 查看详细信息:

```
✅ tools_runtime 目录: 42 个 Python 文件

分类统计:
- 基础工具: 4 个 (base.py, types.py, tool_interface.py, registry.py)
- 文件操作: 3 个 (file_read_tool.py, file_edit_tool.py, file_processor.py)
- 代码编辑: 4 个 (search_replace.py, edit_parser.py, udiff_tool.py, ...)
- 搜索工具: 4 个 (grep_tool.py, glob_tool.py, symbol_find_tool.py, ...)
- Bash 相关: 4 个 (bash_tool.py, bash_executor.py, bash_security.py, ...)
- Lint 工具: 4 个 (linter.py, linter_linter.py, linter_python.py, ...)
- 其他工具: 4 个 (clipboard_tool.py, scrape_tool.py, voice_tool.py, ...)

子目录:
- code_edit/: 8 个文件
- implementations/: 2 个文件
- sandbox/: 5 个文件
```

---

## 🚀 性能优化建议

### 1. **减少不必要的文件搜索**

Claude Code 有时会过度搜索文件。可以通过以下方式优化:

- ✅ 明确指定文件路径
- ✅ 使用更精确的搜索模式
- ❌ 避免使用 `**` 通配符扫描整个项目

### 2. **利用缓存**

Claude Code 会缓存最近访问的文件。重复访问相同文件会更快。

### 3. **并行 vs 串行操作**

- **并行:** 读取多个独立文件时可以并行
- **串行:** 编辑文件时必须串行(避免冲突)

### 4. **监控工具调用延迟**

如果感觉工具调用慢,检查:
- Hooks 是否过多(每次操作都触发质量检查等)
- 是否有文件锁冲突
- 网络延迟(如果使用远程 LLM)

---

## 🔧 故障排除

### 问题 1: Glob 找不到文件

**症状:** `The Glob tool couldn't find any files matching...`

**解决:**
1. 检查路径是否正确(区分大小写)
2. 使用 `ListDir` 确认目录存在
3. 尝试更简单的模式(如 `*.py` 而非 `**/*.py`)

### 问题 2: Bash 命令卡住

**症状:** Bash 命令长时间无响应

**解决:**
1. 检查命令是否有交互式输入
2. 添加超时参数
3. 使用 `&` 后台运行长时间任务
4. 检查是否有进程锁

### 问题 3: 文件编辑冲突

**症状:** `Error editing file`

**解决:**
1. 检查文件是否被其他进程锁定
2. 确保没有并发编辑同一文件
3. 使用 `git status` 检查文件状态
4. 尝试重新加载文件

---

## 📚 相关资源

- [check_tools_structure.py](./check_tools_structure.py) - 工具文件检查脚本
- [src/tools_runtime/__init__.py](./src/tools_runtime/__init__.py) - 工具注册和导出
- [CLAUDE.md](./CLAUDE.md) - 项目上下文和指令

---

## 📝 更新日志

- **2026-04-16:** 初始版本,记录工具调用优化建议
- **2026-04-16:** 添加工具文件统计和诊断脚本
