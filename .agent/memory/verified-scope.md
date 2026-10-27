# 已验证范围（避免重复跑同一验证）

## 2026-10-27
| 验证项 | 命令 | 结果 | 时间戳 |
|--------|------|------|--------|
| 新增模块测试 116 个 | pytest tests/mcp/ tests/reasoning/ tests/security/ tests/reverse_tools/ tests/agent/test_engine_extended_tools.py tests/cli_handlers/test_reason_handler.py -q | 全绿 | 2026-10-27 |
| 契约测试 | pytest tests/contracts/ -q | 39 passed | 2026-10-27 |
| reason CLI 注册 | python -m src reason --help | 正常输出用法 | 2026-10-27 |
| ruff | ruff check src/ tests/ --select F821,F811,E9 | All passed | 2026-10-27 |
| 导入扫描 | python scripts/import_sweep.py | IMPORT-FAIL=0 | 2026-10-27 |
| 全量快检 | pytest tests/ -q -m "not slow" | 3632 passed / 17 存量失败（已定性） | 2026-10-27 |
| 基线对照 | git stash 后复跑失败用例 | 同样失败 → 存量确认 | 2026-10-27 |
