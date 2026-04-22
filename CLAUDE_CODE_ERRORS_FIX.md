# Claude Code 常见错误修复指南

**最后更新:** 2026-04-16  
**版本:** 1.1

---

## 🚨 常见错误及解决方案

### 错误 1: Agent type not found

#### 症状
```
Error: Agent type 'everything-claude-code:explore-agent' not found
Available agents: general-purpose, Explore, Plan, everything-claude-code:planner, ...
```

#### 原因
使用了不存在的 Agent 名称。

#### 解决方案

**步骤 1:** 从错误信息中复制可用的 Agent 列表

**步骤 2:** 选择正确的 Agent

| 用途 | 正确的 Agent 名称 |
|------|------------------|
| 探索项目 | `Explore` (内置，无命名空间) |
| 规划任务 | `everything-claude-code:planner` |
| 代码审查 | `everything-claude-code:code-reviewer` |
| 架构设计 | `everything-claude-code:architect` |
| TDD 开发 | `everything-claude-code:tdd-guide` |
| 安全审查 | `everything-claude-code:security-reviewer` |

**步骤 3:** 使用正确的名称

```python
# ❌ 错误
subagent_type="everything-claude-code:explore-agent"

# ✅ 正确 - 使用内置 Explore
subagent_type="Explore"

# ✅ 正确 - 使用 ECC planner
subagent_type="everything-claude-code:planner"
```

#### 快速参考

**ECC 插件 Agents (需要命名空间):**
```
everything-claude-code:planner
everything-claude-code:architect
everything-claude-code:code-reviewer
everything-claude-code:security-reviewer
everything-claude-code:tdd-guide
everything-claude-code:build-error-resolver
everything-claude-code:e2e-runner
... (见完整列表在 AGENT_NAMESPACE_GUIDE.md)
```

**内置 Agents (不需要命名空间):**
```
Explore
Plan
general-purpose
statusline-setup
claude-code-guide
```

**其他插件 Agents:**
```
python-development:python-pro
python-development:django-pro
javascript-typescript:typescript-pro
backend-development:backend-architect
...
```

---

### 错误 2: File not found

#### 症状
```
Error: File not found - src\core\config.py
```

#### 原因
文件路径错误或文件不存在。

#### 解决方案

**步骤 1:** 先检查目录结构
```python
ListDir(path="src/core/")
```

**步骤 2:** 确认文件存在后再操作
```python
# ❌ 错误 - 假设文件存在
Write(file_path="src/core/config.py", content="...")

# ✅ 正确 - 先检查
if Path("src/core/config.py").exists():
    # 编辑现有文件
    Edit(...)
else:
    # 创建新文件或调整路径
    Write(file_path="src/core/config/feature_flags.py", ...)
```

**步骤 3:** 使用正确的路径

本项目配置系统结构:
```
src/core/
├── config/              ← 配置目录 (不是 config.py!)
│   ├── feature_flags.py
│   ├── settings.py
│   └── ...
├── exceptions.py
└── replay_engine.py
```

---

### 错误 3: Glob pattern not matching

#### 症状
```
The Glob tool couldn't find any files matching src/**/tool*.py
```

#### 原因
搜索模式与实际文件命名不匹配。

#### 解决方案

**步骤 1:** 先用 ListDir 查看实际结构
```python
ListDir(path="src/")
# 发现工具在 tools_runtime/ 目录
```

**步骤 2:** 使用正确的搜索模式
```python
# ❌ 错误 - 假设文件名以 tool 开头
Glob(pattern="src/**/tool*.py")

# ✅ 正确 - 指定具体目录
Glob(pattern="src/tools_runtime/*.py")

# ✅ 更好 - 直接列出目录
ListDir(path="src/tools_runtime/")
```

**步骤 3:** 记住项目的文件组织
- 工具文件: `src/tools_runtime/*.py` (42 个文件)
- 配置文件: `src/core/config/*.py`
- Agent 定义: `agents/*.md`
- Skills: `skills/*/SKILL.md`

---

### 错误 4: Bash command hangs

#### 症状
Bash 命令长时间无响应，Claude Code 停止回复。

#### 原因
1. 交互式输入等待
2. PowerShell 模块问题
3. 长时间运行的命令

#### 解决方案

**方法 1:** 添加超时
```bash
timeout 30 your_command
```

**方法 2:** 后台运行
```bash
your_command &
```

**方法 3:** 使用 Python 替代复杂命令
```bash
# ❌ 可能卡住
ls -la | grep pattern | awk '{print $1}'

# ✅ 更可靠
python -c "import os; print([f for f in os.listdir('.') if 'pattern' in f])"
```

**方法 4:** 修复 PowerShell (如果频繁出现)
```powershell
# 重启 PowerShell
exit
# 然后重新打开

# 或更新 PowerShell
winget install Microsoft.PowerShell
```

---

### 错误 5: Settings.json not found

#### 症状
```
Error reading C:\project\.claude\settings.json - File not found
```

#### 原因
Claude Code 在错误的位置查找 settings.json。

#### 解决方案

**理解配置层级:**

1. **用户级别配置** (全局)
   ```
   C:\Users\<username>\.claude\settings.json
   ```
   - 所有项目共享
   - 插件配置
   - Hooks 配置

2. **项目级别配置** (可选)
   ```
   <project>/.claude/settings.local.json
   ```
   - 仅当前项目
   - 权限覆盖
   - 本地设置

**检查当前配置:**
```bash
# 用户级别
cat ~/.claude/settings.json

# 项目级别
cat .claude/settings.local.json
```

**如果需要项目级 hooks 配置:**

在项目根目录创建 `.claude/settings.local.json`:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "black --check ."
          }
        ]
      }
    ]
  }
}
```

**注意:** 大多数配置应该在用户级别的 `settings.json` 中。

---

## 🔧 预防性措施

### 1. 始终验证文件存在性

```python
# 好习惯
ListDir(path="target/directory/")
# 然后再 Read/Edit/Write
```

### 2. 使用正确的 Agent 名称

保存常用 Agent 列表:
```python
# 内置 Agents
BUILTIN_AGENTS = ["Explore", "Plan", "general-purpose"]

# ECC Agents (需要命名空间)
ECC_AGENTS = [
    "everything-claude-code:planner",
    "everything-claude-code:architect",
    "everything-claude-code:code-reviewer",
    # ...
]
```

### 3. 了解项目结构

为每个项目创建快速参考:
```markdown
# 项目文件组织

- 工具: src/tools_runtime/
- 配置: src/core/config/
- Agents: agents/
- Skills: skills/
- 测试: tests/
```

### 4. 定期检查配置

运行诊断脚本:
```bash
cd ~/.claude
python diagnose_claude_cli.py
```

---

## 📋 快速故障排除清单

当 Claude Code 停止响应时:

1. **检查最后的错误信息**
   - 是否有 "Agent type not found"?
   - 是否有 "File not found"?
   - 是否有 "Glob pattern" 错误?

2. **验证 Agent 名称**
   ```
   从错误信息中复制可用 agents 列表
   选择正确的 agent 名称
   ```

3. **检查文件路径**
   ```python
   ListDir(path="parent/directory/")
   # 确认文件存在
   ```

4. **简化命令**
   ```bash
   # 避免复杂的管道
   # 使用 Python 替代
   ```

5. **重启会话**
   - 如果完全卡住
   - 清除上下文
   - 重新开始

---

## 📚 相关文档

- [AGENT_NAMESPACE_GUIDE.md](~/.claude/AGENT_NAMESPACE_GUIDE.md) - Agent 命名空间完整指南
- [CLAUDE_CLI_DIAGNOSIS.md](~/.claude/CLAUDE_CLI_DIAGNOSIS.md) - CLI 诊断报告
- [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) - 项目快速参考
- [diagnose_claude_cli.py](~/.claude/diagnose_claude_cli.py) - 诊断脚本

---

## 💡 最佳实践

### Do's ✅

- ✅ 使用前先 `ListDir` 验证路径
- ✅ 从错误信息中复制正确的 Agent 名称
- ✅ 使用具体的搜索模式而非宽泛的通配符
- ✅ 定期运行诊断脚本
- ✅ 备份配置文件

### Don'ts ❌

- ❌ 不要假设文件存在
- ❌ 不要使用未验证的 Agent 名称
- ❌ 不要使用 `**/*.py` 这样的宽泛模式
- ❌ 不要在 Bash 中使用复杂的交互式命令
- ❌ 不要忽略错误信息中的可用选项列表

---

**记住:** 大多数问题都是因为**假设**而不是**验证**。养成先检查再操作的习惯！
