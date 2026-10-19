# add-new-api

## 适用场景
新增对外 Python API、CLI 子命令、MCP 工具或 WebSocket 消息类型。

## 前置读取
1. `AGENTS.md`、`docs/MAINTENANCE.md`、`skills/clawd-change-workflow/SKILL.md`
2. `tests/contracts/` 是否已锁定相关接口
3. `scripts/reachability.py` 当前生产可达数

## 步骤
1. 先写失败测试（契约测试优先）。
2. 实现最小 API；默认值/错误码与现有风格一致。
3. 若新增模块，必须有**显式 import**（不要 `importlib.import_module("字符串")`，否则可达性图看不见）。
4. 更新 `__init__.py` 导出与 `docs/MAINTENANCE.md`。
5. 验证：
   ```bash
   pytest tests/contracts -q
   python scripts/import_sweep.py          # IMPORT-FAIL 必须 0
   python scripts/reachability.py          # 可达数不得下降
   ruff check src/ tests/ --select F821,F811,E9
   ```

## 验收标准
- 契约测试覆盖 success / 参数错误 / 权限错误。
- 生产可达数不下降；导入扫描 0 缺陷。
- 文档有可复制的调用示例。

## 证据要求
`evidence/<task>.json` 记录命令、退出码、输出尾部。

## 回滚方式
新增 API 独立成文件；回滚 = 还原提交 + 删除对应测试。

## 常见坑
- 参数被接受但函数体未使用（伪契约）。
- 同名类在两处定义导致 `isinstance` 失配。
- 只在测试中可达，生产入口没有接线。
