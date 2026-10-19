# project-audit-sop

## 适用场景
对项目做全量审计、接手陌生模块、或发布前终检。

## 0. 读
1. `AGENTS.md` / `CLAUDE.md`
2. `workflow_status.md`（上一轮做了什么、验证到哪）
3. `skills/clawd-change-workflow/SKILL.md`
4. `计划书/` 最新文档（注意顶部状态表优先于正文旧数字）
5. `docs/MAINTENANCE.md`、`docs/adr/README.md`

## 1. 建事实基线（不要信文档数字）
```bash
python scripts/reachability.py
python scripts/import_sweep.py
ruff check src/ tests/ --select F821,F811,E9
pytest tests/ -q
pytest tests/contracts -q
```

## 2. 文档保鲜
对每条具体断言（“X 未实现”“覆盖率 N%”“文件在 Y”）用代码/命令验证。
判定：一致 → 按文档；过时 → 先更新；API 不存在 → 看有无活调用方。

## 3. 分层审计
- 入口：CLI 命令是否可执行（不只是 `--help` 可见）。
- 生产可达：功能是否从入口可达。
- 默认关闭能力：是否有显式提示。
- 静默失败：`except: pass` 数量与位置。
- 测试：是否测生产函数、是否复制逻辑。

## 4. 输出
问题按 P0/P1/P2 分级，每条带 file:line、证据、复现、修复方向。
不做“风格偏好当缺陷”。

## 5. 收尾
更新 `workflow_status.md`、`test_ledger.md`、`evidence/`。
