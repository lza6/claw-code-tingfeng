# Known Issues

## 未闭环（工程量大，需独立排期）
| ID | 问题 | 现状 | 影响 |
|:---|:---|:---|:---|
| K-01 | 覆盖率 60% | 46.15%（25,877/56,072） | 回归保护不足 |
| K-02 | 死模块 ≤20 | 200 个生产不可达（41,561 行） | 维护负担与误判风险 |
| K-03 | 测试收集 <120s | ✅ **已达成**：3167 tests / 0 errors / 78.99s | — |
| K-04 | 静默吞异常 | 全库 206 处 `pass/continue` | 故障不可见 |

## 已知限制（已披露）
| ID | 限制 | 原因 |
|:---|:---|:---|
| L-01 | 流式路径不支持原生 function calling | provider 流式 delta 实现不一致；启用时告警回退文本 |
| L-02 | SSRF 存在 DNS rebinding TOCTOU | 校验解析与连接解析各一次；未做请求期 IP 绑定 |
| L-03 | `record_visual_feedback` 只原子写、未覆盖读改写 | 频率低；已记录 |
| L-04 | `PipelineState` 非生产路径 | 生产用 `ModeStateManager`；`expected_attempt` 无生产调用方 |
| L-05 | 无 Web UI / 无浏览器验证 | 项目为 CLI |
| L-06 | `FilePathWatcher`（`src/utils/watch.py`）依赖可选 `pathspec` | 未装 `[watch]` extra 时降级，`FileWatcher` 抛明确 ImportError；核心 CLI 不受影响 |

## 环境阻塞
| ID | 阻塞 | 缺什么 |
|:---|:---|:---|
| B-01 | GitHub Release | 无 `gh` CLI / token |
| B-02 | Docker 构建/部署/热更新 | 无 Docker、无部署目标与凭证 |
| B-03 | 远端 CI 实跑 | 本机无法触发 Actions |
