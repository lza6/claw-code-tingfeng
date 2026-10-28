"""引擎注册表 — 统一发现/探活/选择多个开源 agent 引擎

设计原则（多引擎整合的正确形态）:
- **不是把 6 个引擎的代码合并成一个**（语言/协议/依赖都不同，合了必崩），
  而是**统一到一套驱动接口 + 一份注册表 + 一次探活**，上层按能力/可用性路由。
- 引擎各用各的原生协议，我们只做归一化；领域能力（工具/世界模型）走 **MCP** 反向供给，
  这样任何一个引擎都能"长出"我们的领域工具。

已登记引擎的真实性质（2026-10-28 实测，勿篡改）:
- codex    : Agent CLI，Rust 内核 + TS 启动器（Apache-2.0），`codex exec --json`
- opencode : Agent CLI（Go），`opencode run --format json`
- openclaw : Agent CLI（TS），对 Node 版本要求严格（本机 25.8.1 不满足 → incompatible）
- grok     : 模型代理（把 Claude Code 路由到 Grok），不是引擎 → 归入 provider 层
- pi       : 插件/上下文原语包（spawn/notebook/handoff），不是引擎 → 归入能力层
- hermes   : 参考库中无源码（空目录）→ 不可用
"""

from __future__ import annotations

from typing import Iterable

from .base import CliBackend, CliEngineProfile, EngineProbe

# ---------- 引擎画像 ----------

CODEX = CliEngineProfile(
    name="codex",
    binary="codex",
    version_args=("--version",),
    argv_template=("exec", "--sandbox", "{sandbox}", "--skip-git-repo-check"),
    json_flag_args=("--json",),
    event_text_keys=("item.text", "text"),
    event_command_keys=("item.command", "command"),
    event_usage_keys=("usage",),
    event_session_keys=("thread_id",),
)

OPENCODE = CliEngineProfile(
    name="opencode",
    binary="opencode",
    version_args=("--version",),
    argv_template=("run",),
    json_flag_args=("--format", "json"),
    event_text_keys=("part.text", "text", "message"),
    event_command_keys=("part.command", "command"),
    event_usage_keys=("usage", "part.tokens"),
    event_session_keys=("sessionID", "session_id", "session"),
)

OPENCLAW = CliEngineProfile(
    name="openclaw",
    binary="openclaw",
    version_args=("--version",),
    argv_template=(),
    json_flag_args=(),
    event_text_keys=("text", "message"),
    event_command_keys=("command",),
    event_usage_keys=("usage",),
    event_session_keys=("sessionId", "session_id"),
    runtime_check="node",
)

ENGINES: dict[str, CliEngineProfile] = {
    p.name: p for p in (CODEX, OPENCODE, OPENCLAW)
}

#: 非引擎项（避免把它们当引擎驱动，造成"看起来支持其实跑不通"）
NON_ENGINES: dict[str, str] = {
    "grok": "模型代理：把 Claude Code 的请求路由到 Grok 模型；属 provider 层，不是 agent 引擎",
    "pi": "插件包：提供 spawn/notebook/handoff 上下文原语；属能力层，不是独立引擎",
    "hermes": "参考库中无源码（空目录），无法评估与集成",
}


def get_backend(engine: str, **kwargs):
    """按名称取后端实例（未知引擎抛 KeyError，不静默回退）

    codex 走专用驱动（需要自定义 provider 注册等额外配置），其余走通用 CliBackend。
    """
    profile = ENGINES.get(engine)
    if profile is None:
        known = ", ".join(sorted(ENGINES))
        raise KeyError(f"未知引擎: {engine}（已注册: {known}）")
    if engine == "codex":
        from .codex import CodexBackend

        allowed = {k: v for k, v in kwargs.items()
                   if k in ("model", "provider", "base_url", "sandbox", "workdir",
                            "extra_config", "skip_git_check", "api_key_env", "wire_api")}
        return CodexBackend(**allowed)
    return CliBackend(profile, **kwargs)


def probe_engine(engine: str, **kwargs) -> EngineProbe:
    profile = ENGINES.get(engine)
    if profile is None:
        return EngineProbe(name=engine, status="not_installed", detail="未注册的引擎")
    return CliBackend(profile, **kwargs).probe()


def probe_all(engines: Iterable[str] | None = None) -> list[EngineProbe]:
    names = list(engines) if engines else list(ENGINES)
    return [probe_engine(n) for n in names if n in ENGINES]


def ready_engines() -> list[str]:
    """当前真正可用的引擎名列表（探活结果为准）"""
    return [p.name for p in probe_all() if p.usable]


def describe() -> dict[str, dict[str, object]]:
    """引擎 + 非引擎项的完整清单（供 CLI/文档展示）"""
    out: dict[str, dict[str, object]] = {}
    for probe in probe_all():
        out[probe.name] = {
            "kind": "engine",
            "status": probe.status,
            "version": probe.version,
            "detail": probe.detail,
            "binary": probe.binary,
        }
    for name, why in NON_ENGINES.items():
        out[name] = {"kind": "non-engine", "status": "n/a", "detail": why}
    return out
