# Agent Rules

## 必须先读
1. `.agent/memory/*.md`（判断是否过时）
2. `.agent/skills/*.md`（按任务匹配）
3. `AGENTS.md`、`workflow_status.md`、`docs/MAINTENANCE.md`
4. `计划书/` 顶部状态表

## 执行契约
- 先思考后编码：目标、范围、假设、验证方式写清楚。
- 读实际代码，再信文档；文档断言必须用命令/代码验证。
- 优先复用项目已有实现；禁止重复造轮子；禁止大幅重构。
- 改动必须同步代码、配置、测试、文档。
- 任何“完成/通过/已修复”必须附实际命令、退出码、输出尾部。
- 未运行的验证写 `not_run` 并说明原因。
- 禁止用删除测试、跳过测试、放宽断言、mock 真实逻辑来变绿。
- 禁止把占位/假数据/伪连接包装成完成。
- 高风险/不可逆操作先给方案、回滚、验证计划；未授权不执行。

## 验证铁则
```bash
ruff check src/ tests/ --select F821,F811,E9
python scripts/import_sweep.py
python scripts/reachability.py
pytest tests/contracts -q
pytest tests/ -q
python scripts/e2e_smoke.py
```
退出码 0 且输出符合预期才算通过。

## 审查
- 独立审查、有罪推定；阻断项清零才可 Done。
- 最多 3 轮；未 Approve 记录阻塞。

## 回滚
- 每批次一个提交；回滚 `git revert <sha>`。
- 状态/数据变更必须可逆；删除前先归档并生成 manifest。

## 禁止
- force push、amend 已推送历史。
- 未备份的不可逆操作。
- 把“代码存在”当闭环。
- 把“文档写了完成”当闭环。
