"""多 provider 配置存储 —— **JSON 文件**（用户可读、可手改、升级不丢）

为什么从 SQLite 改成 JSON（用户明确要求 + 真实事故）：
- 用户反馈"重启之后数据库会丢"，根因是数据目录跟着**安装目录**走，升级即被覆盖；
  数据目录已改到 `CLAWD_DATA_DIR`（桌面端=userData），见 `src/core/data_dir.py`；
- provider 配置是**低频小数据**，JSON 更合适：能直接看、能手动改、能进版本库（脱敏后）。
  用量统计（高频、会持续增长、要 GROUP BY）仍留在 SQLite。

文件格式（`<数据目录>/providers.json`）：

    {
      "version": 1,
      "active": "deepseek-main",
      "providers": {
        "deepseek-main": {
          "name": "DeepSeek 官方", "kind": "deepseek", "base_url": "https://api.deepseek.com/v1",
          "model": "deepseek-chat", "key_env": "DEEPSEEK_API_KEY", "key": "", "enabled": true,
          "updated_at": 1730000000.0
        }
      }
    }

密钥仍是两种放法：`key_env`（环境变量名，推荐）或 `key`（明文兜底）。
对外接口只返回掩码；写入用原子替换（临时文件 + rename），避免半截文件。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from pathlib import Path
from typing import Any

from . import data_dir as data_dir_mod

logger = logging.getLogger(__name__)

VALID_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
KINDS = ("openai", "anthropic", "deepseek", "google", "groq", "mistral", "openrouter", "together", "custom")
FILE_NAME = "providers.json"


def _path() -> Path:
    return data_dir_mod.data_path(FILE_NAME)


def _mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:5]}…{secret[-4:]}"


def _empty() -> dict[str, Any]:
    return {"version": 1, "active": "", "providers": {}}


def _load() -> dict[str, Any]:
    path = _path()
    if not path.is_file():
        return _migrate_from_sqlite(_empty())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"providers.json 读取失败（按空库处理）: {e}")
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("providers", {})
    data.setdefault("active", "")
    return data


def _save(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # 原子替换，避免写一半被读到


def _migrate_from_sqlite(data: dict[str, Any]) -> dict[str, Any]:
    """一次性迁移：老版本把 providers 存在 SQLite 里，读出来写成 JSON 后不再回写 SQLite"""
    try:
        from . import local_db

        conn = local_db.connect()
        try:
            rows = local_db.fetch_all(conn, "SELECT * FROM providers")
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — 没有老库/表不存在都属正常
        return data
    if not rows:
        return data
    for row in rows:
        provider_id = str(row.get("id") or "").strip()
        if not provider_id:
            continue
        data["providers"][provider_id] = {
            "name": row.get("name") or provider_id,
            "kind": row.get("kind") or "openai",
            "base_url": row.get("base_url") or "",
            "model": row.get("model") or "",
            "key_env": row.get("key_env") or "",
            "key": row.get("key_inline") or "",
            "enabled": bool(row.get("enabled", 1)),
            "updated_at": float(row.get("updated_at") or 0.0),
        }
        if row.get("is_default"):
            data["active"] = provider_id
    try:
        _save(data)
        logger.info(f"已把 {len(rows)} 个 provider 从 SQLite 迁移到 providers.json")
    except OSError as e:
        logger.warning(f"迁移写入失败: {e}")
    return data


def _public(provider_id: str, raw: dict[str, Any], active: str) -> dict[str, Any]:
    env_name = str(raw.get("key_env") or "")
    inline = str(raw.get("key") or "")
    env_value = os.environ.get(env_name) if env_name else ""
    resolved = env_value or inline
    return {
        "id": provider_id,
        "name": raw.get("name") or provider_id,
        "kind": raw.get("kind") or "openai",
        "base_url": raw.get("base_url") or "",
        "model": raw.get("model") or "",
        "key_env": env_name,
        "key_masked": _mask(resolved),
        "key_source": "env" if env_value else ("inline" if inline else "missing"),
        "has_key": bool(resolved),
        "enabled": bool(raw.get("enabled", True)),
        "is_default": provider_id == active,
        "updated_at": float(raw.get("updated_at") or 0.0),
    }


def list_providers(workdir: Path | str | None = None) -> list[dict[str, Any]]:
    del workdir  # 数据目录由 CLAWD_DATA_DIR 决定，保留参数是为兼容旧调用
    data = _load()
    active = str(data.get("active") or "")
    items = [_public(pid, raw, active) for pid, raw in (data.get("providers") or {}).items()]
    items.sort(key=lambda item: (not item["is_default"], -float(item["updated_at"] or 0)))
    return items


def get_provider(provider_id: str, workdir: Path | str | None = None) -> dict[str, Any] | None:
    del workdir
    data = _load()
    raw = (data.get("providers") or {}).get(provider_id)
    return _public(provider_id, raw, str(data.get("active") or "")) if raw else None


def resolve_api_key(provider_id: str, workdir: Path | str | None = None) -> str:
    del workdir
    raw = (_load().get("providers") or {}).get(provider_id) or {}
    env_name = str(raw.get("key_env") or "").strip()
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    return str(raw.get("key") or "").strip()


def save_provider(payload: dict[str, Any], workdir: Path | str | None = None) -> dict[str, Any]:
    del workdir
    provider_id = str(payload.get("id") or "").strip()
    if not VALID_ID.match(provider_id):
        raise ValueError("provider id 只能包含字母数字和 . _ -（1~64 位）")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("provider 需要 name")
    kind = str(payload.get("kind") or "openai").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"不支持的 kind: {kind}（可选: {', '.join(KINDS)}）")

    data = _load()
    providers = data.setdefault("providers", {})
    existing = providers.get(provider_id) or {}
    key_input = str(payload.get("key") or "").strip()
    providers[provider_id] = {
        "name": name,
        "kind": kind,
        "base_url": str(payload.get("base_url") or "").strip(),
        "model": str(payload.get("model") or "").strip(),
        "key_env": str(payload.get("key_env") or "").strip(),
        # key 留空 = 保留原值（避免"编辑别的字段把密钥清空"）
        "key": key_input if key_input else str(existing.get("key") or ""),
        "enabled": payload.get("enabled", True) in (True, 1, "1", "true", "True"),
        "updated_at": time.time(),
    }
    if payload.get("is_default") or not data.get("active"):
        data["active"] = provider_id
    _save(data)
    return get_provider(provider_id) or {}


def delete_provider(provider_id: str, workdir: Path | str | None = None) -> bool:
    del workdir
    data = _load()
    providers = data.get("providers") or {}
    if provider_id not in providers:
        return False
    providers.pop(provider_id, None)
    if data.get("active") == provider_id:
        # 删掉默认项后把最近更新的一条顶上，不留"无默认"状态
        remaining = sorted(providers.items(), key=lambda kv: -float(kv[1].get("updated_at") or 0))
        data["active"] = remaining[0][0] if remaining else ""
    _save(data)
    return True


def set_default(provider_id: str, workdir: Path | str | None = None) -> bool:
    del workdir
    data = _load()
    if provider_id not in (data.get("providers") or {}):
        return False
    data["active"] = provider_id
    data["providers"][provider_id]["updated_at"] = time.time()
    _save(data)
    return True


def active_provider(workdir: Path | str | None = None) -> dict[str, Any] | None:
    del workdir
    data = _load()
    active = str(data.get("active") or "")
    raw = (data.get("providers") or {}).get(active)
    if not raw or not raw.get("enabled", True):
        return None
    return _public(active, raw, active)


def build_llm_config(provider_id: str, workdir: Path | str | None = None):
    """把某个 provider 转成 `LLMConfig`（让"设为默认"真的生效）"""
    from ..llm.config import LLMConfig, LLMProviderType

    item = get_provider(provider_id)
    if not item:
        raise ValueError(f"provider 不存在: {provider_id}")
    key = resolve_api_key(provider_id)
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


def store_path() -> str:
    """配置文件位置（设置页展示用；不含密钥）"""
    return str(_path())


__all__ = [
    "KINDS",
    "VALID_ID",
    "active_provider",
    "build_llm_config",
    "delete_provider",
    "describe_active",
    "get_provider",
    "list_providers",
    "resolve_api_key",
    "save_provider",
    "set_default",
    "store_path",
]
