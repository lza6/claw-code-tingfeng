# release-checklist

## 适用场景
发布新版本、创建 tag、推送 main。

## 前置检查（全部必须真实执行）
```bash
ruff check src/ tests/ --select F821,F811,E9
python scripts/import_sweep.py          # IMPORT-FAIL = 0
python scripts/reachability.py          # 可达数不得下降
pytest tests/contracts -q
pytest tests/ -q                        # 0 failed
python scripts/e2e_smoke.py             # 退出码 0
python scripts/e2e_production.py        # 全通过（若存在）
python scripts/stress_test.py --n 200   # 核心并发
```

## 版本一致性
```bash
python -m src --version
python -c "import importlib.metadata as m; print(m.version('clawd-code'))"
grep -m1 '^version' pyproject.toml
grep -m1 '当前版本' README.md
```
四处必须一致。`src.__version__` 以 `pyproject.toml` 为优先真相源。

## 发布步骤
1. 更新 CHANGELOG（写“为什么”和验证结果）。
2. 更新 `workflow_status.md`、`test_ledger.md`。
3. `git add` 明确文件；检查 diff 无密钥/临时产物。
4. `git commit`（约定式提交）。
5. `git push origin main`（禁止 force）。
6. `git tag -a vX.Y.Z` + `git push origin vX.Y.Z`。
7. 记录 SHA 与远端核对结果。

## 阻塞处理
- 无 `gh` CLI → GitHub Release 标记 BLOCKED，不假装创建。
- 无 Docker/部署目标 → 不声称“已上线”。

## 回滚
`git revert <sha>`；tag 可保留作为失败标记。
