"""多 provider 配置存储（本地 SQLite）

用户要"能配多个 API 提供商、能切换、重启后还在"，所以：
- 存 SQLite（`<workdir>/.clawd/clawd.db` 的 `providers` 表），不是内存/环境变量临时拼；
- **密钥两种放法**：`key_env`（推荐，存环境变量名）+ `key_inline`（明文兜底，UI 里只显示掩码）；
  取值时优先 `key_env`，其次 `key_inline`；
- 对外只返回**掩码**，绝不把明文吐给前端；
- `is_default` 全表唯一（保存时在事务里清掉其它行的默认位）。
"""
from __future__ import annotations

import logging
import os
import re
import time

from pathlib import Path
from typing import Any

from . import local_db

logger = logging.getLogger(__name__)

VALID_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
KINDS = ("openai", "anthropic", "deepseek", "google", "groq", "mistral", "openrouter", "together", "custom")


def _mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:5]}…{secret[-4:]}"


def _row_to_public(row: dict[str, Any]) -> dict[str, Any]:
    """把 DB 行转成可发给前端的形状（**密钥只给掩码**）"""
    env_name = row.get("key_env") or ""
    inline = row.get("key_inline") or ""
    env_value = os.environ.get(env_name) if env_name else ""
    resolved = env_value or inline
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "kind": row.get("kind"),
        "base_url": row.get("base_url"),
        "model": row.get("model"),
        "key_env": env_name,
        "key_masked": _mask(resolved),
        "key_source": "env" if env_value else ("inline" if inline else "missing"),
        "has_key": bool(resolved),
        "enabled": bool(row.get("enabled")),
        "is_default": bool(row.get("is_default")),
        "updated_at": row.get("updated_at"),
    }


def list_providers(workdir: Path | str | None = None) -> list[dict[str, Any]]:
    conn = local_db.connect(workdir)
    try:
        rows = local_db.fetch_all(
            conn, "SELECT * FROM providers ORDER BY is_default DESC, updated_at DESC"
        )
        return [_row_to_public(r) for r in rows]
    finally:
        conn.close()


def get_provider(provider_id: str, workdir: Path | str | None = None) -> dict[str, Any] | None:
    conn = local_db.connect(workdir)
    try:
        row = local_db.fetch_one(conn, "SELECT * FROM providers WHERE id = ?", (provider_id,))
        return _row_to_public(row) if row else None
    finally:
        conn.close()


def resolve_api_key(provider_id: str, workdir: Path | str | None = None) -> str:
    """取真实密钥（env 优先），供 Host 建 provider 时用；**不对外暴露**"""
    conn = local_db.connect(workdir)
    try:
        row = local_db.fetch_one(conn, "SELECT key_env, key_inline FROM providers WHERE id = ?", (provider_id,))
    finally:
        conn.close()
    if not row:
        return ""
    env_name = (row.get("key_env") or "").strip()
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    return (row.get("key_inline") or "").strip()


def save_provider(payload: dict[str, Any], workdir: Path | str | None = None) -> dict[str, Any]:
    """新增/更新 provider

    Raises:
        ValueError: id 非法 / 缺 name / kind 不认识
    """
    provider_id = str(payload.get("id") or "").strip()
    if not VALID_ID.match(provider_id):
        raise ValueError("provider id 只能包含字母数字和 . _ -（1~64 位）")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("provider 需要 name")
    kind = str(payload.get("kind") or "openai").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"不支持的 kind: {kind}（可选: {', '.join(KINDS)}）")

    base_url = str(payload.get("base_url") or "").strip()
    model = str(payload.get("model") or "").strip()
    key_env = str(payload.get("key_env") or "").strip()
    key_inline = str(payload.get("key") or "").strip()  # 前端传 key 字段；空表示不改
    make_default = bool(payload.get("is_default"))
    enabled = payload.get("enabled", True)
    enabled = 1 if enabled in (True, 1, "1", "true", "True") else 0

    ts = time.time()
    conn = local_db.connect(workdir)
    try:
        existing = local_db.fetch_one(conn, "SELECT * FROM providers WHERE id = ?", (provider_id,))
        if existing:
            # key 留空 = 保留原值（避免"编辑别的字段把密钥清空"）
            new_inline = key_inline if key_inline else (existing.get("key_inline") or "")
            conn.execute(
                "UPDATE providers SET name=?, kind=?, base_url=?, model=?, key_env=?, key_inline=?,"
                " enabled=?, updated_at=? WHERE id=?",
                (name, kind, base_url, model, key_env, new_inline, enabled, ts, provider_id),
            )
        else:
            conn.execute(
                "INSERT INTO providers (id, name, kind, base_url, model, key_env, key_inline,"
                " enabled, is_default, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,0,?,?)",
                (provider_id, name, kind, base_url, model, key_env, key_inline, enabled, ts, ts),
            )
        if make_default:
            conn.execute("UPDATE providers SET is_default = 0")
            conn.execute("UPDATE providers SET is_default = 1 WHERE id = ?", (provider_id,))
        # 首次保存的 provider 自动成为默认（否则用户加了却"没生效"）
        has_default = local_db.fetch_one(conn, "SELECT id FROM providers WHERE is_default = 1")
        if not has_default:
            conn.execute("UPDATE providers SET is_default = 1 WHERE id = ?", (provider_id,))
        conn.commit()
    finally:
        conn.close()
    return get_provider(provider_id, workdir) or {}


def delete_provider(provider_id: str, workdir: Path | str | None = None) -> bool:
    conn = local_db.connect(workdir)
    try:
        row = local_db.fetch_one(conn, "SELECT is_default FROM providers WHERE id = ?", (provider_id,))
        if not row:
            return False
        conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
        if row.get("is_default"):
            # 删掉默认项后，把最近更新的一条提升为默认（不留"无默认"状态）
            nxt = local_db.fetch_one(conn, "SELECT id FROM providers ORDER BY updated_at DESC LIMIT 1")
            if nxt:
                conn.execute("UPDATE providers SET is_default = 1 WHERE id = ?", (nxt["id"],))
        conn.commit()
        return True
    finally:
        conn.close()


def set_default(provider_id: str, workdir: Path | str | None = None) -> bool:
    conn = local_db.connect(workdir)
    try:
        row = local_db.fetch_one(conn, "SELECT id FROM providers WHERE id = ?", (provider_id,))
        if not row:
            return False
        conn.execute("UPDATE providers SET is_default = 0")
        conn.execute("UPDATE providers SET is_default = 1, updated_at = ? WHERE id = ?", (time.time(), provider_id))
        conn.commit()
        return True
    finally:
        conn.close()


def active_provider(workdir: Path | str | None = None) -> dict[str, Any] | None:
    """当前默认 provider（含是否已配密钥）"""
    for item in list_providers(workdir):
        if item["is_default"] and item["enabled"]:
            return item
    return None


def build_llm_config(provider_id: str, workdir: Path | str | None = None):
    """把某个 provider 转成 `LLMConfig`（供 Host 建引擎时使用）

    这是"设为默认真的生效"的关键：只存配置不改运行时不等于功能闭环。

    Raises:
        ValueError: provider 不存在或没配密钥
    """
    from ..llm.config import LLMConfig, LLMProviderType

    item = get_provider(provider_id, workdir)
    if not item:
        raise ValueError(f"provider 不存在: {provider_id}")
    key = resolve_api_key(provider_id, workdir)
    if not key:
        raise ValueError(
            f"provider {provider_id} 没有可用密钥（设置 key_env 指向环境变量，或填 key）"
        )
    try:
        ptype = LLMProviderType(str(item.get("kind") or "openai"))
    except ValueError:
        ptype = LLMProviderType.CUSTOM
    return LLMConfig(
        provider=ptype,
        api_key=key,
        base_url=str(item.get("base_url") or ""),
        model=str(item.get("model") or ""),
    )


def describe_active(workdir: Path | str | None = None) -> dict[str, Any]:
    """当前生效 provider 的可展示摘要（不含密钥）"""
    active = active_provider(workdir)
    if not active:
        return {"configured": False}
    return {
        "configured": True,
        "id": active["id"],
        "name": active["name"],
        "kind": active["kind"],
        "model": active["model"],
        "base_url": active["base_url"],
        "has_key": active["has_key"],
        "key_source": active["key_source"],
    }


__all__ = [
    "KINDS",
    "VALID_ID",
    "active_provider",
    "build_llm_config",
    "describe_active",
    "delete_provider",
    "get_provider",
    "list_providers",
    "resolve_api_key",
    "save_provider",
    "set_default",
]
