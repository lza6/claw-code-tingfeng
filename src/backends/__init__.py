"""后端适配层 — 把成熟 agent 内核接进 clawd（不重复造轮子）

当前实现:
- `codex`：OpenAI Codex CLI（Rust 内核 + TS 启动器，Apache-2.0）
  通过 `codex exec --json` 的 JSONL 事件流驱动，保留其原生沙箱/审批/会话续跑能力，
  我们只负责：参数与配置映射、事件归一化、超时与进程回收、用量统计。

设计约束:
- **不碰内核**：我们不 fork Codex 的循环，只做协议适配，因此升级 Codex 版本无需改适配层
  （仅当 JSONL 事件 schema 变化时需要调整 `parse_events`）。
- **进程可控**：所有子进程都带超时与 kill 兜底，避免长程任务把宿主拖死（内存/句柄泄漏防线）。
- **可测试**：`binary` 允许传 argv 前缀，测试用假进程注入 JSONL，不依赖真实安装。
"""

from .base import BackendResult, BackendUnavailable, CliBackend, EngineProbe
from .codex import CodexBackend, CodexRunResult, parse_events
from .native import NativeBackend

__all__ = [
    "BackendResult",
    "BackendUnavailable",
    "CliBackend",
    "CodexBackend",
    "CodexRunResult",
    "EngineProbe",
    "NativeBackend",
    "parse_events",
]
