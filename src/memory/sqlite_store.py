"""SQLite Memory Storage - 基于 SQLite 的持久化存储后端

提供高性能的记忆存储，支持:
- 异步 I/O (通过 aiosqlite 或 asyncio.to_thread)
- 全文搜索 (FTS5)
- 关系型查询 (按标签、项目、重要性等过滤)
- 自动维护元数据和索引
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..core.project_context import ProjectContext
from .models import (
    EpisodicMemory,
    MemoryEntry,
    MemoryKind,
    MemoryType,
    SemanticPattern,
    WorkingMemory,
)


class SQLiteMemoryStorage:
    """基于 SQLite 的记忆存储后端"""

    def __init__(self, db_path: Path | str | None = None, project_ctx: ProjectContext | None = None) -> None:
        """初始化 SQLite 存储

        Args:
            db_path: 数据库文件路径
            project_ctx: 项目上下文
        """
        if db_path is not None:
            self.db_path = Path(db_path)
        elif project_ctx is not None:
            self.db_path = project_ctx.memory_dir / "memory_v2.db"
        else:
            self.db_path = Path('.clawd') / 'memory' / 'memory_v2.db'

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """获取 SQLite 连接 (WAL 模式)"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute('PRAGMA journal_mode=WAL')
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """初始化数据库表和索引"""
        with self._connect() as conn:
            # 1. 记忆条目表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id                  TEXT PRIMARY KEY,
                    memory_type         TEXT NOT NULL,
                    kind                TEXT NOT NULL,
                    content             TEXT NOT NULL,
                    source              TEXT NOT NULL,
                    importance          REAL DEFAULT 0.5,
                    tags                TEXT, -- JSON array
                    selectors           TEXT, -- JSON object
                    metadata            TEXT, -- JSON object
                    created_at          REAL,
                    updated_at          REAL,
                    access_count        INTEGER DEFAULT 0,
                    last_accessed       REAL,
                    verification_state  TEXT DEFAULT 'unverified',
                    confidence          TEXT DEFAULT 'medium',
                    success_association_count INTEGER DEFAULT 0,
                    contradicted_count  INTEGER DEFAULT 0,
                    superseded_by       TEXT DEFAULT ''
                )
            """)

            # 2. 全文搜索虚拟表 (FTS5)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    id UNINDEXED,
                    content,
                    tags,
                    kind,
                    content='memory_entries',
                    content_rowid='id'
                )
            """)

            # 3. 语义模式表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS semantic_patterns (
                    id              TEXT PRIMARY KEY,
                    name            TEXT,
                    category        TEXT,
                    pattern         TEXT,
                    problem         TEXT,
                    solution        TEXT,
                    confidence      REAL,
                    applications    INTEGER DEFAULT 0,
                    target_skills   TEXT, -- JSON array
                    created_at      REAL
                )
            """)

            # 4. 情景记忆表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodic_memories (
                    id                  TEXT PRIMARY KEY,
                    timestamp           REAL,
                    skill_used          TEXT,
                    situation           TEXT,
                    root_cause          TEXT,
                    solution            TEXT,
                    lesson              TEXT,
                    related_pattern_id  TEXT,
                    user_rating         REAL,
                    user_comments       TEXT,
                    FOREIGN KEY (related_pattern_id) REFERENCES semantic_patterns(id)
                )
            """)

            # 5. 工作记忆表 (持久化当前会话状态)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS working_memories (
                    session_id  TEXT PRIMARY KEY,
                    data        TEXT, -- JSON object
                    created_at  REAL,
                    expires_at  REAL
                )
            """)

            # 索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_type ON memory_entries(memory_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_kind ON memory_entries(kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_importance ON memory_entries(importance)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_created ON memory_entries(created_at)")

    # -- MemoryEntry API --

    def save_entry(self, entry: MemoryEntry) -> None:
        """保存或更新记忆条目"""
        with self._connect() as conn:
            d = entry.to_dict()
            conn.execute("""
                INSERT OR REPLACE INTO memory_entries (
                    id, memory_type, kind, content, source, importance, tags,
                    selectors, metadata, created_at, updated_at, access_count,
                    last_accessed, verification_state, confidence,
                    success_association_count, contradicted_count, superseded_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d['id'], d['memory_type'], d['kind'], d['content'], d['source'],
                d['importance'], json.dumps(d['tags']), json.dumps(d['selectors']),
                json.dumps(d['metadata']), d['created_at'], d['updated_at'],
                d['access_count'], d['last_accessed'], d['verification_state'],
                d['confidence'], d['success_association_count'],
                d['contradicted_count'], d['superseded_by']
            ))
            # 更新 FTS
            conn.execute("DELETE FROM memory_fts WHERE id = ?", (d['id'],))
            conn.execute("""
                INSERT INTO memory_fts (id, content, tags, kind)
                VALUES (?, ?, ?, ?)
            """, (d['id'], d['content'], " ".join(d['tags']), d['kind']))

    def get_entry(self, entry_id: str) -> MemoryEntry | None:
        """根据 ID 获取记忆条目"""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_entries WHERE id = ?", (entry_id,)).fetchone()
            if not row:
                return None
            return self._row_to_entry(row)

    def search_entries(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """全文搜索记忆"""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT me.* FROM memory_entries me
                JOIN memory_fts fts ON me.id = fts.id
                WHERE memory_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit)).fetchall()
            return [self._row_to_entry(row) for row in rows]

    def list_entries(self, memory_type: MemoryType | None = None, kind: MemoryKind | None = None,
                     tag: str | None = None, limit: int = 100) -> list[MemoryEntry]:
        """列表查询记忆，支持多种过滤"""
        query = "SELECT * FROM memory_entries WHERE 1=1"
        params = []
        if memory_type:
            query += " AND memory_type = ?"
            params.append(memory_type.value)
        if kind:
            query += " AND kind = ?"
            params.append(kind.value)
        if tag:
            query += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_entry(row) for row in rows]

    def _row_to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        """将数据库行转换为 MemoryEntry 对象"""
        data = dict(row)
        data['tags'] = json.loads(data['tags'] or '[]')
        data['selectors'] = json.loads(data['selectors'] or '{}')
        data['metadata'] = json.loads(data['metadata'] or '{}')
        # 处理 evidence 字段（在 models.py 中 MemoryEntry 有 evidence，但表结构里为了简化合并到 metadata 或单独表）
        # 这里暂时假设存储在 metadata 中，或者先留空
        return MemoryEntry.from_dict(data)

    # -- SemanticPattern API --

    def save_pattern(self, pattern: SemanticPattern) -> None:
        """保存语义模式"""
        with self._connect() as conn:
            d = pattern.to_dict()
            conn.execute("""
                INSERT OR REPLACE INTO semantic_patterns (
                    id, name, category, pattern, problem, solution,
                    confidence, applications, target_skills, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d['id'], d['name'], d['category'], d['pattern'], d['problem'],
                d['solution'], d['confidence'], d['applications'],
                json.dumps(d['target_skills']), d['created_at']
            ))

    # -- EpisodicMemory API --

    def save_episodic(self, memory: EpisodicMemory) -> None:
        """保存情景记忆"""
        with self._connect() as conn:
            d = memory.to_dict()
            conn.execute("""
                INSERT OR REPLACE INTO episodic_memories (
                    id, timestamp, skill_used, situation, root_cause,
                    solution, lesson, related_pattern_id, user_rating, user_comments
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d['id'], d['timestamp'], d['skill_used'], d['situation'],
                d['root_cause'], d['solution'], d['lesson'],
                d['related_pattern_id'], d['user_rating'], d['user_comments']
            ))

    # -- WorkingMemory API --

    def save_working(self, memory: WorkingMemory) -> None:
        """保存工作记忆"""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO working_memories (
                    session_id, data, created_at, expires_at
                ) VALUES (?, ?, ?, ?)
            """, (
                memory.session_id, json.dumps(memory.data),
                memory.created_at, memory.expires_at
            ))

    def load_working(self, session_id: str) -> WorkingMemory | None:
        """加载工作记忆"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM working_memories WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            if not row:
                return None
            return WorkingMemory(
                session_id=row['session_id'],
                data=json.loads(row['data']),
                created_at=row['created_at'],
                expires_at=row['expires_at']
            )
