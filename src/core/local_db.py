"""本地 SQLite 存储（单一 db 文件，放在 <workdir>/.clawd/clawd.db）

为什么用 SQLite 而不是 JSON 文件：
- **用量/请求日志会持续增长**（每跑一轮就一行），JSON 全量读写会越来越慢，
  而且并发写容易互相覆盖；SQLite 有事务、索引、`GROUP BY`，一次查询就能出统计。
- **零依赖**：`sqlite3` 是标准库，不需要起服务、不需要账号。
- **可迁移**：单个文件，备份就是拷一个文件。

设计约束：
- 只做**本机单人**使用（不做多用户/权限）；所有读写都串行化在短事务里。
- 表结构演进用 `PRAGMA user_version` 记版本，升级时**只加列不删列**，避免老数据打不开。
"""
from __future__ import annotations

import logging
import sqlite3
import time

from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DB_FILENAME = "clawd.db"


def db_path(workdir: Path | str | None = None) -> Path:
    base = Path(workdir) if workdir else Path.cwd()
    directory = base / ".clawd"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / DB_FILENAME


def connect(workdir: Path | str | None = None) -> sqlite3.Connection:
    """打开连接（自动建表；WAL 模式让读写不互相阻塞）"""
    path = db_path(workdir)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.DatabaseError as e:  # pragma: no cover - 特殊文件系统
        logger.warning(f"SQLite PRAGMA 失败（继续）: {e}")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS providers (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            kind        TEXT NOT NULL DEFAULT 'openai',
            base_url    TEXT NOT NULL DEFAULT '',
            model       TEXT NOT NULL DEFAULT '',
            key_env     TEXT NOT NULL DEFAULT '',
            key_inline  TEXT NOT NULL DEFAULT '',
            enabled     INTEGER NOT NULL DEFAULT 1,
            is_default  INTEGER NOT NULL DEFAULT 0,
            created_at  REAL NOT NULL DEFAULT 0,
            updated_at  REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS usage (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            ts                 REAL NOT NULL,
            session_id         TEXT NOT NULL DEFAULT '',
            provider           TEXT NOT NULL DEFAULT '',
            model              TEXT NOT NULL DEFAULT '',
            prompt_tokens      INTEGER NOT NULL DEFAULT 0,
            completion_tokens  INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
            cost               REAL NOT NULL DEFAULT 0,
            duration_ms        INTEGER NOT NULL DEFAULT 0,
            steps              INTEGER NOT NULL DEFAULT 0,
            status             TEXT NOT NULL DEFAULT 'completed',
            goal_chars         INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);
        CREATE INDEX IF NOT EXISTS idx_usage_model ON usage(model);
        """
    )
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()


def now() -> float:
    return time.time()


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def fetch_one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row is not None else None


__all__ = [
    "DB_FILENAME",
    "SCHEMA_VERSION",
    "connect",
    "db_path",
    "fetch_all",
    "fetch_one",
    "init_schema",
    "now",
]
