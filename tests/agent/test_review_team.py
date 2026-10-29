"""多角色并行评审测试（回归：P1-14「review 面有名无实」）

审计事实：34 个 prompt 模板 + 6 个 REVIEW 角色定义，但生产侧只有 `get_prompt()` 一个
调用方，没有任何调度器并行跑它们。本模块补上调度器，这里验证：

- 真的并发（不是 for 循环顺序调）；
- 裁决是确定性解析，不靠模型自述"通过"；
- 任一角色失败/超时/不给裁决 → 整体 INCOMPLETE，绝不伪装 APPROVE。

全程用假 provider，**零付费 LLM 调用**。
"""

from __future__ import annotations

import asyncio
import time

from pathlib import Path

import pytest

from src.agent.review_team import (
    DEFAULT_ROLES,
    VERDICT_APPROVE,
    VERDICT_INCOMPLETE,
    VERDICT_NEEDS_FIX,
    ReviewTeam,
    available_review_roles,
    build_role_prompt,
    collect_review_targets,
    parse_role_output,
)
from src.llm.config import LLMResponse


class _FakeProvider:
    """按角色顺序返回预设文本，并记录并发情况"""

    def __init__(self, replies: dict[str, str] | None = None, delay: float = 0.05) -> None:
        self.replies = replies or {}
        self.delay = delay
        self.calls: list[str] = []
        self.concurrent = 0
        self.max_concurrent = 0

    async def chat(self, messages, **kwargs):  # noqa: ANN001 - 假 provider
        import re

        prompt = messages[0].content
        # prompt 里有一行显式说明角色（`模板 prompts/agents/<role>.md`），按它取预设回复
        match = re.search(r"prompts/agents/([\w-]+)\.md", prompt)
        role = match.group(1) if match else "unknown"
        self.calls.append(role)
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            await asyncio.sleep(self.delay)
            text = self.replies.get(role, "VERDICT: APPROVE")
            return LLMResponse(content=text, model="fake")
        finally:
            self.concurrent -= 1


class _ExplodingProvider:
    async def chat(self, messages, **kwargs):  # noqa: ANN001
        raise RuntimeError("provider 挂了")


@pytest.fixture
def sample_file(tmp_path):
    path = tmp_path / "app.py"
    path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    return path


class TestParsing:
    def test_verdict_and_severities_parsed(self):
        text = "CRITICAL: 第 3 行有 SQL 注入\nHIGH: 缺少输入校验\nVERDICT: NEEDS_FIX"
        review = parse_role_output("security-reviewer", text)
        assert review.verdict == VERDICT_NEEDS_FIX
        assert review.severities["CRITICAL"] == 1
        assert review.severities["HIGH"] == 1
        assert len(review.findings) == 2

    def test_missing_verdict_is_unknown_not_pass(self):
        review = parse_role_output("code-reviewer", "看起来还行")
        assert review.verdict == "UNKNOWN"

    def test_chinese_colon_verdict_accepted(self):
        review = parse_role_output("code-reviewer", "结论 VERDICT：APPROVE")
        assert review.verdict == VERDICT_APPROVE

    def test_markdown_bold_verdict_accepted(self):
        review = parse_role_output("code-reviewer", "**VERDICT: APPROVE**")
        assert review.verdict == VERDICT_APPROVE


class TestPromptBuilding:
    def test_prompt_contains_template_and_contract(self):
        prompt = build_role_prompt("code-reviewer", "print(1)", ["a.py"], "diff --git")
        assert "VERDICT: APPROVE" in prompt  # 输出契约
        assert "a.py" in prompt
        assert "print(1)" in prompt
        assert "diff --git" in prompt

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError, match="找不到角色模板"):
            build_role_prompt("not-a-role", "x", [])

    def test_available_roles_are_review_like(self):
        roles = available_review_roles()
        assert "code-reviewer" in roles
        assert "security-reviewer" in roles
        assert "designer" not in roles


class TestParallelExecution:
    def test_roles_run_concurrently(self, sample_file):
        provider = _FakeProvider(delay=0.08)
        team = ReviewTeam(provider_factory=lambda: provider, roles=DEFAULT_ROLES)
        started = time.perf_counter()
        report = asyncio.run(team.review([sample_file]))
        elapsed = time.perf_counter() - started

        assert len(report.roles) == len(DEFAULT_ROLES)
        assert provider.max_concurrent >= 2, "必须是并发调度，不能顺序执行"
        assert elapsed < 0.08 * len(DEFAULT_ROLES), "串行会超时，说明没有并发"
        assert report.verdict == VERDICT_APPROVE

    def test_all_roles_reported(self, sample_file):
        provider = _FakeProvider()
        report = asyncio.run(ReviewTeam(provider_factory=lambda: provider).review([sample_file]))
        assert {r.role for r in report.roles} == set(DEFAULT_ROLES)


class TestVerdictAggregation:
    def test_any_needs_fix_blocks(self, sample_file):
        provider = _FakeProvider({
            "security-reviewer": "HIGH: 明文存储密码\nVERDICT: NEEDS_FIX",
        })
        report = asyncio.run(ReviewTeam(provider_factory=lambda: provider).review([sample_file]))
        assert report.verdict == VERDICT_NEEDS_FIX
        assert any("security-reviewer" in f for f in report.blocking_findings)

    def test_blocking_severity_without_verdict_still_blocks(self, sample_file):
        """模型漏写 VERDICT 但报了 CRITICAL —— 不能因为缺一行标记就放行"""
        provider = _FakeProvider({"code-reviewer": "CRITICAL: 逻辑写反了"})
        report = asyncio.run(ReviewTeam(provider_factory=lambda: provider).review([sample_file]))
        assert report.verdict == VERDICT_NEEDS_FIX

    def test_provider_failure_makes_report_incomplete(self, sample_file):
        report = asyncio.run(
            ReviewTeam(provider_factory=lambda: _ExplodingProvider()).review([sample_file])
        )
        assert report.verdict == VERDICT_INCOMPLETE
        assert len(report.failed_roles) == len(DEFAULT_ROLES)
        assert "RuntimeError" in report.failed_roles[0].error

    def test_timeout_marks_incomplete(self, sample_file):
        provider = _FakeProvider(delay=2.0)
        report = asyncio.run(
            ReviewTeam(provider_factory=lambda: provider, timeout=0.1).review([sample_file])
        )
        assert report.verdict == VERDICT_INCOMPLETE
        assert any("超时" in r.error for r in report.failed_roles)

    def test_no_targets_is_incomplete_not_approve(self):
        report = asyncio.run(ReviewTeam(provider_factory=lambda: _FakeProvider()).review([]))
        assert report.verdict == VERDICT_INCOMPLETE
        assert report.roles == []

    def test_summary_line_mentions_verdict(self, sample_file):
        provider = _FakeProvider()
        report = asyncio.run(ReviewTeam(provider_factory=lambda: provider).review([sample_file]))
        assert VERDICT_APPROVE in report.summary_line()

    def test_to_dict_is_json_safe(self, sample_file):
        import json

        provider = _FakeProvider({"style-reviewer": "LOW: 行太长\nVERDICT: NEEDS_FIX"})
        report = asyncio.run(ReviewTeam(provider_factory=lambda: provider).review([sample_file]))
        payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False))
        assert payload["verdict"] == VERDICT_NEEDS_FIX
        assert payload["severity_totals"]["LOW"] == 1


class TestTargets:
    def test_explicit_paths_used(self, tmp_path):
        path = tmp_path / "x.py"
        path.write_text("x = 1\n", encoding="utf-8")
        assert collect_review_targets([str(path)]) == [path]

    def test_missing_paths_are_filtered_when_reading(self, tmp_path, sample_file):
        provider = _FakeProvider()
        report = asyncio.run(
            ReviewTeam(provider_factory=lambda: provider).review(
                [sample_file, tmp_path / "does-not-exist.py"]
            )
        )
        assert len(report.files) == 1


class TestSecretGuard:
    """评审会把文件内容发给模型 —— 密钥类文件必须先剔除"""

    def test_env_file_is_skipped(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("OPENAI_API_KEY=sk-real-secret\n", encoding="utf-8")
        code = tmp_path / "app.py"
        code.write_text("x = 1\n", encoding="utf-8")

        provider = _FakeProvider()
        report = asyncio.run(ReviewTeam(provider_factory=lambda: provider).review([env, code]))

        assert [Path(f).name for f in report.files] == ["app.py"]
        assert all(".env" not in call for call in provider.calls if isinstance(call, str))

    def test_pem_and_credentials_skipped(self, tmp_path):
        from src.agent.review_team import _read_files

        for name in ("server.pem", "credentials.json", "id_rsa"):
            (tmp_path / name).write_text("secret", encoding="utf-8")
        (tmp_path / "ok.py").write_text("ok = 1\n", encoding="utf-8")

        payload, used = _read_files([tmp_path / n for n in
                                     ("server.pem", "credentials.json", "id_rsa", "ok.py")])
        assert used == [str(tmp_path / "ok.py")]
        assert "secret" not in payload
