"""用量记账（本地 SQLite）—— 每一轮 agent 运行都落一行

为什么需要：用户想知道"这个月花了多少钱、哪个模型最贵、缓存命中率多少"，
这些必须**跑完就记**，不能靠日志事后拼。记录点在 `AgentEngine._persist_session`
（CLI 与桌面端共用同一条路径），字段口径与 CC Switch 那类用量面板对齐：
时间 / provider / model / 输入 token / 输出 token / 缓存读 token / 成本 / 耗时 / 步数 / 状态。
"""
from __future__ import annotations

import logging

from pathlib import Path
from typing import Any

from . import local_db

logger = logging.getLogger(__name__)

RANGE_SECONDS = {
    "today": 24 * 3600,
    "day": 24 * 3600,
    "week": 7 * 24 * 3600,
    "month": 30 * 24 * 3600,
    "all": None,
}


def record(
    *,
    provider: str = "",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_read_tokens: int = 0,
    cost: float = 0.0,
    duration_ms: int = 0,
    steps: int = 0,
    status: str = "completed",
    session_id: str = "",
    goal_chars: int = 0,
    workdir: Path | str | None = None,
) -> bool:
    """写一条用量记录（失败只告警，绝不打断 agent 主流程）"""
    try:
        conn = local_db.connect(workdir)
        try:
            conn.execute(
                "INSERT INTO usage (ts, session_id, provider, model, prompt_tokens, completion_tokens,"
                " cache_read_tokens, cost, duration_ms, steps, status, goal_chars)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    local_db.now(), session_id, provider, model,
                    int(prompt_tokens or 0), int(completion_tokens or 0), int(cache_read_tokens or 0),
                    float(cost or 0.0), int(duration_ms or 0), int(steps or 0), status, int(goal_chars or 0),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as e:  # noqa: BLE001 — 记账失败不能影响任务
        logger.warning(f"用量记录失败（已忽略）: {e}")
        return False


def summary(range_key: str = "today", workdir: Path | str | None = None) -> dict[str, Any]:
    """按时间范围汇总（KPI + 按小时分布 + 按模型分布）"""
    window = RANGE_SECONDS.get(range_key, 24 * 3600)
    since = 0.0 if window is None else local_db.now() - window
    conn = local_db.connect(workdir)
    try:
        totals = local_db.fetch_one(
            conn,
            "SELECT COUNT(*) AS requests,"
            " COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,"
            " COALESCE(SUM(completion_tokens),0) AS completion_tokens,"
            " COALESCE(SUM(cache_read_tokens),0) AS cache_read_tokens,"
            " COALESCE(SUM(cost),0) AS cost,"
            " COALESCE(AVG(duration_ms),0) AS avg_duration_ms"
            " FROM usage WHERE ts >= ?",
            (since,),
        ) or {}

        # 缓存命中率 = 缓存读 / (缓存读 + 新增输入)（与 CC Switch 口径一致）
        cache_read = int(totals.get("cache_read_tokens") or 0)
        prompt = int(totals.get("prompt_tokens") or 0)
        denom = cache_read + prompt
        totals["cache_hit_rate"] = round(cache_read / denom, 4) if denom else 0.0
        totals["total_tokens"] = prompt + int(totals.get("completion_tokens") or 0)
        totals["cost"] = round(float(totals.get("cost") or 0.0), 6)
        totals["avg_duration_ms"] = int(totals.get("avg_duration_ms") or 0)

        hourly = local_db.fetch_all(
            conn,
            "SELECT CAST(ts/3600 AS INTEGER)*3600 AS bucket,"
            " COUNT(*) AS requests,"
            " COALESCE(SUM(prompt_tokens+completion_tokens),0) AS tokens,"
            " COALESCE(SUM(cost),0) AS cost"
            " FROM usage WHERE ts >= ? GROUP BY bucket ORDER BY bucket",
            (since,),
        )
        by_model = local_db.fetch_all(
            conn,
            "SELECT model, provider, COUNT(*) AS requests,"
            " COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,"
            " COALESCE(SUM(completion_tokens),0) AS completion_tokens,"
            " COALESCE(SUM(cache_read_tokens),0) AS cache_read_tokens,"
            " COALESCE(SUM(cost),0) AS cost"
            " FROM usage WHERE ts >= ? GROUP BY provider, model ORDER BY cost DESC",
            (since,),
        )
        return {"range": range_key, "since": since, "totals": totals,
                "hourly": hourly, "by_model": by_model}
    finally:
        conn.close()


def recent(limit: int = 50, workdir: Path | str | None = None) -> list[dict[str, Any]]:
    """最近的请求日志（新→旧）"""
    conn = local_db.connect(workdir)
    try:
        return local_db.fetch_all(
            conn,
            "SELECT * FROM usage ORDER BY ts DESC LIMIT ?",
            (max(1, min(int(limit or 50), 500)),),
        )
    finally:
        conn.close()


__all__ = ["RANGE_SECONDS", "recent", "record", "summary"]
