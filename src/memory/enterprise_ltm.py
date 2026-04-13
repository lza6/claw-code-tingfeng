"""Enterprise Long-Term Memory (LTM) - 基于 SQLite 的企业级持久化记忆层

核心功能:
1. 模式存储: 自动提取并保存成功的代码实现模式
2. 语义索引: 基于关键字和组件图的轻量级关联检索
3. 跨会话同步: 支持多个项目间的成功经验复用

存储路径: 项目目录/.clawd/enterprise_ltm.db

v0.45.0: 修复同步 sqlite3 在 async 方法中阻塞事件循环的问题
         所有 DB 操作通过 asyncio.to_thread() 异步化
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..core.config.models import get_settings
from ..core.project_context import ProjectContext
from ..llm.litellm_singleton import get_litellm
from ..rag.vector_store.base import VectorDocument, VectorStore
from ..rag.vector_store.local import LocalVectorStore

logger = logging.getLogger(__name__)


class PatternType(str, Enum):
    SUCCESS = "success"
    FAILURE_PREVENTION = "failure_prevention"

@dataclass
class ImplementationPattern:
    """代码实现模式"""
    pattern_id: str
    task_type: str
    description: str
    solution_code: str
    success_metrics: dict[str, Any]
    pattern_type: PatternType = PatternType.SUCCESS
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

class EnterpriseLTM:
    """企业级长短期记忆总线"""

    def __init__(self, db_path: Path | None = None, project_ctx: ProjectContext | None = None, vector_store: VectorStore | None = None) -> None:
        """初始化企业级长短期记忆总线

        Args:
            db_path: 数据库路径（显式指定时优先使用）
            project_ctx: 项目上下文（用于自动推导路径）
            vector_store: 向量存储（可选）
        """
        if db_path is not None:
            self.db_path = db_path
        elif project_ctx is not None:
            self.db_path = project_ctx.enterprise_ltm_path
        else:
            # 向后兼容：使用相对路径
            self.db_path = Path('.clawd') / 'enterprise_ltm.db'

        self._init_db()

        # 初始化向量存储
        if vector_store:
            self.vector_store = vector_store
        else:
            self.vector_store = self._init_vector_store()

    def _init_vector_store(self) -> VectorStore:
        """根据配置初始化向量存储"""
        settings = get_settings()
        vs_type = settings.vector_store_type.lower()
        dimension = settings.vector_store_dimension

        if vs_type == "faiss":
            try:
                from ..rag.vector_store.faiss_store import FaissStore
                return FaissStore(dimension=dimension)
            except ImportError:
                logger.warning("[LTM] FAISS 未安装，回退到 local 存储")
                vs_type = "local"

        if vs_type == "qdrant":
            try:
                from ..rag.vector_store.qdrant import QdrantStore
                return QdrantStore(vector_size=dimension)
            except ImportError:
                logger.warning("[LTM] QdrantClient 未安装，回退到 local 存储")
                vs_type = "local"

        # 默认使用本地向量存储
        vector_path = settings.vector_store_path or self.db_path.with_suffix('.vectors.json')
        return LocalVectorStore(storage_path=vector_path, dimension=dimension)

    def _init_db(self) -> None:
        """初始化数据库表"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS implementation_patterns (
                    pattern_id TEXT PRIMARY KEY,
                    task_type TEXT,
                    description TEXT,
                    solution_code TEXT,
                    success_metrics TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_type ON implementation_patterns(task_type)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_heatmap (
                    tool_name TEXT PRIMARY KEY,
                    call_count INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 0.0,
                    avg_latency REAL DEFAULT 0.0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    goal TEXT,
                    status TEXT,
                    error_msg TEXT,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP
                )
            """)

    # ─── 同步内部方法 (在线程池中执行) ────────────────────────────────

    def _store_pattern_sync(self, pattern: ImplementationPattern) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO implementation_patterns (pattern_id, task_type, description, solution_code, success_metrics) VALUES (?, ?, ?, ?, ?)",
                (
                    pattern.pattern_id,
                    pattern.task_type,
                    pattern.description,
                    pattern.solution_code,
                    json.dumps(pattern.success_metrics)
                )
            )
            logger.info(f"[LTM] 成功持久化模式: {pattern.pattern_id}")

    def _find_similar_patterns_sync(self, task_description: str, limit: int) -> list[ImplementationPattern]:
        keywords = [k for k in task_description.split() if len(k) > 3]
        query = "SELECT * FROM implementation_patterns WHERE " + " OR ".join(["description LIKE ?" for _ in keywords]) + " LIMIT ?"
        params = [f"%{k}%" for k in keywords] + [limit]

        if not keywords:
            query = "SELECT * FROM implementation_patterns ORDER BY created_at DESC LIMIT ?"
            params = [limit]

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [
                ImplementationPattern(
                    pattern_id=row[0],
                    task_type=row[1],
                    description=row[2],
                    solution_code=row[3],
                    success_metrics=json.loads(row[4]),
                    created_at=row[5]
                ) for row in rows
            ]

    def _update_heatmap_sync(self, tool_name: str, success: bool, latency: float) -> None:
        with sqlite3.connect(self.db_path) as conn:
            # SQLite ON CONFLICT SET 子句中所有列引用都是旧行值，
            # 所以用 EXCLUDED 引用 INSERT 中要写入的新值来正确计算 rolling average。
            conn.execute("""
                INSERT INTO execution_heatmap (tool_name, call_count, success_rate, avg_latency)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(tool_name) DO UPDATE SET
                    call_count = call_count + 1,
                    success_rate = (success_rate * call_count + EXCLUDED.success_rate) / (call_count + 1),
                    avg_latency = (avg_latency * call_count + EXCLUDED.avg_latency) / (call_count + 1)
            """, (tool_name, 1.0 if success else 0.0, latency))

    def _record_session_start_sync(self, session_id: str, goal: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (session_id, goal, status) VALUES (?, ?, ?)",
                (session_id, goal, "started")
            )

    def _record_session_failure_sync(self, session_id: str, error_msg: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET status = ?, error_msg = ?, ended_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                ("failed", error_msg, session_id)
            )

    # ─── 异步公共接口 (通过 asyncio.to_thread 委托) ──────────────────

    async def store_pattern(self, pattern: ImplementationPattern) -> None:
        """持久化一个实现模式"""
        # 1. 生成嵌入向量
        try:
            # 使用线程池执行同步的 embedding 调用
            def _get_embedding():
                return get_litellm().embedding(model="text-embedding-3-small", input=pattern.description)

            resp = await asyncio.to_thread(_get_embedding)
            if resp and hasattr(resp, 'data') and len(resp.data) > 0:
                vector = resp.data[0]['embedding']
                # 2. 存入向量存储
                await self.vector_store.add([
                    VectorDocument(
                        id=pattern.pattern_id,
                        vector=vector,
                        content=pattern.description,
                        metadata={"task_type": pattern.task_type}
                    )
                ])
        except Exception as e:
            logger.warning(f"[LTM] 生成或存储向量失败: {e}")

        # 3. 存入 SQLite
        await asyncio.to_thread(self._store_pattern_sync, pattern)

    async def find_similar_patterns(self, task_description: str, limit: int = 3) -> list[ImplementationPattern]:
        """寻找相似的历时模式 (优先使用向量搜索，失败则回退到关键字)"""
        try:
            # 1. 生成查询向量
            def _get_query_vector():
                return get_litellm().embedding(model="text-embedding-3-small", input=task_description)

            resp = await asyncio.to_thread(_get_query_vector)
            if resp and hasattr(resp, 'data') and len(resp.data) > 0:
                query_vector = resp.data[0]['embedding']

                # 2. 向量检索
                vec_results = await self.vector_store.search(query_vector=query_vector, top_k=limit)
                if vec_results:
                    pattern_ids = [res.id for res in vec_results]
                    # 从 SQLite 加载完整对象
                    return await asyncio.to_thread(self._load_patterns_by_ids, pattern_ids)
        except Exception as e:
            logger.debug(f"[LTM] 向量搜索失败，将回退到关键字匹配: {e}")

        # 3. 回退到关键字匹配
        return await asyncio.to_thread(self._find_similar_patterns_sync, task_description, limit)

    def _load_patterns_by_ids(self, ids: list[str]) -> list[ImplementationPattern]:
        """根据 ID 列表批量加载模式 (同步方法)"""
        if not ids:
            return []

        placeholders = ', '.join(['?'] * len(ids))
        query = f"SELECT * FROM implementation_patterns WHERE pattern_id IN ({placeholders})"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, ids)
            rows = cursor.fetchall()
            # 保持输入 ID 的顺序
            id_to_row = {row[0]: row for row in rows}
            results = []
            for pid in ids:
                if pid in id_to_row:
                    row = id_to_row[pid]
                    results.append(ImplementationPattern(
                        pattern_id=row[0],
                        task_type=row[1],
                        description=row[2],
                        solution_code=row[3],
                        success_metrics=json.loads(row[4]),
                        created_at=row[5]
                    ))
            return results

    async def _load_patterns_by_ids_async(self, ids: list[str]) -> list[ImplementationPattern]:
        return await asyncio.to_thread(self._load_patterns_by_ids, ids)

    async def update_heatmap(self, tool_name: str, success: bool, latency: float) -> None:
        """更新工具执行热力图"""
        await asyncio.to_thread(self._update_heatmap_sync, tool_name, success, latency)

    async def record_session_start(self, session_id: str, goal: str) -> None:
        """记录会话开始"""
        await asyncio.to_thread(self._record_session_start_sync, session_id, goal)

    async def record_session_failure(self, session_id: str, error_msg: str) -> None:
        """记录会话失败"""
        await asyncio.to_thread(self._record_session_failure_sync, session_id, error_msg)

    async def learn_pattern(self, goal: str, implementation: Any = None, rejection_reason: str | None = None, pattern_type: PatternType = PatternType.SUCCESS) -> None:
        """学习并持久化模式"""
        pattern_id = str(uuid.uuid4())[:8]
        pattern = ImplementationPattern(
            pattern_id=pattern_id,
            task_type="general",
            description=goal,
            solution_code=json.dumps(implementation) if implementation else "",
            success_metrics={"rejection_reason": rejection_reason} if rejection_reason else {},
            pattern_type=pattern_type
        )
        await self.store_pattern(pattern)
