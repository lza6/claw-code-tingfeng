# Known Issues

## 未闭环（工程量大，需独立排期）
| ID | 问题 | 现状 | 影响 |
|:---|:---|:---|:---|
| K-01 | 覆盖率 60% | **47.44%（26,861/56,624）**，2026-10-23 重取；`fail_under=47` 已真实生效 | 回归保护不足 |
| K-02 | 死模块 ≤20 | 134 个完全不可达（24,667 行）；三问判定 NO_REFS 112 / DOC_ONLY 6 / HAS_REFS 16。**删除需产品决策**（ADR-0001） | 维护负担与误判风险 |
| K-03 | 测试收集 <120s | ✅ **已达成**：3261 tests / 0 errors / 4.6s（热缓存） | — |
| K-04 | 静默吞异常 | **172 处（AST 口径）**；基线文件 `.clawd/baseline-silent.json`，CI 门禁 `--fail-over 172` | 故障不可见 |

## 已知限制（已披露）
| ID | 限制 | 原因 |
|:---|:---|:---|
| L-01 | 流式路径不支持原生 function calling | provider 流式 delta 实现不一致；启用时告警回退文本 |
| L-02 | SSRF 存在 DNS rebinding TOCTOU | 校验解析与连接解析各一次；未做请求期 IP 绑定 |
| L-03 | `record_visual_feedback` 只原子写、未覆盖读改写 | 频率低；已记录 |
| L-04 | `PipelineState` 非生产路径 | 生产用 `ModeStateManager`；`expected_attempt` 无生产调用方 |
| L-05 | 无 Web UI / 无浏览器验证 | 项目为 CLI |
| L-06 | `FilePathWatcher`（`src/utils/watch.py`）依赖可选 `pathspec` | 未装 `[watch]` extra 时降级，`FileWatcher` 抛明确 ImportError；核心 CLI 不受影响 |
| L-07 | `file_lock` 的重入状态是**线程级** | async 临界区若在持锁期间 `await`，同线程两个协程会被误判为可重入；当前调用方均为同步且临界区无 `await` |

## 环境阻塞
| ID | 阻塞 | 缺什么 |
|:---|:---|:---|
| B-01 | GitHub Release | 无 `gh` CLI / token |
| B-02 | Docker 构建/部署/热更新 | 无 Docker、无部署目标与凭证 |
| B-03 | 远端 CI 实跑 | 本机无法触发 Actions |

## 2026-10-23 新发现并已修复（保留记录，避免复现）

| ID | 问题 | 根因 | 修复 |
|:---|:---|:---|:---|
| F-01 | `IMPORT-FAIL = 0` 这条红线可被一个 `sys.exit(1)` 污染 | `import_sweep.classify()` 把 `SystemExit` 兜底判为代码缺陷 | 新增 `IMPORT-EXIT` 分类 + `--strict-exit` 门禁 |
| F-02 | 覆盖率阈值 `fail_under = 60` **从未生效**（v0.53.0 起） | 写在 `[tool.coverage.run]`，coverage 当作未知项忽略 | 移到 `[tool.coverage.report]`，设 47，CI 不再传参 |
| F-03 | `python -m src` 的入口 `src.__main__` 被算作"完全不可达" | `reachability` 的种子列表漏了它；`deadcode_triage` 又自己复制了一份种子 | 种子收敛为 `PROD_SEED_MODULES` + `compute_reachability()`；可达 442→443 |
| F-04 | `test_acquire_release_thread_safe` 靠运气变绿 | 断言"10 线程并发 acquire 同一互斥租约都应成功" | 改为 Exactly-One 强契约断言，连续 5 次绿 |
| F-05 | 仓库内陈旧 `clawd_code.egg-info/`（0.60.6）污染所有 `importlib.metadata` 查询 | 未跟踪的构建残留，且项目根在 `sys.path` 首位 | 删除残留（可再生成）；版本一致性测试随之转绿 |
| F-06 | 4 个生产依赖（litellm/mcp/psutil/fastapi）从未声明 | 只写进 `requirements.txt` 或完全遗漏 | 补进 `pyproject.toml`；`pip install -e .` 后 E2E 可用 |
| F-07 | `src/cli/surface_viewer.py` 的 `except ImportError: sys.exit(1)` 掩盖了整块不可用 | 函数注解在模块级求值，`SurfaceManager` 来自可能失败的 try | 加 `from __future__ import annotations`，退出推迟到 `main()` |
| F-08 | GitPython `get_value(key, default)` 在 section 不存在时抛 `NoSectionError` | 空仓库无 `[user]` section | 显式兜住异常（`src/core/git_integration.py`） |

## 未闭环（2026-10-23 复核）

| ID | 项 | 现状 |
|:---|:---|:---|
| K-05 | 快速层（`-m "not slow"`）< 180s | **237s**；slow 层 9 例已剥离 410s，剩余耗时分散 |
| K-06 | `src/core/git_integration.py` 使用了 `except Exception` 兜 GitPython 配置读取 | 建议收窄为 `NoSectionError`/`NoOptionError`（P2） |
| K-07 | 远端 CI 未实跑 | 本机无 `gh`；YAML 与本地等价命令已验证 |
