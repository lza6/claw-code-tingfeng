"""质量门聚合结论测试（回归：`overall` 曾只看第 1 项）

原实现 `return self.results[0].result` —— 第 2 项之后无论怎么失败，`must_block()`
都判放行。这里用最小的手搓结果集直接断言聚合语义，不跑真实 ruff/mypy。
"""

from __future__ import annotations

from pathlib import Path

from src.core.quality_gate import (
    GateCheck,
    GateCheckResult,
    GateLevel,
    GateResult,
    QualityGate,
)


def _check(name: str) -> GateCheck:
    return GateCheck(name=name, command=["true"], level=GateLevel.COMMIT)


def _result(name: str, result: GateResult) -> GateCheckResult:
    return GateCheckResult(check=_check(name), result=result)


class TestOverallAggregation:
    def test_first_pass_second_fail_blocks(self):
        gate = QualityGate(Path("."), GateLevel.COMMIT)
        gate.results = [
            _result("format", GateResult.PASS),
            _result("lint", GateResult.FAIL),
        ]
        assert gate.overall == GateResult.FAIL
        assert gate.must_block() is True

    def test_fail_in_middle_detected(self):
        gate = QualityGate(Path("."), GateLevel.PHASE)
        gate.results = [
            _result("a", GateResult.PASS),
            _result("b", GateResult.FAIL),
            _result("c", GateResult.PASS),
        ]
        assert gate.must_block() is True

    def test_all_pass_passes(self):
        gate = QualityGate(Path("."), GateLevel.COMMIT)
        gate.results = [_result("a", GateResult.PASS), _result("b", GateResult.PASS)]
        assert gate.overall == GateResult.PASS
        assert gate.must_block() is False

    def test_warn_blocks_only_in_strict(self):
        failing_warn = [_result("a", GateResult.PASS), _result("b", GateResult.WARN)]

        lenient = QualityGate(Path("."), GateLevel.COMMIT, strict=False)
        lenient.results = list(failing_warn)
        assert lenient.overall == GateResult.PASS

        strict = QualityGate(Path("."), GateLevel.COMMIT, strict=True)
        strict.results = list(failing_warn)
        assert strict.overall == GateResult.WARN

    def test_empty_results_do_not_block(self):
        gate = QualityGate(Path("."), GateLevel.COMMIT)
        assert gate.results == []
        assert gate.overall == GateResult.PASS
        assert gate.must_block() is False

    def test_skip_alone_does_not_block(self):
        gate = QualityGate(Path("."), GateLevel.COMMIT)
        gate.results = [_result("a", GateResult.SKIP)]
        assert gate.must_block() is False
