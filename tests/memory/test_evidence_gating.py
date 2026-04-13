"""
Evidence Gating Tests - 记忆演进中的证据门控
"""

import pytest
from unittest.mock import MagicMock
from src.memory.evolution import (
    MemoryEvolver,
    MemoryProposal,
    MemoryEvidence,
    MemoryKind,
    MemoryEntry,
    VerificationLevel
)


class TestMemoryEvidence:
    """测试证据门控功能"""

    def test_proposal_add_evidence(self):
        """测试添加证据到提案"""
        proposal = MemoryProposal(
            kind=MemoryKind.FACT,
            statement="Python tests run with pytest",
            selectors={"lang": "python"}
        )

        proposal.add_evidence("run-1", "pytest output", kind="test_result")
        assert len(proposal.evidence) == 1
        assert proposal.evidence[0].run_id == "run-1"
        assert proposal.evidence[0].kind == "test_result"
        assert "run-1" in proposal.source_runs

    def test_proposal_evidence_dedup(self):
        """测试不重复添加证据"""
        proposal = MemoryProposal(
            kind=MemoryKind.PROCEDURE,
            statement="Always run lint before commit",
            selectors={}
        )

        proposal.add_evidence("run-1", "Test 1")
        proposal.add_evidence("run-1", "Test 2")  # Same run, different content

        assert len(proposal.evidence) == 2
        assert len(proposal.source_runs) == 1  # Should deduplicate source_runs


class TestEvidenceGating:
    """测试证据门控逻辑"""

    def test_fact_promotion_always(self):
        """测试事实类记忆无条件晋升"""
        evolver = MemoryEvolver(MagicMock())

        proposal = MemoryProposal(
            kind=MemoryKind.FACT,
            statement="Port 8080 is used for API",
            selectors={"module": "network"}
        )
        proposal.add_evidence("run-1", "Found in code", kind="observation")

        entries = evolver.aggregate_proposals([proposal])
        assert len(entries) == 1
        assert entries[0].verification == VerificationLevel.VALIDATED

    def test_procedure_requires_runs(self):
        """测试过程类记忆需要多次运行才能晋升"""
        evolver = MemoryEvolver(MagicMock())

        # 只有 1 次运行的提案不应晋升
        proposal1 = MemoryProposal(
            kind=MemoryKind.PROCEDURE,
            statement="Run format before commit",
            selectors={}
        )
        proposal1.add_evidence("run-1", "Test 1")

        entries = evolver.aggregate_proposals([proposal1])
        assert len(entries) == 0  # Not promotable yet

    def test_procedure_promotes_with_multiple_runs(self):
        """测试过程类记忆在多次运行后晋升"""
        evolver = MemoryEvolver(MagicMock())

        # 创建 2 次独立运行的相同提案
        proposal1 = MemoryProposal(
            kind=MemoryKind.PROCEDURE,
            statement="Run format before commit",
            selectors={}
        )
        proposal1.add_evidence("run-1", "Test 1")
        proposal1.source_runs.append("run-1")

        proposal2 = MemoryProposal(
            kind=MemoryKind.PROCEDURE,
            statement="Run format before commit",
            selectors={}
        )
        proposal2.add_evidence("run-2", "Test 2")
        proposal2.source_runs.append("run-2")

        entries = evolver.aggregate_proposals([proposal1, proposal2])
        assert len(entries) == 1
        entry = entries[0]
        # 2 runs -> REPEATED
        assert entry.verification == VerificationLevel.REPEATED

    def test_pitfall_requires_3_runs_or_strong_evidence(self):
        """测试陷阱类记忆需要 3 次运行或强证据"""
        evolver = MemoryEvolver(MagicMock())

        # 1 次运行，3 条证据 -> 应晋升
        proposal = MemoryProposal(
            kind=MemoryKind.PITFALL,
            statement="Avoid using bare except",
            selectors={}
        )
        proposal.add_evidence("run-1", "Evidence 1")
        proposal.add_evidence("run-1", "Evidence 2")
        proposal.add_evidence("run-1", "Evidence 3")

        entries = evolver.aggregate_proposals([proposal])
        assert len(entries) == 1

    def test_rejected_proposals_skipped(self):
        """测试被拒绝的提案不会被聚合"""
        evolver = MemoryEvolver(MagicMock())

        proposal = MemoryProposal(
            kind=MemoryKind.FACT,
            statement="This is false",
            selectors={}
        )
        proposal.state = "rejected"

        entries = evolver.aggregate_proposals([proposal])
        assert len(entries) == 0

    def test_entry_verification_level(self):
        """测试验证级别计算"""
        evolver = MemoryEvolver(MagicMock())

        proposal = MemoryProposal(
            kind=MemoryKind.SUCCESS_PRIOR,
            statement="Used fast algorithm X",
            selectors={}
        )
        # 3 次独立运行
        for i in range(3):
            proposal.source_runs.append(f"run-{i}")

        entries = evolver.aggregate_proposals([proposal])
        assert len(entries) == 1
        assert entries[0].verification == VerificationLevel.VALIDATED
