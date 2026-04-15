"""Memory Manager - 记忆管理器

从 claude-code-rust-master 汲取的架构优点:
- 多层记忆统一管理入口
- 语义/情景/工作记忆分离
- 记忆整合引擎
- 持久化存储
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from ..rag.text_indexer import TextIndexer
from .context_window import ContextWindowManager
from .evolution import MemoryEvolver
from .models import (
    EpisodicMemory,
    JournalEntry,
    MemoryEntry,
    MemoryStatus,
    MemoryType,
    SemanticPattern,
    WorkingMemory,
)
from .sqlite_store import SQLiteMemoryStorage
from .storage import MemoryStorage


class MemoryManager:
    """记忆管理器

    统一管理多层记忆系统:
    - 语义记忆 (Semantic): 抽象知识/模式/规则
    - 情景记忆 (Episodic): 具体经验/事件
    - 工作记忆 (Working): 当前会话上下文

    功能:
    - 添加/查询/删除记忆
    - 按类型/标签/重要性搜索
    - 记忆整合 (Consolidation)
    - 持久化存储 (支持 SQLite 后端)

    使用方式:
        mgr = MemoryManager()
        await mgr.add_memory(MemoryEntry(content="...", memory_type=MemoryType.SEMANTIC))
        results = await mgr.search("keyword")
    """

    def __init__(self, memory_dir: Path | None = None, use_sqlite: bool = True, project_ctx: Any | None = None) -> None:
        if use_sqlite:
            self.storage = SQLiteMemoryStorage(project_ctx=project_ctx)
            if hasattr(self.storage, 'init_db'):
                self.storage.init_db()
        else:
            self.storage = MemoryStorage(memory_dir)
        self._entries: list[MemoryEntry] = []
        self._patterns: list[SemanticPattern] = []
        self._journals: list[JournalEntry] = []  # 新增: 操作日志列表
        self._working = WorkingMemory()
        self._last_consolidation: float | None = None
        self._use_sqlite = use_sqlite

        # 增强功能
        from .notepad import Notepad
        self.notepad = Notepad(storage_path=(memory_dir / "notepad.json") if memory_dir else None)
        self.indexer = TextIndexer(root_dir=project_ctx.workdir if project_ctx else None)  # RAG 索引器
        self.context_window = ContextWindowManager()  # 对话窗口管理器
        self.evolver = MemoryEvolver(store=self)  # 记忆演进引擎

    async def initialize(self, session_id: str | None = None) -> None:
        """初始化 - 加载已有记忆"""
        try:
            if self._use_sqlite:
                # SQLite 模式下，按需加载或保持延迟加载
                self._entries = self.storage.list_entries(limit=1000)
                # 加载语义模式
                if hasattr(self.storage, 'list_patterns'):
                    self._patterns = self.storage.list_patterns()
                else:
                    # 回退到基础查询
                    with self.storage._connect() as conn:
                        rows = conn.execute("SELECT * FROM semantic_patterns").fetchall()
                        self._patterns = [SemanticPattern(**dict(r)) for r in rows]

                # 加载当前会话的工作记忆
                if session_id:
                    working = self.storage.load_working(session_id)
                    if working:
                        self._working = working
            else:
                self._entries = await self.storage.load_entries()
                self._patterns = await self.storage.load_patterns()
                self._working = await self.storage.load_working()
        except Exception as e:
            logging.getLogger('memory.manager').debug(f'No existing memory found, starting fresh: {e}')

    async def save(self) -> None:
        """保存所有记忆"""
        # [Phase 5] 处理待提升的证据到情景记忆
        await self._process_pending_episodic_promotion()

        if self._use_sqlite:
            for entry in self._entries:
                self.storage.save_entry(entry)
            for pattern in self._patterns:
                self.storage.save_pattern(pattern)
            if self._working.session_id:
                self.storage.save_working(self._working)
        else:
            await self.storage.save_entries(self._entries)
            await self.storage.save_patterns(self._patterns)
            await self.storage.save_working(self._working)

    async def _process_pending_episodic_promotion(self) -> int:
        """[Phase 5] 处理待提升的证据到情景记忆

        从工作记忆中检查并处理待提升的证据条目。
        这实现了 Evidence-Gated Memory 模式。

        Returns:
            提升的记忆数量
        """
        pending = self._working.get("_pending_episodic_promotion")
        if not pending:
            return 0

        from .models import EpisodicMemory
        promoted_count = 0
        logger = logging.getLogger('memory.manager')

        try:
            tasks_data = pending.get("tasks", [])
            goal = pending.get("goal", "")
            timestamp = pending.get("timestamp", 0)
            logger.debug(f"正在处理 {len(tasks_data)} 个任务的证据提升 (目标: {goal})")

            for task_data in tasks_data:
                evidence_paths = task_data.get("evidence_paths", [])
                if not evidence_paths:
                    logger.debug(f"任务 {task_data.get('task_id')} 无证据路径，跳过提升")
                    continue

                # 构建情景记忆
                situation = f"目标: {goal[:100]} | 任务: {task_data.get('title', '')} | 状态: {task_data.get('status', '')}"
                result = task_data.get("result", "")
                result_summary = result[:200] if result and len(result) > 200 else (result or "")

                solution = "\n".join(evidence_paths) if evidence_paths else ""
                status = task_data.get("status", "")

                lesson = ""
                if status == "completed":
                    lesson = "任务成功完成，证据已记录"
                elif status == "failed":
                    lesson = f"任务失败: {result_summary[:100]}"
                else:
                    lesson = f"任务结束 (状态: {status})"

                episodic = EpisodicMemory(
                    skill_used="workflow:deliver",
                    situation=situation,
                    solution=solution,
                    lesson=lesson,
                )

                logger.debug(f"保存情景记忆: {episodic.id} (任务: {task_data.get('task_id')})")
                await self.add_episodic(episodic)
                promoted_count += 1

            # 清除待处理记录
            self._working.set("_pending_episodic_promotion", None)
            if promoted_count > 0:
                logger.info(f"已提升 {promoted_count} 条情景记忆 (目标: {goal[:50]}...)")

        except Exception as e:
            logger.error(f"处理待提升证据失败: {e}", exc_info=True)

        return promoted_count

    # 记忆条目操作

    async def add_memory(self, entry: MemoryEntry) -> str:
        """添加记忆条目

        Returns:
            记忆 ID
        """
        self._entries.append(entry)
        # 同步到 Notepad 高优先级上下文
        if entry.importance >= 0.8:
            self.notepad.add_priority(entry.content, {"id": entry.id, "type": entry.memory_type})
        else:
            self.notepad.add_log(f"New Memory: {entry.content[:50]}...", {"id": entry.id})

        # 同步到 RAG 索引以支持语义搜索
        from ..rag.models import Document
        doc = Document(
            id=entry.id,
            content=entry.content,
            source=f"memory:{entry.memory_type.value}",
            metadata={"tags": entry.tags, "importance": entry.importance}
        )
        self.indexer.add_document(doc)
        return entry.id

    async def add_journal(self, journal: JournalEntry) -> str:
        """添加操作日志 (从 goalx-main 整合)

        记录 Agent 执行过程中的每一步决策。
        """
        self._journals.append(journal)
        # 同步记录到 Notepad 工作日志
        self.notepad.add_log(f"Action: {journal.action} | Result: {journal.status}", {"task_id": journal.task_id})

        # 暂时只在 SQLite 存储中记录，不放入 RAG 索引以节省开销
        if self._use_sqlite and hasattr(self.storage, 'save_journal'):
            self.storage.save_journal(journal)
        return journal.id

    async def get_journals_by_task(self, task_id: str) -> list[JournalEntry]:
        """获取任务相关的日志"""
        return [j for j in self._journals if j.task_id == task_id]

    async def get_journals_by_agent(self, agent_id: str) -> list[JournalEntry]:
        """获取 Agent 相关的日志"""
        return [j for j in self._journals if j.agent_id == agent_id]

    async def get_memory(self, memory_id: str) -> MemoryEntry | None:
        """获取记忆条目"""
        for e in self._entries:
            if e.id == memory_id:
                e.access()
                return e
        return None

    async def search_memories(self, query: str, use_rag: bool = True) -> list[MemoryEntry]:
        """搜索记忆 (支持 RAG 语义搜索)"""
        if use_rag:
            rag_results = self.indexer.search(query, top_k=10)
            if rag_results:
                # 将 RAG 结果映射回 MemoryEntry
                entry_ids = {r.chunk.document_id for r in rag_results}
                return [e for e in self._entries if e.id in entry_ids]

        # 回退到关键词搜索
        query_lower = query.lower()
        results: list[MemoryEntry] = []
        for e in self._entries:
            if query_lower in e.content.lower() or \
               any(query_lower in t.lower() for t in e.tags):
                e.access()
                results.append(e)

        results.sort(
            key=lambda x: x.importance * 0.7 + min(x.access_count * 0.1, 0.3),
            reverse=True
        )
        return results

    async def get_memories_by_type(self, memory_type: MemoryType) -> list[MemoryEntry]:
        """按类型获取记忆"""
        return [e for e in self._entries if e.memory_type == memory_type]

    async def get_important_memories(self, threshold: float = 0.7) -> list[MemoryEntry]:
        """获取高重要性记忆"""
        return [e for e in self._entries if e.importance >= threshold]

    async def delete_memory(self, memory_id: str) -> bool:
        """删除记忆条目"""
        for i, e in enumerate(self._entries):
            if e.id == memory_id:
                self._entries.pop(i)
                return True
        return False

    async def clear(self) -> None:
        """清空所有记忆"""
        self._entries.clear()
        self._patterns.clear()
        self._working.clear()
        self._last_consolidation = None

    # 语义模式操作

    async def add_pattern(self, pattern: SemanticPattern) -> str:
        """添加语义模式"""
        self._patterns.append(pattern)
        return pattern.id

    def get_patterns(self) -> list[SemanticPattern]:
        """获取所有语义模式"""
        return self._patterns.copy()

    def get_pattern(self, pattern_id: str) -> SemanticPattern | None:
        """获取语义模式"""
        for p in self._patterns:
            if p.id == pattern_id:
                return p
        return None

    # 情景记忆操作

    async def add_episodic(self, memory: EpisodicMemory) -> str:
        """添加情景记忆"""
        # 支持同步和异步存储后端
        result = self.storage.save_episodic(memory)
        if asyncio.iscoroutine(result):
            await result
        return memory.id

    async def get_episodic(self, episodic_id: str) -> EpisodicMemory | None:
        """获取情景记忆"""
        result = self.storage.load_episodic(episodic_id)
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def list_episodic(self) -> list[EpisodicMemory]:
        """列出所有情景记忆"""
        result = self.storage.list_episodic()
        if asyncio.iscoroutine(result):
            return await result
        return result

    # 工作记忆操作

    def working(self) -> WorkingMemory:
        """获取工作记忆"""
        return self._working

    def working_set(self, key: str, value: Any) -> None:
        """设置工作记忆"""
        self._working.set(key, value)

    def working_get(self, key: str, default: Any = None) -> Any:
        """获取工作记忆"""
        return self._working.get(key, default)

    # 记忆整合

    async def consolidate(self) -> None:
        """记忆整合

        整合策略:
        - 低重要性记忆降权
        - 高频访问记忆提权
        - 清理过期工作记忆
        """
        now = time.time()

        # 更新模式置信度
        for pattern in self._patterns:
            if pattern.applications > 5:
                pattern.confidence = min(1.0, pattern.confidence + 0.05)

        # 降权低重要性且未被访问的记忆
        for entry in self._entries:
            if entry.importance < 0.3 and entry.last_accessed is None:
                entry.importance *= 0.9
            elif entry.access_count > 0:
                entry.importance = min(1.0, entry.importance + 0.05 * entry.access_count)

        self._last_consolidation = now

        # 集成 MemoryEvolver: 晋升记忆
        proposals = self.working_get("memory_proposals", [])
        if proposals:
            promoted_entries = self.evolver.aggregate_proposals(proposals)
            for entry in promoted_entries:
                from .models import MemoryEntry as StoreEntry
                await self.add_memory(StoreEntry(
                    content=f"[{entry.kind.upper()}] {entry.statement}",
                    memory_type=MemoryType.SEMANTIC,
                    importance=0.8 if entry.verification == "validated" else 0.6,
                    tags=list(entry.selectors.values())
                ))
            # 清空已处理的 proposals
            self.working_set("memory_proposals", [])

        await self.save()

    # 状态

    async def get_status(self) -> MemoryStatus:
        """获取记忆状态"""
        storage_size = await self.storage.get_storage_size()
        await self.storage.list_episodic()

        return MemoryStatus(
            total_memories=len(self._entries),
            semantic_count=len([e for e in self._entries if e.memory_type == MemoryType.SEMANTIC]),
            episodic_count=len([e for e in self._entries if e.memory_type == MemoryType.EPISODIC]),
            working_count=len([e for e in self._entries if e.memory_type == MemoryType.WORKING]),
            pattern_count=len(self._patterns),
            last_consolidation=self._last_consolidation,
            storage_size_bytes=storage_size,
        )

    async def export(self, output_path: Path) -> None:
        """导出所有记忆"""
        data = {
            "entries": [e.to_dict() for e in self._entries],
            "patterns": [p.to_dict() for p in self._patterns],
            "episodic": [m.to_dict() for m in await self.storage.list_episodic()],
            "working": self._working.data,
        }
        await asyncio.to_thread(
            output_path.write_text,
            json.dumps(data, indent=2, ensure_ascii=False),
        )

    async def import_memories(self, input_path: Path) -> int:
        """导入记忆

        Returns:
            导入的记忆数量
        """
        content = await asyncio.to_thread(input_path.read_text, encoding="utf-8")
        data = json.loads(content)

        count = 0
        for d in data.get("entries", []):
            await self.add_memory(MemoryEntry.from_dict(d))
            count += 1

        for d in data.get("patterns", []):
            self._patterns.append(SemanticPattern(**{
                k: v for k, v in d.items() if k in SemanticPattern.__dataclass_fields__
            }))
            count += 1

        return count

    # ========== [汲取 GoalX] Memory Seed & Promote ==========

    async def seed_memory(self, project_id: str, content: str, memory_type: MemoryType = MemoryType.SEMANTIC, importance: float = 0.9) -> str:
        """[汲取 GoalX memory seed] 预设核心记忆

        在项目启动时预设关键记忆，如项目规范、核心约束、重要联系人等。
        这些记忆会被标记为种子记忆，具有较高的持久性。

        Args:
            project_id: 项目标识
            content: 记忆内容
            memory_type: 记忆类型
            importance: 重要性 (0-1)

        Returns:
            记忆 ID
        """
        entry = MemoryEntry(
            content=content,
            memory_type=memory_type,
            importance=importance,
            tags=["seed", "core_knowledge"],
            selectors={"project_id": project_id},
        )
        # 标记为种子记忆
        entry.metadata["is_seed"] = True
        entry.metadata["seeded_at"] = time.time()

        return await self.add_memory(entry)

    async def promote_to_long_term(self, memory_id: str, reason: str = "") -> bool:
        """[汲取 GoalX memory promote] 将短期记忆升级为长期记忆

        将特定的短期/情景记忆晋升为语义记忆，使其具有更长的生命周期
        和更高的重要性。

        Args:
            memory_id: 要晋升的记忆 ID
            reason: 晋升原因

        Returns:
            是否成功
        """
        entry = await self.get_memory(memory_id)
        if not entry:
            return False

        # 创建新的语义记忆作为副本
        promoted = MemoryEntry(
            content=entry.content,
            memory_type=MemoryType.SEMANTIC,  # 晋升为语义记忆
            importance=min(1.0, entry.importance + 0.2),  # 提升重要性
            tags=["promoted", f"promoted_from_{entry.memory_type.value}", *entry.tags],
        )
        # 传递选择器信息
        if entry.selectors:
            promoted.selectors.update(entry.selectors)

        promoted.metadata["promoted_from_id"] = memory_id
        promoted.metadata["promoted_reason"] = reason
        promoted.metadata["promoted_at"] = time.time()

        await self.add_memory(promoted)

        # 可选：标记原记忆为已晋升
        if entry.memory_type == MemoryType.EPISODIC:
            entry.metadata["promoted"] = True

        return True

    async def retrieve_similar_experiences(self, query: str, limit: int = 5) -> list[EpisodicMemory]:
        """[汲取 GoalX memory retrieve] 检索相似经验

        基于语义相似度检索相关的情景记忆，用于从历史经验中学习。

        Args:
            query: 查询文本
            limit: 返回数量限制

        Returns:
            相似的情景记忆列表
        """
        # 使用 RAG 检索相似的语义记忆
        semantic_results = await self.search_memories(query, use_rag=True)

        # 查找相关的情景记忆
        related_episodic = []
        for entry in semantic_results[:limit]:
            episodic_list = await self.storage.list_episodic()
            related = [e for e in episodic_list if entry.id in e.tags or entry.id in (e.metadata or {})]
            related_episodic.extend(related[:2])  # 每个语义记忆最多取 2 个情景

        return related_episodic[:limit]

    async def get_project_seed_memories(self, project_id: str) -> list[MemoryEntry]:
        """获取项目的所有种子记忆"""
        return [
            e for e in self._entries
            if e.selectors.get("project_id") == project_id and e.metadata.get("is_seed", False)
        ]
