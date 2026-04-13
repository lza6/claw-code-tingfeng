"""Tests for RTK-style integration features:
- Token tracker (token_tracker.py)
- Output compressor (output_compressor.py)
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Token Tracker Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def tracker(tmp_path: Path):
    """Temporary TokenTracker instance"""
    from src.core.token_tracker import TokenTracker
    db = tmp_path / "tracker.db"
    t = TokenTracker(db_path=db)
    t.init()
    return t


class TestTokenTracker:
    def test_record_and_summary(self, tracker):
        tracker.record("BashTool", raw_tokens=1000, compressed_tokens=400, command="git status")
        summary = tracker.get_summary(days=30)
        assert summary["total_records"] == 1
        assert summary["total_saved_tokens"] == 600
        assert summary["avg_savings_pct"] == 60.0

    def test_record_multiple(self, tracker):
        tracker.record("BashTool", raw_tokens=1000, compressed_tokens=300, command="git log")
        tracker.record("FileReadTool", raw_tokens=500, compressed_tokens=400, command="read src/main.py")
        summary = tracker.get_summary(days=30)
        assert summary["total_records"] == 2
        assert summary["total_saved_tokens"] == 800

    def test_tool_breakdown(self, tracker):
        for _ in range(3):
            tracker.record("BashTool", raw_tokens=1000, compressed_tokens=200)
        tracker.record("FileReadTool", raw_tokens=500, compressed_tokens=500)

        breakdown = tracker.get_tool_breakdown(days=30)
        assert len(breakdown) == 2
        bash = next(b for b in breakdown if b["tool_name"] == "BashTool")
        assert bash["records"] == 3
        assert bash["saved_tokens"] == 2400  # 3 * (1000-200)

    def test_daily_breakdown(self, tracker):
        tracker.record("BashTool", raw_tokens=800, compressed_tokens=200)
        daily = tracker.get_daily_breakdown(days=7)
        assert len(daily) >= 1
        today = daily[-1]
        assert today["records"] == 1
        assert today["saved_tokens"] == 600

    def test_ascii_chart(self, tracker):
        tracker.record("BashTool", raw_tokens=1000, compressed_tokens=100)
        chart = tracker.get_ascii_chart(days=7)
        assert "token 节省趋势" in chart
        assert "1,000" in chart or "900" in chart

    def test_project_path_filter(self, tracker):
        tracker.record("BashTool", raw_tokens=1000, project_path="/projectA")
        tracker.record("BashTool", raw_tokens=800, project_path="/projectB")
        summary_a = tracker.get_summary(project_path="/projectA")
        summary_b = tracker.get_summary(project_path="/projectB")
        assert summary_a["total_records"] == 1
        assert summary_b["total_records"] == 1

    def test_empty_summary(self, tracker):
        summary = tracker.get_summary(days=30)
        assert summary["total_records"] == 0
        assert summary["avg_savings_pct"] == 0.0

    def test_cleanup_removes_records(self, tracker):
        tracker.record("BashTool", raw_tokens=100, compressed_tokens=50)
        before = tracker.get_summary(days=30)
        assert before["total_records"] == 1
        # Manually set a very old timestamp
        import sqlite3
        with tracker._connect() as conn:
            conn.execute(
                "UPDATE tracking_records SET timestamp = datetime('now', '-100 days')"
            )
        tracker.cleanup(days=90)
        after = tracker.get_summary(days=120)  # wide window
        # Record should have been cleaned up
        assert after["total_records"] == 0

    def test_savings_pct_on_zero_raw(self, tracker):
        tracker.record("BashTool", raw_tokens=0, compressed_tokens=0)
        summary = tracker.get_summary(days=30)
        assert summary["avg_savings_pct"] == 0.0

    def test_history(self, tracker):
        tracker.record("BashTool", raw_tokens=100, compressed_tokens=50, command="git status")
        hist = tracker.get_history(limit=10)
        assert len(hist) == 1
        assert hist[0].command == "git status"
        assert hist[0].saved_tokens == 50
        assert hist[0].savings_pct == 50.0

    def test_report_format(self, tracker):
        tracker.record("BashTool", raw_tokens=1000, compressed_tokens=300, command="git log")
        report = tracker.get_report(days=30)
        assert "Token 节省报告" in report
        assert "按工具分类" in report
        assert "git log" in report or "BashTool" in report


# ---------------------------------------------------------------------------
# Output Compressor Tests
# ---------------------------------------------------------------------------


class TestOutputCompressor:
    def test_truncate_strategy(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        big = "line\n" * 600
        result = compressor._truncate(big, {"max_lines": 100, "max_chars": 50000})
        assert "lines omitted" in result
        # Should have fewer lines than original
        assert result.count("\n") < big.count("\n")

    def test_error_only_strategy(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        output = "OK\nOK\nWarning: deprecated\nOK\nError: connection failed\nOK"
        result = compressor._error_only(output, {})
        assert "Error" in result
        assert "Warning" in result
        # Should NOT contain clean "OK" lines (they don't match error patterns)
        assert "OK" not in result or result.count("OK") == 0

    def test_error_no_errors(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        result = compressor._error_only("All tests passed\nOK\nDone", {})
        assert "(no errors" in result

    def test_deduplication(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        output = "a\na\na\nb\nb\nc"
        result = compressor._deduplication(output, {})
        assert "repeated 3 times" in result
        assert "repeated 2 times" in result

    def test_compress_git_status(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        raw = "On branch main\nYour branch is up to date with 'origin/main'.\n\nnothing to commit, working tree clean\n"
        result = compressor.compress("git status", raw)
        # 匹配新行为: 'ok (clean)'
        assert "ok" in result.lower() or "branch" in result.lower()

    def test_compress_unknown_command_returns_truncated(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        big = "x\n" * 1000
        result = compressor.compress("unknown_cmd", big)
        # Unknown commands match DEFAULT_FILTER which has max_lines=500 and max_chars=20000
        assert len(result) <= len(big)
        # Should produce some output
        assert len(result) > 0

    def test_compress_empty_output(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        assert compressor.compress("anything", "") == ""

    def test_estimate_savings(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        big = "line of text\n" * 500
        result = compressor.estimate_savings("git log", big)
        assert "original_chars" in result
        assert "compressed_chars" in result
        assert "savings_pct" in result
        assert "strategy" in result

    def test_load_rules_from_file(self):
        from src.core.output_compressor import OutputCompressor, FilterRule
        compressor = OutputCompressor()

        # Use existing filter files
        filters_dir = Path(__file__).parent.parent / "src" / "core" / "filters"
        for json_file in filters_dir.glob("*.json"):
            count = compressor.load_rules_from_file(json_file)
            assert count > 0

    def test_progress_filter(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        # Progress lines include Downloading, percentage bars, etc.
        output = (
            "Collecting flask\n"
            "  Downloading flask-2.0.0.tar.gz\n"
            "  [====>     ] 45%\n"
            "Successfully installed flask-2.0.0"
        )
        result = compressor._progress_filter(output, {})
        assert "Successfully installed flask-2.0.0" in result

    def test_failure_focus(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        output = (
            "test_one ... PASSED\n"
            "test_two ... FAILED\n"
            "AssertionError: expected True\n"
            "test_three ... PASSED\n"
            "FAILED (failures=1)\n"
        )
        result = compressor._failure_focus(output, {})
        assert "FAILED" in result
        assert "AssertionError" in result
        assert "PASSED" not in result or output.count("PASSED") <= result.count("PASSED")

    def test_match_rule_returns_default(self):
        from src.core.output_compressor import OutputCompressor, DEFAULT_FILTER, FilterStrategy
        compressor = OutputCompressor()
        rule = compressor.match_rule("some_obscure_command")
        # Should return default truncate for unknown commands
        assert rule.strategy == FilterStrategy.TRUNCATE

    def test_filter_rule_dataclass(self):
        from src.core.output_compressor import FilterRule, FilterStrategy
        rule = FilterRule(
            name="test_rule",
            command_pattern=r"^test",
            strategy=FilterStrategy.TRUNCATE,
            params={"max_lines": 10},
        )
        assert rule.name == "test_rule"
        assert rule.params["max_lines"] == 10

    def test_json_summary(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        data = {"key1": "value1", "key2": 42}
        result = compressor._json_summary(data)
        assert "key1" in result
        assert "key2" in result

    def test_ascii_chart_no_data(self):
        from src.core.token_tracker import TokenTracker
        with tempfile.TemporaryDirectory() as tmp:
            tracker = TokenTracker(db_path=Path(tmp) / "tracker.db")
            tracker.init()
            chart = tracker.get_ascii_chart(days=7)
            assert "暂无数据" in chart

    def test_git_log_condensed(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        raw = (
            "commit abcdef1234567890\n"
            "Author: test-user <test@example.com>\n"
            "Date:   Mon Jan 1 00:00:00 2025\n"
            "\n"
            "    Initial commit\n"
            "\n"
            "commit bbbbbbb1234567890\n"
            "Author: another <another@example.com>\n"
            "Date:   Tue Jan 2 00:00:00 2025\n"
            "\n"
            "    Fix a bug\n"
        )
        result = compressor._git_log_condensed(raw, {"max_lines": 30})
        assert "commit abcdef" in result
        assert "Initial commit" in result

    def test_tree_compression(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        # Tree with nested dirs (tree compression uses │ count for depth)
        raw = "src/\n│\n│ ├── core/\n│ │ ├── __init__.py\n│ │ └── main.py\n│ │ └── deep/\n│ │   └── nested.py\n├── tests/\n│ └── test_main.py\nREADME.md"
        result = compressor._tree_compression(raw, {"max_depth": 2})
        # Should either contain truncated marker or be shorter
        assert "src/" in result
        assert len(result) <= len(raw)

    def test_grouping_strategy(self):
        from src.core.output_compressor import OutputCompressor
        compressor = OutputCompressor()
        output = "file1.py:10 error\nfile2.py:20 error\nfile1.py:30 error\nfile1.py:40 error"
        result = compressor._error_only(output, {"group_by_file": True})
        assert "file1.py" in result
        assert "file2.py" in result
