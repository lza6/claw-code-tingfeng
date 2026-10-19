# high-concurrency-checklist

## 适用场景
改线程池、锁、审批门禁、熔断器、状态持久化、后台任务。

## 必测
- 并发写同一状态文件：最终 JSON 合法且**不丢更新**。
- 锁：互斥、可重入、超时、陈旧锁回收、owner 校验。
- 线程池：不耗尽、超时后不泄漏、结果不错配。
- 审批门禁：并发下拒绝/放行计数正确。
- 熔断器：计数不丢、状态跃迁正确。

## 命令
```bash
python scripts/stress_test.py --n 200
pytest tests/workflow/test_state_persistence_semantics.py -q
```

## 判据
- 200 并发全部成功、结果无错配、无死锁。
- 读改写计数精确（如 4 线程 ×25 = 100）。
- 连续复跑 3 次稳定。

## 常见坑
- 锁只包写不包读改写。
- Windows `os.replace` 偶发 PermissionError（杀软占用）需重试。
- 可重入锁是线程级：async 临界区 `await` 后同线程协程会被误判。
- stale 回收误删活锁（用 owner token + 原子 rename）。
