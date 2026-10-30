"""笔记本（Pi 原语）+ 压缩准入阈值（Pi handoff eligibility）测试"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.compaction import (
    MIN_COMPACT_TOKENS,
    estimate_context_tokens,
    format_context_usage,
    is_compaction_eligible,
)
from src.memory.notebook import Notebook, format_page_preview, normalize_topic
from src.tools_runtime.notebook_tool import NotebookTool

# ==========================================================================
# Pi handoff 准入判断
# ==========================================================================


class TestCompactionEligibility:
    def test_too_small_context_is_not_eligible(self):
        """Pi 的核心洞见：上下文太小，压缩是净损失"""
        assert is_compaction_eligible(tokens=5_000) is False
        assert is_compaction_eligible(tokens=MIN_COMPACT_TOKENS - 1) is False

    def test_large_context_is_eligible(self):
        assert is_compaction_eligible(tokens=MIN_COMPACT_TOKENS) is True
        assert is_compaction_eligible(tokens=100_000) is True

    def test_estimates_from_percent_and_window(self):
        assert estimate_context_tokens(percent=50, context_window=100_000) == 50_000
        assert is_compaction_eligible(percent=50, context_window=100_000) is True
        assert is_compaction_eligible(percent=10, context_window=100_000) is False

    def test_unknown_usage_is_not_eligible(self):
        assert estimate_context_tokens() is None
        assert is_compaction_eligible() is False
        assert "未知" in format_context_usage()

    def test_exact_tokens_preferred_over_estimate(self):
        assert estimate_context_tokens(tokens=1234, percent=99, context_window=1_000_000) == 1234

    def test_format_usage_is_honest(self):
        assert format_context_usage(tokens=8000) == "8000 tokens"
        assert "估算" in format_context_usage(percent=20, context_window=50_000)


# ==========================================================================
# 笔记本数据模型
# ==========================================================================


class TestNotebookModel:
    def test_normalize_topic_matches_pi_rules(self):
        assert normalize_topic("API Design!") == "api-design"
        assert normalize_topic("  多 空格  ") == ""  # 非 ASCII 归一化为空
        assert normalize_topic("a" * 200) == "a" * 80  # 长度上限

    def test_preview_truncates(self):
        assert format_page_preview("x" * 100).endswith("…")
        assert len(format_page_preview("x" * 100)) == 80

    def test_save_and_read_roundtrip(self, tmp_path: Path):
        nb = Notebook(tmp_path)
        slug = nb.save_page("API Design", "统一用 REST，错误码 E4xxx")

        assert slug == "api-design"
        assert "E4xxx" in (nb.read_page("api-design") or "")
        assert nb.read_page("missing") is None

    def test_list_pages_sorted_by_update(self, tmp_path: Path):
        nb = Notebook(tmp_path)
        nb.save_page("first", "a")
        nb.save_page("second", "b")

        pages = nb.list_pages()

        assert {p["topic"] for p in pages} == {"first", "second"}
        assert all("preview" in p for p in pages)

    def test_empty_notebook_message(self, tmp_path: Path):
        assert "空" in Notebook(tmp_path).format_page_list()

    def test_invalid_topic_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="主题名无效"):
            Notebook(tmp_path).save_page("   ", "x")


class TestActiveTopicBoundaryHint:
    def test_first_set_has_no_boundary(self, tmp_path: Path):
        result = Notebook(tmp_path).set_active_topic("auth")
        assert result["changed"] is True
        assert result["boundary_hint"] is None

    def test_switch_produces_boundary_hint(self, tmp_path: Path):
        nb = Notebook(tmp_path)
        nb.set_active_topic("auth")
        result = nb.set_active_topic("payment")

        assert result["changed"] is True
        assert result["boundary_hint"]["from"] == "auth"
        assert result["boundary_hint"]["to"] == "payment"
        assert "切换" in result["boundary_hint"]["hint"]

    def test_same_topic_no_hint(self, tmp_path: Path):
        nb = Notebook(tmp_path)
        nb.set_active_topic("auth")
        result = nb.set_active_topic("auth")
        assert result["changed"] is False
        assert result["boundary_hint"] is None


class TestTwoPhaseDiscard:
    """Pi 的安全删除模型：prepare 不删，commit 才删"""

    def test_prepare_does_not_delete_files(self, tmp_path: Path):
        nb = Notebook(tmp_path)
        nb.save_page("old-a", "内容 A")
        nb.save_page("old-b", "内容 B")

        plan = nb.prepare_discard(["old-a", "old-b"])

        assert plan.topics == ["old-a", "old-b"]
        assert nb.read_page("old-a") == "内容 A\n"      # 文件还在
        assert plan.snapshot["old-a"].startswith("内容 A")

    def test_commit_deletes_after_success(self, tmp_path: Path):
        nb = Notebook(tmp_path)
        nb.save_page("old-a", "内容 A")
        plan = nb.prepare_discard(["old-a"])

        removed = nb.commit_discard(plan.token)

        assert removed == ["old-a"]
        assert nb.read_page("old-a") is None
        assert nb.list_pages() == []

    def test_abort_keeps_files(self, tmp_path: Path):
        nb = Notebook(tmp_path)
        nb.save_page("keep-me", "重要")
        plan = nb.prepare_discard(["keep-me"])

        nb.abort_discard(plan.token)

        assert nb.read_page("keep-me") == "重要\n"
        assert plan.token not in nb.pending_plans()

    def test_commit_unknown_token_is_explicit(self, tmp_path: Path):
        with pytest.raises(KeyError, match="未知的删除计划"):
            Notebook(tmp_path).commit_discard("nope")

    def test_prepare_ignores_missing_topics(self, tmp_path: Path):
        nb = Notebook(tmp_path)
        nb.save_page("exists", "x")

        plan = nb.prepare_discard(["exists", "ghost"])

        assert plan.topics == ["exists"]


# ==========================================================================
# 工具层
# ==========================================================================


class TestNotebookTool:
    def test_save_read_list_via_tool(self, tmp_path: Path):
        tool = NotebookTool(tmp_path)

        saved = tool.execute(action="save", topic="plan", content="先做 A 再做 B")
        assert saved.success is True, saved.error

        read = tool.execute(action="read", topic="plan")
        assert "先做 A" in read.output

        listed = tool.execute(action="list")
        assert listed.success is True
        assert listed.metadata["count"] == 1

    def test_save_requires_content(self, tmp_path: Path):
        result = NotebookTool(tmp_path).execute(action="save", topic="x", content="")
        assert result.success is False
        assert "content" in result.error

    def test_two_phase_discard_via_tool(self, tmp_path: Path):
        tool = NotebookTool(tmp_path)
        tool.execute(action="save", topic="tmp-page", content="临时")

        prepared = tool.execute(action="prepare_discard", topics=["tmp-page"])
        assert prepared.success is True
        token = prepared.metadata["token"]
        assert tool.execute(action="read", topic="tmp-page").success is True  # 还没删

        committed = tool.execute(action="commit_discard", token=token)
        assert committed.success is True
        assert tool.execute(action="read", topic="tmp-page").success is False  # 已删

    def test_unknown_action_explicit(self, tmp_path: Path):
        result = NotebookTool(tmp_path).execute(action="bogus")
        assert result.success is False
        assert "未知 action" in result.error

    def test_risk_kind_requires_approval(self):
        assert NotebookTool.risk_kind == "write"

    def test_engine_registers_notebook_tool(self, tmp_path: Path):
        import asyncio

        from src.agent.engine import AgentEngine

        engine = AgentEngine(workdir=tmp_path)
        asyncio.run(engine._load_extended_tools())

        assert "NotebookTool" in engine.tools
        assert "LSPTool" in engine.tools
