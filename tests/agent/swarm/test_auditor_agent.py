"""`AuditorAgent` 的审计规则与报告契约测试。

被测单元是**审计规则本身**：每条规则在什么输入下产出什么 level/category 的
finding，以及审计结论（`passed`）如何由 finding 的最严重级别推导。

LLM 辅助审查（`_llm_assist`）与视觉审计（`_check_visual`）都会调用外部能力，
因此分别用 fake engine / fake VisualVerifier 固定它们的契约，
覆盖 success / 拒绝 / 抛异常三条分支。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.agent.swarm.auditor import (
    AuditFinding,
    AuditorAgent,
    AuditReport,
)
from src.agent.swarm.message_bus import AgentMessage, MessageBus, MessageType


class FakeEngine:
    """最小 AgentEngine 契约：只提供 `run()`，返回固定 final_result。"""

    def __init__(self, final_result: str = "无问题") -> None:
        self.final_result = final_result
        self.prompts: list[str] = []
        self.raises: Exception | None = None

    async def run(self, prompt: str) -> Any:
        self.prompts.append(prompt)
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(final_result=self.final_result)


@pytest.fixture
def bus() -> MessageBus:
    return MessageBus()


@pytest.fixture
def auditor(bus: MessageBus, tmp_path: Path) -> AuditorAgent:
    agent = AuditorAgent("auditor-1", bus, workdir=tmp_path)
    agent._engine = FakeEngine()  # 隔离真实 LLM
    return agent


def findings_of(findings: list[AuditFinding], category: str) -> list[AuditFinding]:
    return [f for f in findings if f.category == category]


# ==========================================================================
# 数据类契约
# ==========================================================================


class TestAuditReportModel:
    def test_counts_by_severity(self):
        report = AuditReport(
            passed=False,
            findings=[
                AuditFinding("critical", "syntax", "a.py", 1, "x"),
                AuditFinding("critical", "security", "a.py", 2, "x"),
                AuditFinding("high", "security", "a.py", 3, "x"),
                AuditFinding("medium", "convention", "a.py", 4, "x"),
            ],
        )

        assert report.critical_count == 2
        assert report.high_count == 1

    def test_markdown_contains_findings_and_suggestions(self):
        report = AuditReport(
            passed=False,
            findings=[
                AuditFinding(
                    "critical",
                    "security",
                    "src/a.py",
                    7,
                    "使用了不安全的 eval/exec",
                    suggestion="改用 ast.literal_eval",
                )
            ],
            warnings=["无测试文件"],
            summary="发现 1 个问题",
        )

        md = report.to_markdown()

        assert "**结果**: 驳回" in md
        assert "**严重问题**: 1" in md
        assert "- **[CRITICAL]** `src/a.py:7` - 使用了不安全的 eval/exec" in md
        assert "建议: 改用 ast.literal_eval" in md
        assert "## 警告" in md
        assert "- 无测试文件" in md
        assert "## 摘要" in md

    def test_markdown_without_findings_or_warnings(self):
        md = AuditReport(passed=True).to_markdown()

        assert "**结果**: 通过" in md
        assert "## 问题列表" not in md
        assert "## 警告" not in md
        assert "## 摘要" not in md


# ==========================================================================
# 规则：语法
# ==========================================================================


class TestSyntaxRule:
    def test_syntax_error_is_critical_and_reports_real_line(self, auditor):
        findings = auditor._check_syntax("bad.py", "def f(:\n    pass\n")

        assert len(findings) == 1
        assert findings[0].severity == "critical"
        assert findings[0].category == "syntax"
        assert findings[0].line == 1
        assert "语法错误" in findings[0].description

    def test_valid_python_has_no_findings(self, auditor):
        assert auditor._check_syntax("ok.py", "x = 1\n") == []

    def test_non_python_file_is_skipped(self, auditor):
        assert auditor._check_syntax("a.js", "function f({") == []


# ==========================================================================
# 规则：安全
# ==========================================================================


class TestSecurityRule:
    def test_eval_usage_is_critical(self, auditor):
        findings = auditor._check_security("a.py", "result = eval(user_input)\n")

        assert [f.severity for f in findings] == ["critical"]
        assert findings[0].line == 1
        assert "eval/exec" in findings[0].description
        assert findings[0].code_snippet == "result = eval(user_input)"

    def test_exec_usage_is_critical(self, auditor):
        findings = auditor._check_security("a.py", "exec(code)\n")

        assert findings and findings[0].category == "security"

    def test_commented_eval_is_ignored(self, auditor):
        assert auditor._check_security("a.py", "# result = eval(x)\n") == []

    def test_eval_inside_re_search_pattern_is_ignored(self, auditor):
        """规则自身实现（正则里含 ``eval(``）不得被自己误报。"""
        assert auditor._check_security("a.py", "if re.search(r'\\beval\\s*\\(', x):\n") == []

    def test_hardcoded_secret_is_high(self, auditor):
        findings = auditor._check_security("a.py", 'password = "hunter2hunter2"\n')

        assert len(findings) == 1
        assert findings[0].severity == "high"
        assert "硬编码密钥" in findings[0].description

    @pytest.mark.parametrize("token", ["example", "placeholder"])
    def test_documented_secret_placeholders_are_ignored(self, auditor, token):
        line = f'api_key = "{token}_value_here"\n'
        assert auditor._check_security("a.py", line) == []

    def test_aws_secret_key_is_high(self, auditor):
        findings = auditor._check_security("a.py", "AWS_SECRET_ACCESS_KEY = os.environ['X']\n")

        assert len(findings) == 1
        assert findings[0].severity == "high"

    def test_private_key_material_is_high(self, auditor):
        findings = auditor._check_security("a.py", "-----BEGIN RSA PRIVATE KEY-----\n")

        assert len(findings) == 1
        assert findings[0].severity == "high"

    def test_sql_string_interpolation_is_high(self, auditor):
        findings = auditor._check_security(
            "a.py", 'cursor.execute("SELECT * FROM t WHERE id = %s" % uid)\n'
        )

        assert any("SQL 拼接" in f.description for f in findings)
        assert all(f.severity == "high" for f in findings if "SQL" in f.description)

    def test_clean_lines_produce_nothing(self, auditor):
        code = (
            "import os\n"
            "def add(a, b):\n"
            "    return a + b\n"
        )
        assert auditor._check_security("a.py", code) == []


# ==========================================================================
# 规则：规范
# ==========================================================================


class TestConventionRule:
    def test_long_line_is_low_severity_with_real_length(self, auditor):
        long_line = "x = '" + "a" * 130 + "'"

        findings = auditor._check_conventions("a.py", long_line + "\n")

        assert len(findings) == 1
        assert findings[0].severity == "low"
        assert str(len(long_line)) in findings[0].description
        assert "120" in findings[0].description

    def test_long_line_ignored_when_lint_not_strict(self, bus, tmp_path):
        agent = AuditorAgent("a", bus, workdir=tmp_path, lint_strict=False)

        assert agent._check_conventions("a.py", "x = '" + "a" * 200 + "'\n") == []

    def test_max_line_length_is_configurable(self, bus, tmp_path):
        agent = AuditorAgent("a", bus, workdir=tmp_path, max_line_length=10)

        findings = agent._check_conventions("a.py", "y = 123456789012\n")

        assert len(findings) == 1
        assert "10" in findings[0].description

    def test_bare_except_is_medium(self, auditor):
        findings = auditor._check_conventions(
            "a.py", "try:\n    pass\nexcept:\n    pass\n"
        )

        assert len(findings) == 1
        assert findings[0].severity == "medium"
        assert "bare except" in findings[0].description

    def test_bare_except_allowed_in_audit_tests(self, auditor):
        assert auditor._check_conventions("tests/test_audit_x.py", "except:\n") == []

    def test_star_import_is_medium(self, auditor):
        findings = auditor._check_conventions("a.py", "from os.path import *\n")

        assert len(findings) == 1
        assert "import *" in findings[0].description

    def test_star_import_allowed_in_package_init(self, auditor):
        assert auditor._check_conventions("src/pkg/__init__.py", "from .x import *\n") == []


# ==========================================================================
# 规则：性能
# ==========================================================================


class TestPerformanceRule:
    def test_string_concat_in_loop_is_medium(self, auditor):
        # 规则实现是单行正则：`for ... + str(` 必须出现在同一行才命中
        findings = auditor._check_performance(
            "a.py", "for i in items: out = out + str(i)\n"
        )

        assert len(findings) == 1
        assert findings[0].severity == "medium"
        assert findings[0].category == "performance"

    def test_sum_over_list_comprehension_is_low(self, auditor):
        findings = auditor._check_performance("a.py", "total = sum([x for x in items])\n")

        assert len(findings) == 1
        assert findings[0].severity == "low"

    def test_generator_expression_is_clean(self, auditor):
        assert auditor._check_performance("a.py", "total = sum(x for x in items)\n") == []


# ==========================================================================
# 规则：测试覆盖
# ==========================================================================


class TestCoverageRule:
    def test_missing_tests_dir_yields_warning(self, auditor, tmp_path):
        warnings = auditor._check_test_coverage({"src/a.py": "x = 1"})

        assert warnings == ["无 tests 目录，建议添加测试文件"]
        assert not (tmp_path / "tests").exists()

    def test_empty_tests_dir_yields_warning(self, auditor, tmp_path):
        (tmp_path / "tests").mkdir()

        warnings = auditor._check_test_coverage({"src/a.py": "x = 1"})

        assert warnings == ["无测试文件，新增代码缺乏测试覆盖"]

    def test_existing_tests_silence_warning(self, auditor, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_a.py").write_text("def test_ok(): pass\n", encoding="utf-8")

        assert auditor._check_test_coverage({"src/a.py": "x = 1"}) == []

    def test_non_python_or_test_changes_are_ignored(self, auditor):
        assert auditor._check_test_coverage({"README.md": "# x", "tests/test_a.py": "x"}) == []


# ==========================================================================
# 规则：UI / 视觉
# ==========================================================================


class TestUiAndVisual:
    @pytest.mark.parametrize(
        "path", ["a.html", "a.css", "a.tsx", "a.jsx", "a.vue", "a.less", "a.scss"]
    )
    def test_ui_extensions_are_detected(self, auditor, path):
        assert auditor._is_ui_change(path) is True

    @pytest.mark.parametrize("path", ["a.py", "a.md", "a.json", "a.HTML".lower() + "x"])
    def test_non_ui_extensions_are_rejected(self, auditor, path):
        assert auditor._is_ui_change(path) is False

    def test_visual_verdict_problems_become_medium_findings(self, auditor, monkeypatch):
        class _Verifier:
            def __init__(self, *a, **k):
                pass

            async def capture_screenshot(self, url, name="current"):
                assert url.startswith("file://")
                return Path("shot.png")

            async def get_verdict(self, screenshot_path):
                return SimpleNamespace(
                    verdict="revise",
                    differences=["布局错位", "颜色不一致"],
                    reasoning="边距与主题需调整",
                )

        monkeypatch.setattr("src.utils.visual_verifier.VisualVerifier", _Verifier)

        findings = asyncio.run(auditor._check_visual("index.html", "<html></html>"))

        assert len(findings) == 2
        assert all(f.severity == "medium" and f.category == "visual" for f in findings)
        assert findings[0].description == "视觉审计发现问题: 布局错位"
        assert findings[0].suggestion == "边距与主题需调整"

    def test_passing_visual_verdict_is_silent(self, auditor, monkeypatch):
        class _Verifier:
            def __init__(self, *a, **k):
                pass

            async def capture_screenshot(self, url, name="current"):
                return Path("shot.png")

            async def get_verdict(self, screenshot_path):
                return SimpleNamespace(verdict="pass", differences=[], reasoning="")

        monkeypatch.setattr("src.utils.visual_verifier.VisualVerifier", _Verifier)

        assert asyncio.run(auditor._check_visual("index.html", "<html></html>")) == []

    def test_verifier_environment_failure_is_swallowed(self, auditor, monkeypatch):
        """无浏览器环境时视觉审计必须降级，而不是让整个审计崩掉。"""

        class _Verifier:
            def __init__(self, *a, **k):
                raise RuntimeError("playwright 未安装")

        monkeypatch.setattr("src.utils.visual_verifier.VisualVerifier", _Verifier)

        assert asyncio.run(auditor._check_visual("index.html", "<html></html>")) == []

    def test_non_html_ui_file_skips_screenshot(self, auditor, monkeypatch):
        called: list[str] = []

        class _Verifier:
            def __init__(self, *a, **k):
                pass

            async def capture_screenshot(self, url, name="current"):
                called.append(url)
                return Path("shot.png")

        monkeypatch.setattr("src.utils.visual_verifier.VisualVerifier", _Verifier)

        assert asyncio.run(auditor._check_visual("style.css", "body{}")) == []
        assert called == []


# ==========================================================================
# LLM 辅助审查
# ==========================================================================


class TestLlmAssist:
    def test_no_changes_returns_empty_without_calling_engine(self, auditor):
        assert asyncio.run(auditor._llm_assist({})) == []
        assert auditor._engine.prompts == []

    @pytest.mark.parametrize(
        "answer", ["无问题", "No issue found", "NO PROBLEM here", "nothing to fix: 无问题"]
    )
    def test_clean_answers_produce_no_finding(self, auditor, answer):
        auditor._engine = FakeEngine(answer)

        assert asyncio.run(auditor._llm_assist({"a.py": "x = 1"})) == []

    def test_problem_answer_produces_medium_finding(self, auditor):
        auditor._engine = FakeEngine("发现边界条件缺失：" + "细节" * 400)

        findings = asyncio.run(auditor._llm_assist({"a.py": "x = 1"}))

        assert len(findings) == 1
        assert findings[0].severity == "medium"
        assert findings[0].category == "review"
        assert "a.py" in findings[0].file
        # suggestion 被截断到 500 字符，避免报告爆炸
        assert len(findings[0].suggestion) == 500

    def test_files_are_batched_by_configured_size(self, bus, tmp_path):
        agent = AuditorAgent("a", bus, workdir=tmp_path, llm_review_batch_size=2)
        engine = FakeEngine("无问题")
        agent._engine = engine
        changes = {f"f{i}.py": "x = 1" for i in range(5)}

        asyncio.run(agent._llm_assist(changes))

        # 5 个文件 / 每批 2 个 → 3 批
        assert len(engine.prompts) == 3
        # 每批 prompt 只带本批文件
        assert "f0.py" in engine.prompts[0] and "f2.py" not in engine.prompts[0]
        assert "f4.py" in engine.prompts[2]

    def test_engine_failure_degrades_silently(self, auditor):
        auditor._engine = FakeEngine()
        auditor._engine.raises = RuntimeError("LLM 超时")

        assert asyncio.run(auditor._llm_assist({"a.py": "x = 1"})) == []

    def test_one_failing_batch_does_not_lose_other_batches(self, bus, tmp_path):
        agent = AuditorAgent("a", bus, workdir=tmp_path, llm_review_batch_size=1)

        class _Flaky(FakeEngine):
            async def run(self, prompt):
                if "bad.py" in prompt:
                    raise RuntimeError("批次失败")
                return SimpleNamespace(final_result="发现潜在 Bug")

        agent._engine = _Flaky()

        findings = asyncio.run(agent._llm_assist({"good.py": "x", "bad.py": "y"}))

        assert len(findings) == 1
        assert "good.py" in findings[0].file


# ==========================================================================
# audit() 汇总行为
# ==========================================================================


class TestAuditAggregation:
    def test_clean_change_passes(self, bus, tmp_path):
        agent = AuditorAgent("a", bus, workdir=tmp_path, require_tests=False)
        agent._engine = FakeEngine()

        report = asyncio.run(agent.audit({"src/ok.py": "def f():\n    return 1\n"}))

        assert report.passed is True
        assert report.findings == []
        assert report.summary == "代码质量良好，未发现明显问题"

    def test_critical_finding_blocks_report(self, auditor):
        report = asyncio.run(auditor.audit({"src/bad.py": "eval(x)\n"}))

        assert report.passed is False
        assert report.critical_count == 1
        assert "1 critical" in report.summary

    def test_high_finding_blocks_report(self, auditor):
        report = asyncio.run(auditor.audit({"src/a.py": 'token = "abcdefghijklmno"\n'}))

        assert report.passed is False
        assert report.high_count == 1

    def test_medium_and_low_findings_do_not_block(self, auditor):
        code = "from os import *\ntry:\n    pass\nexcept:\n    pass\n"

        report = asyncio.run(auditor.audit({"src/a.py": code}))

        assert {f.severity for f in report.findings} == {"medium"}
        assert report.passed is True
        assert "2 medium" in report.summary

    def test_multiple_files_are_all_audited(self, auditor):
        report = asyncio.run(
            auditor.audit({"a.py": "eval(x)\n", "b.py": "def f(:\n"})
        )

        files = {f.file for f in report.findings}
        assert files == {"a.py", "b.py"}
        assert report.critical_count == 2

    def test_require_tests_toggle_controls_warning(self, bus, tmp_path):
        strict = AuditorAgent("a", bus, workdir=tmp_path, require_tests=True)
        strict._engine = FakeEngine()

        report = asyncio.run(strict.audit({"src/a.py": "x = 1\n"}))
        assert report.warnings == ["无 tests 目录，建议添加测试文件"]

        lenient = AuditorAgent("b", bus, workdir=tmp_path, require_tests=False)
        lenient._engine = FakeEngine()
        report2 = asyncio.run(lenient.audit({"src/a.py": "x = 1\n"}))
        assert report2.warnings == []

    def test_empty_change_set_is_clean(self, auditor):
        report = asyncio.run(auditor.audit({}))

        assert report.passed is True
        assert report.findings == []

    def test_ui_change_triggers_visual_audit(self, auditor, monkeypatch):
        class _Verifier:
            def __init__(self, *a, **k):
                pass

            async def capture_screenshot(self, url, name="current"):
                return Path("shot.png")

            async def get_verdict(self, screenshot_path):
                return SimpleNamespace(
                    verdict="revise", differences=["对比度不足"], reasoning="调整颜色"
                )

        monkeypatch.setattr("src.utils.visual_verifier.VisualVerifier", _Verifier)

        report = asyncio.run(auditor.audit({"web/index.html": "<html></html>"}))

        assert [f.category for f in report.findings] == ["visual"]
        assert report.passed is True  # visual 是 medium，不阻断


class TestBuildSummary:
    def test_empty(self, auditor):
        assert auditor._build_summary([], []) == "代码质量良好，未发现明显问题"

    def test_findings_grouped_by_severity(self, auditor):
        findings = [
            AuditFinding("high", "security", "a.py", 1, "x"),
            AuditFinding("high", "security", "a.py", 2, "y"),
            AuditFinding("low", "convention", "a.py", 3, "z"),
        ]

        summary = auditor._build_summary(findings, [])

        assert "发现 3 个问题" in summary
        assert "2 high" in summary
        assert "1 low" in summary

    def test_warnings_only(self, auditor):
        assert auditor._build_summary([], ["w1", "w2"]) == "2 个警告"


# ==========================================================================
# process(): 消息驱动的审计入口
# ==========================================================================


def _audit_request(code_changes: dict[str, str]) -> AgentMessage:
    return AgentMessage(
        sender="worker-1",
        recipient="auditor-1",
        message_type=MessageType.AUDIT_REQUEST,
        content="请审计",
        metadata={"code_changes": code_changes},
    )


class TestProcess:
    def test_passing_audit_publishes_audit_pass(self, auditor, bus):
        reply = asyncio.run(auditor.process(_audit_request({"a.py": "x = 1\n"})))

        assert "**结果**: 通过" in reply
        assert len(bus._message_history) == 1
        published = bus._message_history[0]
        assert published.message_type == MessageType.AUDIT_PASS
        assert published.recipient == "worker-1"
        assert "**结果**: 通过" in published.metadata["report"]

    def test_failing_audit_publishes_audit_fail(self, auditor, bus):
        reply = asyncio.run(auditor.process(_audit_request({"a.py": "eval(x)\n"})))

        assert "**结果**: 驳回" in reply
        assert bus._message_history[0].message_type == MessageType.AUDIT_FAIL

    def test_missing_code_changes_defaults_to_empty(self, auditor, bus):
        msg = AgentMessage(
            sender="w",
            recipient="auditor-1",
            message_type=MessageType.AUDIT_REQUEST,
            content="",
        )

        reply = asyncio.run(auditor.process(msg))

        assert "**结果**: 通过" in reply

    def test_audit_exception_is_reported_not_raised(self, auditor, monkeypatch):
        async def boom(changes):
            raise RuntimeError("审计器内部错误")

        monkeypatch.setattr(auditor, "audit", boom)

        reply = asyncio.run(auditor.process(_audit_request({"a.py": "x"})))

        assert reply == "审计失败: 审计器内部错误"

    def test_unknown_message_type_is_rejected(self, auditor, bus):
        msg = AgentMessage(
            sender="w",
            recipient="auditor-1",
            message_type=MessageType.TASK_ASSIGN,
            content="",
        )

        assert asyncio.run(auditor.process(msg)) == "未知操作: task_assign"
        assert bus._message_history == []


# ==========================================================================
# _get_engine 懒加载
# ==========================================================================


class TestEngineLazyLoad:
    def test_engine_without_llm_config_uses_defaults(self, bus, tmp_path, monkeypatch):
        created: list[tuple] = []
        monkeypatch.setattr(
            "src.agent.factory.create_agent_engine", lambda *a, **k: created.append((a, k)) or object()
        )
        agent = AuditorAgent("a", bus, workdir=tmp_path)

        first = agent._get_engine()
        second = agent._get_engine()

        assert first is second
        assert len(created) == 1
        assert created[0] == ((), {})

    def test_engine_with_llm_config_passes_provider_and_model(self, bus, tmp_path, monkeypatch):
        created: list[dict] = []
        monkeypatch.setattr(
            "src.agent.factory.create_agent_engine", lambda **kw: created.append(kw) or object()
        )
        agent = AuditorAgent(
            "a",
            bus,
            workdir=tmp_path,
            llm_config=SimpleNamespace(
                provider=SimpleNamespace(value="openai"), api_key="sk-x", model="gpt-4o-mini"
            ),
        )

        agent._get_engine()

        assert created[0] == {
            "provider_type": "openai",
            "api_key": "sk-x",
            "model": "gpt-4o-mini",
        }

    def test_missing_model_falls_back_to_gpt4o(self, bus, tmp_path, monkeypatch):
        created: list[dict] = []
        monkeypatch.setattr(
            "src.agent.factory.create_agent_engine", lambda **kw: created.append(kw) or object()
        )
        agent = AuditorAgent(
            "a",
            bus,
            workdir=tmp_path,
            llm_config=SimpleNamespace(
                provider=SimpleNamespace(value="openai"), api_key="k", model=""
            ),
        )

        agent._get_engine()

        assert created[0]["model"] == "gpt-4o"
