# Clawd Code 清理清单 (Cleanup Manifest)

本手册旨在指导如何系统地移除项目中的冗余代码、旧版残留及架构冲突点。

## 1. 冗余模块清理 (Redundant Modules)

以下文件已被新架构取代，建议在验证完成后直接删除：

- [ ] `src/utils/deprecated_args.py`: 0.4x 版本的参数残留，现已统一由 `core/args_parser.py` 处理。
- [ ] `src/core/chat_summary.py`: 逻辑与 `src/core/chat_summarizer.py` 重复。
- [ ] `src/tools_runtime/diff_utils.py`: 功能与 `src/utils/diff_utils.py` 高度重合，应统一迁往 `src/core/patch/`。
- [ ] `src/cli_handlers/`: 大部分逻辑已被 `src/cli/tui` 或 `src/cli/repl_handlers.py` 覆盖。

## 2. 旧版产物清理 (Legacy Artifacts)

- [ ] `*.bak`, `*.old`, `*.tmp`: 移除所有手动备份文件。
- [ ] `src/__pycache__/`: 强制清理并完善 `.gitignore`。
- [ ] `logs/*.log`: 清理历史调试日志，仅保留最近 24 小时的记录。
- [ ] `tmp/*`: 清理所有临时的补丁文件和扫描缓存。

## 3. 代码级“屎山”修复 (Code Smells)

- [ ] **Hardcoded Paths**: 查找并移除所有硬编码的绝对路径，统一使用 `src/core/project_context.py` 中的动态路径。
- [ ] **Global State**: 减少 `src/agent/engine.py` 中的全局变量，将其封装进 `AgentSession`。
- [ ] **Duplicate Constants**: 将分散在各个工具类中的超时时间、最大重试次数统一存入 `src/core/config/constants.py`。
- [ ] **Commented-out Code**: 移除所有被注释掉的大段旧逻辑代码块。

## 4. 自动化清理建议

在 `scripts/` 下创建一个 `clean_project.py` 脚本，执行以下逻辑：
```python
def cleanup():
    # 移除字节码
    shutil.rmtree('**/__pycache__', ignore_errors=True)
    # 移除旧备份
    for f in glob.glob('**/*.bak', recursive=True): os.remove(f)
    # 移除临时会话数据
    shutil.rmtree('.clawd/tmp/*', ignore_errors=True)
```
