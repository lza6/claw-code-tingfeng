# 一次性脚本 / 历史产物（不要当生产代码用）

这些文件是**当时为了排查某一个问题**写下的一次性脚本与总结，现在只剩历史价值：

| 文件 | 当时干什么 |
|---|---|
| `analyze_coverage.py` / `analyze_integration.py` | 统计覆盖率、给模块间集成关系出建议 |
| `check_tools_structure.py` | 检查 `src/tools_runtime` 目录结构是否规范 |
| `inject_errors.py` | 往代码里注入异常，验证自愈链路 |
| `integrate_command_registry.py` | 一次性把命令注册到 registry |
| `cleanup.bat` / `run_ai_tests.bat` / `run_ai_tests.sh` | 早期本地跑测试的批处理（现用 `py -3.10 -m pytest`） |
| `FINAL_FIX_SUMMARY.txt` / `todos.txt` | 历史待办与修复总结（已被 `workflow_status.md` / `CHANGELOG.md` 取代） |

**为什么搬到 `scripts/oneoff/`**：它们原先散落在仓库根目录，让人分不清哪些是入口、哪些是一次性产物
（用户明确反馈"根目录越来越臃肿"）。搬到子目录 + 这张表，既能一眼看出性质，也不用删除历史。
