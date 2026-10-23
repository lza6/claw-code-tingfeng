"""MemoryManager 深度行为测试（真实文件系统 + 真实 SQLite，不 mock 存储层）。

覆盖行为面：
1. 两种后端的构造与 schema 初始化（幂等）
2. 写入 / 检索 / 删除 / 按类型与重要性过滤
3. RAG 语义搜索命中与关键词回退
4. 语义模式、情景记忆、操作日志
5. 关闭重开后的持久化往返（JSON 后端与 SQLite 后端）
6. 空状态、损坏状态文件、初始化失败降级
7. 记忆整合（consolidate）的权重/置信度/提案晋升
8. 状态统计（get_status）在两种后端上的取数
9. 导出 / 导入往返（UTF-8 + 中文内容）
10. GoalX 记忆种子与长期化晋升
11. 并发写入（asyncio.gather）

说明：所有测试都使用 `tmp_path`；SQLite 后端通过 `ProjectContext(workdir=tmp_path)`
把 `.clawd/` 关进临时目录，绝不在仓库根目录落盘。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest
from src.core.project_context import ProjectContext
from src.memory.context_window import ContextWindowManager
from src.memory.manager import MemoryManager
from src.memory.models import (
    EpisodicMemory,
    JournalEntry,
    MemoryEntry,
    MemoryType,
    SemanticPattern,
    WorkingMemory,
)
from src.memory.sqlite_store import SQLiteMemoryStorage
from src.memory.storage import MemoryStorage
from src.rag.text_indexer import TextIndexer

# ============================================================================
# 辅助
# ============================================================================

def _json_backend(tmp_path) -> MemoryManager:
    return MemoryManager(memory_dir=tmp_path / "memory", use_sqlite=False)


def _sqlite_backend(tmp_path) -> MemoryManager:
    return MemoryManager(
        memory_dir=tmp_path / "memory",
        use_sqlite=True,
        project_ctx=ProjectContext(workdir=tmp_path),
    )


def _sqlite_tables(db_path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


# ============================================================================
# 1. 构造与 schema
# ============================================================================

class TestConstruction:
    def test_json_backend_wires_storage_notepad_indexer_and_evolver(self, tmp_path):
        manager = _json_backend(tmp_path)

        assert isinstance(manager.storage, MemoryStorage)
        assert manager._use_sqlite is False
        assert manager.notepad.storage_path == tmp_path / "memory" / "notepad.json"
        assert isinstance(manager.indexer, TextIndexer)
        assert isinstance(manager.context_window, ContextWindowManager)
        assert manager.evolver.store is manager
        assert manager._entries == []
        assert manager._patterns == []
        assert manager._journals == []
        assert manager.working().data == {}

    def test_sqlite_backend_creates_database_inside_project_context(self, tmp_path):
        manager = _sqlite_backend(tmp_path)

        assert isinstance(manager.storage, SQLiteMemoryStorage)
        assert manager._use_sqlite is True
        db_path = tmp_path / ".clawd" / "memory" / "memory_v2.db"
        assert manager.storage.db_path == db_path
        assert db_path.is_file()
        assert {"memory_entries", "semantic_patterns", "episodic_memories", "working_memories"} <= \
            _sqlite_tables(db_path)

    async def test_sqlite_schema_initialisation_is_idempotent_and_keeps_data(self, tmp_path):
        first = _sqlite_backend(tmp_path)
        await first.add_memory(MemoryEntry(content="保留我", memory_type=MemoryType.SEMANTIC))
        await first.save()

        second = _sqlite_backend(tmp_path)
        await second.initialize()

        assert [e.content for e in second._entries] == ["保留我"]


# ============================================================================
# 2. 写入 / 检索 / 删除
# ============================================================================

class TestMemoryEntryOperations:
    async def test_high_importance_entry_goes_to_priority_context(self, tmp_path):
        manager = _json_backend(tmp_path)
        entry = MemoryEntry(content="关键约束", importance=0.9)

        memory_id = await manager.add_memory(entry)

        assert memory_id == entry.id
        assert len(manager.notepad.priority_context) == 1
        assert manager.notepad.priority_context[0].content == "关键约束"
        assert manager.notepad.working_logs == []

    async def test_low_importance_entry_goes_to_working_log(self, tmp_path):
        manager = _json_backend(tmp_path)
        entry = MemoryEntry(content="普通记录" * 10, importance=0.4)

        await manager.add_memory(entry)

        assert manager.notepad.priority_context == []
        assert len(manager.notepad.working_logs) == 1
        assert manager.notepad.working_logs[0].content.startswith("New Memory:")

    async def test_added_entry_is_searchable_through_rag_index(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="asyncio gather 并发下载"))

        hits = await manager.search_memories("asyncio")

        assert len(hits) == 1
        assert manager.indexer.search("asyncio", top_k=5)

    async def test_get_memory_records_access_and_returns_none_for_unknown_id(self, tmp_path):
        manager = _json_backend(tmp_path)
        memory_id = await manager.add_memory(MemoryEntry(content="x"))

        found = await manager.get_memory(memory_id)

        assert found is not None
        assert found.access_count == 1
        assert found.last_accessed is not None
        assert await manager.get_memory("does-not-exist") is None

    async def test_delete_memory_reports_whether_entry_existed(self, tmp_path):
        manager = _json_backend(tmp_path)
        memory_id = await manager.add_memory(MemoryEntry(content="to delete"))

        assert await manager.delete_memory(memory_id) is True
        assert await manager.get_memory(memory_id) is None
        assert await manager.delete_memory(memory_id) is False

    async def test_get_memories_by_type_filters_exactly(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="s1", memory_type=MemoryType.SEMANTIC))
        await manager.add_memory(MemoryEntry(content="s2", memory_type=MemoryType.SEMANTIC))
        await manager.add_memory(MemoryEntry(content="e1", memory_type=MemoryType.EPISODIC))

        semantic = await manager.get_memories_by_type(MemoryType.SEMANTIC)

        assert [e.content for e in semantic] == ["s1", "s2"]

    async def test_get_important_memories_includes_threshold_boundary(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="edge", importance=0.7))
        await manager.add_memory(MemoryEntry(content="below", importance=0.69))

        important = await manager.get_important_memories(0.7)

        assert [e.content for e in important] == ["edge"]

    async def test_clear_empties_entries_patterns_and_working_memory(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="x"))
        await manager.add_pattern(SemanticPattern(name="p"))
        manager.working_set("k", "v")
        await manager.consolidate()

        await manager.clear()

        assert manager._entries == []
        assert manager._patterns == []
        assert manager.working().data == {}
        assert manager._last_consolidation is None


# ============================================================================
# 3. 搜索
# ============================================================================

class TestSearch:
    async def test_keyword_search_only_is_used_when_rag_is_disabled(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="deploy pipeline steps"))
        await manager.add_memory(MemoryEntry(content="unrelated note"))

        hits = await manager.search_memories("pipeline", use_rag=False)

        assert [e.content for e in hits] == ["deploy pipeline steps"]

    async def test_tag_only_match_is_found_when_rag_index_misses(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="完全无关的中文内容", tags=["asyncio"]))

        hits = await manager.search_memories("asyncio")

        assert [e.content for e in hits] == ["完全无关的中文内容"]

    async def test_no_match_returns_empty_list(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="alpha"))

        assert await manager.search_memories("nothing-here") == []

    async def test_results_are_sorted_by_importance_and_access_count(self, tmp_path):
        manager = _json_backend(tmp_path)
        high = MemoryEntry(content="needle high", importance=0.9)
        low = MemoryEntry(content="needle low", importance=0.1)
        await manager.add_memory(high)
        await manager.add_memory(low)

        hits = await manager.search_memories("needle", use_rag=False)

        scores = [e.importance * 0.7 + min(e.access_count * 0.1, 0.3) for e in hits]
        assert scores == sorted(scores, reverse=True)
        assert hits[0].content == "needle high"

    async def test_search_marks_hits_as_accessed(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="touched needle"))

        await manager.search_memories("needle", use_rag=False)

        assert manager._entries[0].access_count == 1


# ============================================================================
# 4. 语义模式
# ============================================================================

class TestPatterns:
    async def test_add_pattern_returns_id_and_is_retrievable(self, tmp_path):
        manager = _json_backend(tmp_path)
        pattern = SemanticPattern(name="always lint", category="quality")

        pattern_id = await manager.add_pattern(pattern)

        assert pattern_id == pattern.id
        assert manager.get_pattern(pattern_id) is pattern
        assert manager.get_pattern("missing") is None

    async def test_get_patterns_returns_a_copy(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_pattern(SemanticPattern(name="p1"))

        snapshot = manager.get_patterns()
        snapshot.append(SemanticPattern(name="injected"))

        assert [p.name for p in manager.get_patterns()] == ["p1"]


# ============================================================================
# 5. 情景记忆
# ============================================================================

class TestEpisodic:
    async def test_json_backend_saves_and_reads_episodic_memory(self, tmp_path):
        manager = _json_backend(tmp_path)
        memory = EpisodicMemory(situation="s", solution="sol", lesson="lesson-1")

        memory_id = await manager.add_episodic(memory)

        assert memory_id == memory.id
        stored = await manager.get_episodic(memory.id)
        assert stored is not None
        assert stored.lesson == "lesson-1"
        assert len(await manager.list_episodic()) == 1
        assert await manager.get_episodic("missing") is None

    async def test_sqlite_backend_saves_and_reads_episodic_memory(self, tmp_path):
        manager = _sqlite_backend(tmp_path)
        memory = EpisodicMemory(situation="s", lesson="sqlite-lesson")

        await manager.add_episodic(memory)

        stored = await manager.get_episodic(memory.id)
        assert stored is not None
        assert stored.lesson == "sqlite-lesson"
        assert [m.id for m in await manager.list_episodic()] == [memory.id]
        assert await manager.get_episodic("missing") is None

    async def test_pending_promotion_skips_tasks_without_evidence(self, tmp_path):
        manager = _json_backend(tmp_path)
        manager.working_set(
            "_pending_episodic_promotion",
            {
                "goal": "g",
                "timestamp": 1,
                "tasks": [{"task_id": "t1", "title": "no-evidence", "status": "completed"}],
            },
        )

        promoted = await manager._process_pending_episodic_promotion()

        assert promoted == 0
        assert await manager.list_episodic() == []
        assert manager.working_get("_pending_episodic_promotion") is None

    async def test_pending_promotion_builds_lesson_per_task_status(self, tmp_path):
        manager = _json_backend(tmp_path)
        manager.working_set(
            "_pending_episodic_promotion",
            {
                "goal": "目标G",
                "timestamp": 1,
                "tasks": [
                    {
                        "task_id": "t-ok",
                        "title": "完成的任务",
                        "status": "completed",
                        "evidence_paths": ["evidence/a.json"],
                        "result": "ok",
                    },
                    {
                        "task_id": "t-bad",
                        "title": "失败的任务",
                        "status": "failed",
                        "evidence_paths": ["evidence/b.json"],
                        "result": "x" * 500,
                    },
                    {
                        "task_id": "t-other",
                        "title": "未知状态",
                        "status": "skipped",
                        "evidence_paths": ["evidence/c.json"],
                        "result": "",
                    },
                ],
            },
        )

        promoted = await manager._process_pending_episodic_promotion()

        assert promoted == 3
        lessons = {m.lesson for m in await manager.list_episodic()}
        assert "任务成功完成，证据已记录" in lessons
        assert any(lesson.startswith("任务失败:") for lesson in lessons)
        assert any("skipped" in lesson for lesson in lessons)
        episodes = await manager.list_episodic()
        assert all(m.skill_used == "workflow:deliver" for m in episodes)
        assert all("evidence/" in m.solution for m in episodes)
        assert manager.working_get("_pending_episodic_promotion") is None

    async def test_pending_promotion_survives_malformed_payload(self, tmp_path, caplog):
        manager = _json_backend(tmp_path)
        manager.working_set("_pending_episodic_promotion", "not-a-dict")

        with caplog.at_level("ERROR", logger="memory.manager"):
            promoted = await manager._process_pending_episodic_promotion()

        assert promoted == 0
        assert any("处理待提升证据失败" in record.message for record in caplog.records)

    async def test_save_triggers_pending_promotion(self, tmp_path):
        manager = _json_backend(tmp_path)
        manager.working_set(
            "_pending_episodic_promotion",
            {
                "goal": "g",
                "tasks": [
                    {
                        "task_id": "t1",
                        "title": "t",
                        "status": "completed",
                        "evidence_paths": ["evidence/e.json"],
                    }
                ],
            },
        )

        await manager.save()

        assert len(await manager.list_episodic()) == 1
        assert manager.working_get("_pending_episodic_promotion") is None


# ============================================================================
# 6. 操作日志
# ============================================================================

class TestJournal:
    async def test_add_journal_is_queryable_by_task_and_agent(self, tmp_path):
        manager = _json_backend(tmp_path)
        journal = JournalEntry(agent_id="agent-1", task_id="task-1", action="run_tests")

        journal_id = await manager.add_journal(journal)

        assert journal_id == journal.id
        assert [j.id for j in await manager.get_journals_by_task("task-1")] == [journal.id]
        assert [j.id for j in await manager.get_journals_by_agent("agent-1")] == [journal.id]
        assert await manager.get_journals_by_task("other-task") == []
        assert any("run_tests" in log.content for log in manager.notepad.working_logs)

    async def test_journal_is_saved_to_sqlite_when_backend_supports_it(self, tmp_path):
        manager = _sqlite_backend(tmp_path)
        journal = JournalEntry(task_id="task-2", action="plan")

        await manager.add_journal(journal)

        assert [j.id for j in await manager.get_journals_by_task("task-2")] == [journal.id]


# ============================================================================
# 7. 工作记忆
# ============================================================================

class TestWorkingMemory:
    async def test_working_memory_set_get_and_default(self, tmp_path):
        manager = _json_backend(tmp_path)

        manager.working_set("phase", "executing")

        assert isinstance(manager.working(), WorkingMemory)
        assert manager.working().get("phase") == "executing"
        assert manager.working_get("phase") == "executing"
        assert manager.working_get("absent", "fallback") == "fallback"


# ============================================================================
# 8. 关闭重开 / 持久化往返
# ============================================================================

class TestPersistenceRoundtrip:
    async def test_json_backend_writes_all_three_files_and_reloads(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="持久化条目", memory_type=MemoryType.SEMANTIC))
        await manager.add_pattern(SemanticPattern(name="持久化模式"))
        manager.working_set("session_key", "session_value")

        await manager.save()

        memory_dir = tmp_path / "memory"
        assert (memory_dir / "entries.json").is_file()
        assert (memory_dir / "patterns.json").is_file()
        assert (memory_dir / "working.json").is_file()

        reopened = _json_backend(tmp_path)
        await reopened.initialize()

        assert [e.content for e in reopened._entries] == ["持久化条目"]
        assert [p.name for p in reopened._patterns] == ["持久化模式"]
        assert reopened.working_get("session_key") == "session_value"

    async def test_sqlite_backend_restores_working_memory_only_with_session_id(self, tmp_path):
        manager = _sqlite_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="sqlite 条目", memory_type=MemoryType.SEMANTIC))
        manager.working().session_id = "session-42"
        manager.working_set("phase", "executing")
        await manager.save()

        with_session = _sqlite_backend(tmp_path)
        await with_session.initialize(session_id="session-42")
        without_session = _sqlite_backend(tmp_path)
        await without_session.initialize()

        assert [e.content for e in with_session._entries] == ["sqlite 条目"]
        assert with_session.working_get("phase") == "executing"
        assert without_session.working().data == {}
        assert without_session.working().session_id == ""

    async def test_sqlite_semantic_patterns_reload_with_list_typed_target_skills(self, tmp_path):
        manager = _sqlite_backend(tmp_path)
        await manager.add_pattern(
            SemanticPattern(name="模式A", target_skills=["ralph_loop", "code_review"])
        )
        await manager.save()

        reopened = _sqlite_backend(tmp_path)
        await reopened.initialize()

        assert [p.name for p in reopened._patterns] == ["模式A"]
        assert reopened._patterns[0].target_skills == ["ralph_loop", "code_review"]

    async def test_sqlite_patterns_with_broken_or_null_target_skills_degrade_to_empty_list(
        self, tmp_path
    ):
        """库里存在脏数据（非 JSON 或 NULL）时不得让 initialize() 崩溃。"""
        _sqlite_backend(tmp_path)
        db_path = tmp_path / ".clawd" / "memory" / "memory_v2.db"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT OR REPLACE INTO semantic_patterns (id, name, target_skills) "
                "VALUES ('bad-json', '脏数据', '[broken')"
            )
            conn.execute(
                "INSERT OR REPLACE INTO semantic_patterns (id, name, target_skills) "
                "VALUES ('null-json', '空数据', NULL)"
            )
            conn.commit()
        finally:
            conn.close()

        reopened = _sqlite_backend(tmp_path)
        await reopened.initialize()

        by_name = {p.name: p.target_skills for p in reopened._patterns}
        assert by_name["脏数据"] == []
        assert by_name["空数据"] == []


# ============================================================================
# 9. 初始化失败降级
# ============================================================================

class TestInitializeErrorPaths:
    async def test_empty_directory_initialises_to_empty_state(self, tmp_path):
        manager = _json_backend(tmp_path)

        await manager.initialize()

        assert manager._entries == []
        assert manager._patterns == []
        assert manager.working().data == {}

    async def test_corrupted_entries_file_does_not_raise(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "entries.json").write_text("{ not json", encoding="utf-8")
        manager = _json_backend(tmp_path)

        await manager.initialize()

        assert manager._entries == []

    async def test_corrupted_patterns_file_keeps_entries_already_loaded(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "entries.json").write_text(
            json.dumps([MemoryEntry(content="已加载").to_dict()], ensure_ascii=False),
            encoding="utf-8",
        )
        (memory_dir / "patterns.json").write_text("<<<broken>>>", encoding="utf-8")
        manager = _json_backend(tmp_path)

        await manager.initialize()

        assert [e.content for e in manager._entries] == ["已加载"]
        assert manager._patterns == []


# ============================================================================
# 10. 记忆整合
# ============================================================================

class TestConsolidate:
    async def test_low_unaccessed_importance_decays_and_accessed_importance_rises(self, tmp_path):
        manager = _json_backend(tmp_path)
        decaying = MemoryEntry(content="decay", importance=0.1)
        boosted = MemoryEntry(content="boost", importance=0.5)
        boosted.access_count = 3
        boosted.access()
        capped = MemoryEntry(content="cap", importance=0.99)
        for _ in range(5):
            capped.access()
        for entry in (decaying, boosted, capped):
            manager._entries.append(entry)

        await manager.consolidate()

        assert decaying.importance == pytest.approx(0.09)
        assert boosted.importance == pytest.approx(0.5 + 0.05 * boosted.access_count)
        assert capped.importance == pytest.approx(1.0)
        assert manager._last_consolidation is not None

    async def test_pattern_confidence_only_grows_after_five_applications(self, tmp_path):
        manager = _json_backend(tmp_path)
        hot = SemanticPattern(name="hot", confidence=0.5, applications=6)
        cold = SemanticPattern(name="cold", confidence=0.5, applications=5)
        await manager.add_pattern(hot)
        await manager.add_pattern(cold)

        await manager.consolidate()

        assert hot.confidence == pytest.approx(0.55)
        assert cold.confidence == pytest.approx(0.5)

    async def test_consolidate_promotes_proposals_and_clears_them(self, tmp_path):
        from src.memory.evolution import MemoryKind, MemoryProposal

        manager = _json_backend(tmp_path)
        manager.working_set(
            "memory_proposals",
            [
                MemoryProposal(
                    kind=MemoryKind.FACT,
                    statement="Python 3.11 支持异常组",
                    selectors={"lang": "python"},
                )
            ],
        )

        await manager.consolidate()

        promoted = [e for e in manager._entries if e.memory_type == MemoryType.SEMANTIC]
        assert len(promoted) == 1
        assert promoted[0].content.startswith("[FACT] Python 3.11")
        assert promoted[0].importance == pytest.approx(0.8)
        assert promoted[0].tags == ["python"]
        assert manager.working_get("memory_proposals") == []

    async def test_consolidate_persists_state_to_disk(self, tmp_path):
        manager = _json_backend(tmp_path)
        manager._entries.append(MemoryEntry(content="已整合", importance=0.4))

        await manager.consolidate()

        on_disk = json.loads(
            (tmp_path / "memory" / "entries.json").read_text(encoding="utf-8")
        )
        assert [entry["content"] for entry in on_disk] == ["已整合"]


# ============================================================================
# 11. 状态统计
# ============================================================================

class TestStatus:
    async def test_json_backend_status_counts_entries_patterns_and_size(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="s", memory_type=MemoryType.SEMANTIC))
        await manager.add_memory(MemoryEntry(content="w", memory_type=MemoryType.WORKING))
        await manager.add_pattern(SemanticPattern(name="p"))
        await manager.save()

        status = await manager.get_status()

        assert status.total_memories == 2
        assert status.semantic_count == 1
        assert status.working_count == 1
        assert status.pattern_count == 1
        assert status.storage_size_bytes > 0
        assert status.last_consolidation is None

    async def test_sqlite_backend_status_uses_database_file_size(self, tmp_path):
        manager = _sqlite_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="s", memory_type=MemoryType.SEMANTIC))
        await manager.add_episodic(EpisodicMemory(situation="s", lesson="l"))
        await manager.save()

        status = await manager.get_status()

        db_path = tmp_path / ".clawd" / "memory" / "memory_v2.db"
        assert status.total_memories == 1
        assert status.semantic_count == 1
        # 情景记忆存放在独立表，不计入 _entries
        assert status.episodic_count == 0
        assert status.storage_size_bytes == db_path.stat().st_size
        assert status.storage_size_bytes > 0


# ============================================================================
# 12. 导出 / 导入
# ============================================================================

class TestExportImport:
    async def test_export_writes_utf8_json_with_all_sections(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="中文内容", memory_type=MemoryType.SEMANTIC))
        await manager.add_pattern(SemanticPattern(name="模式"))
        await manager.add_episodic(EpisodicMemory(lesson="教训"))
        manager.working_set("k", "v")
        output = tmp_path / "export.json"

        await manager.export(output)

        data = json.loads(output.read_text(encoding="utf-8"))
        assert set(data) == {"entries", "patterns", "episodic", "working"}
        assert data["entries"][0]["content"] == "中文内容"
        assert data["patterns"][0]["name"] == "模式"
        assert data["episodic"][0]["lesson"] == "教训"
        assert data["working"] == {"k": "v"}

    async def test_export_import_roundtrip_on_chinese_content(self, tmp_path):
        source = _json_backend(tmp_path)
        await source.add_memory(MemoryEntry(content="中文记忆内容", memory_type=MemoryType.SEMANTIC))
        await source.add_pattern(SemanticPattern(name="中文模式"))
        output = tmp_path / "dump.json"
        await source.export(output)

        target = MemoryManager(memory_dir=tmp_path / "restored", use_sqlite=False)
        imported = await target.import_memories(output)

        assert imported == 2
        assert [e.content for e in target._entries] == ["中文记忆内容"]
        assert [p.name for p in target._patterns] == ["中文模式"]

    async def test_import_missing_file_raises(self, tmp_path):
        manager = _json_backend(tmp_path)

        with pytest.raises(FileNotFoundError):
            await manager.import_memories(tmp_path / "no-such-dump.json")


# ============================================================================
# 13. Memory Seed & Promote（GoalX）
# ============================================================================

class TestSeedAndPromote:
    async def test_seed_memory_marks_entry_and_is_queryable_by_project(self, tmp_path):
        manager = _json_backend(tmp_path)

        seed_id = await manager.seed_memory("proj-1", "项目规范: 用 ruff")

        entry = await manager.get_memory(seed_id)
        assert entry is not None
        assert entry.tags == ["seed", "core_knowledge"]
        assert entry.selectors == {"project_id": "proj-1"}
        assert entry.metadata["is_seed"] is True
        assert "seeded_at" in entry.metadata
        assert [e.id for e in await manager.get_project_seed_memories("proj-1")] == [seed_id]
        assert await manager.get_project_seed_memories("proj-2") == []

    async def test_promote_unknown_memory_returns_false(self, tmp_path):
        manager = _json_backend(tmp_path)

        assert await manager.promote_to_long_term("missing") is False

    async def test_promote_episodic_memory_creates_semantic_copy(self, tmp_path):
        manager = _json_backend(tmp_path)
        original = MemoryEntry(
            content="可复用的经验",
            memory_type=MemoryType.EPISODIC,
            importance=0.5,
            tags=["tag-a"],
            selectors={"tool": "pytest"},
        )
        await manager.add_memory(original)

        assert await manager.promote_to_long_term(original.id, "反复验证有效") is True

        promoted = [e for e in manager._entries if e.id != original.id]
        assert len(promoted) == 1
        entry = promoted[0]
        assert entry.memory_type == MemoryType.SEMANTIC
        assert entry.importance == pytest.approx(0.7)
        assert "promoted" in entry.tags
        assert "promoted_from_episodic" in entry.tags
        assert entry.selectors == {"tool": "pytest"}
        assert entry.metadata["promoted_from_id"] == original.id
        assert entry.metadata["promoted_reason"] == "反复验证有效"
        assert "promoted_at" in entry.metadata
        assert original.metadata["promoted"] is True

    async def test_promote_caps_importance_at_one(self, tmp_path):
        manager = _json_backend(tmp_path)
        original = MemoryEntry(
            content="几乎满分", memory_type=MemoryType.SEMANTIC, importance=0.95
        )
        await manager.add_memory(original)

        await manager.promote_to_long_term(original.id)

        promoted = next(e for e in manager._entries if e.id != original.id)
        assert promoted.importance == pytest.approx(1.0)
        # 非情景记忆不被标记为已晋升
        assert "promoted" not in original.metadata


# ============================================================================
# 14. 相似经验检索
# ============================================================================

class TestRetrieveSimilarExperiences:
    async def test_returns_episodic_memories_linked_to_matching_semantic_entry(self, tmp_path):
        manager = _json_backend(tmp_path)
        semantic = MemoryEntry(content="subprocess timeout 处理", memory_type=MemoryType.SEMANTIC)
        await manager.add_memory(semantic)
        linked = EpisodicMemory(situation="超时", lesson="加超时", related_pattern_id=semantic.id)
        unlinked = EpisodicMemory(situation="无关", lesson="无关", related_pattern_id="other")
        await manager.add_episodic(linked)
        await manager.add_episodic(unlinked)

        results = await manager.retrieve_similar_experiences("subprocess")

        assert [m.id for m in results] == [linked.id]

    async def test_returns_empty_when_nothing_matches(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="alpha"))

        assert await manager.retrieve_similar_experiences("zzz") == []

    async def test_respects_limit(self, tmp_path):
        manager = _json_backend(tmp_path)
        first = MemoryEntry(content="tuning needle one", importance=0.9)
        second = MemoryEntry(content="tuning needle two", importance=0.8)
        await manager.add_memory(first)
        await manager.add_memory(second)
        for owner in (first, second):
            await manager.add_episodic(
                EpisodicMemory(situation="s", lesson="l", related_pattern_id=owner.id)
            )

        assert len(await manager.retrieve_similar_experiences("needle", limit=1)) == 1


# ============================================================================
# 15. 并发写入
# ============================================================================

class TestConcurrentWrites:
    async def test_concurrent_add_and_save_persists_every_entry(self, tmp_path):
        manager = _json_backend(tmp_path)
        entries = [
            MemoryEntry(content=f"并发条目 {i}", memory_type=MemoryType.SEMANTIC)
            for i in range(20)
        ]

        await asyncio.gather(*(manager.add_memory(entry) for entry in entries))
        await manager.save()

        reopened = _json_backend(tmp_path)
        await reopened.initialize()

        assert len(manager._entries) == 20
        assert len({e.id for e in manager._entries}) == 20
        assert len(reopened._entries) == 20
        assert {e.content for e in reopened._entries} == {f"并发条目 {i}" for i in range(20)}

    async def test_concurrent_saves_leave_readable_files(self, tmp_path):
        manager = _json_backend(tmp_path)
        await manager.add_memory(MemoryEntry(content="重复保存"))

        await asyncio.gather(*(manager.save() for _ in range(5)))

        data = json.loads((tmp_path / "memory" / "entries.json").read_text(encoding="utf-8"))
        assert [entry["content"] for entry in data] == ["重复保存"]
