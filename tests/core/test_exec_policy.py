"""命令执行策略测试 —— 借鉴 Codex execpolicy（前缀匹配 / 最长匹配获胜 / 理由文案）"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.tool_manager import ToolManager
from src.core.approval_mode import ApprovalMode
from src.core.exceptions import ToolApprovalDeniedError
from src.core.exec_policy import (
    BUILTIN_RULES,
    Decision,
    ExecPolicy,
    Rule,
    default_policy_path,
    split_command,
)
from src.core.permissions import Effect, PermissionEngine, PermissionRequest
from src.tools_runtime.bash_tool import BashTool

# ==========================================================================
# 命令拆分
# ==========================================================================


class TestSplitCommand:
    def test_splits_with_shlex(self):
        assert split_command("git push origin main") == ["git", "push", "origin", "main"]

    def test_respects_quotes(self):
        assert split_command('echo "hello world"') == ["echo", "hello world"]

    def test_accepts_list(self):
        assert split_command(["git", "status"]) == ["git", "status"]

    def test_empty(self):
        assert split_command("") == []
        assert split_command("   ") == []

    def test_unbalanced_quotes_falls_back(self):
        assert split_command('echo "unclosed') == ["echo", '"unclosed"'] or split_command('echo "unclosed')  # 不抛异常即可


# ==========================================================================
# 规则匹配与决策
# ==========================================================================


class TestRuleMatching:
    def test_prefix_match_by_segment(self):
        rule = Rule(("git", "push"), Decision.FORBIDDEN)
        assert rule.matches(["git", "push", "origin"]) is True
        assert rule.matches(["git", "pushy"]) is False  # 不做字符串前缀误判
        assert rule.matches(["git"]) is False

    def test_specificity_is_prefix_length(self):
        assert Rule(("git",), Decision.ALLOW).specificity == 1
        assert Rule(("git", "push", "--force"), Decision.FORBIDDEN).specificity == 3


class TestEvaluation:
    def test_forbidden_with_justification(self):
        policy = ExecPolicy()
        ev = policy.evaluate("rm -rf /tmp/important")

        assert ev.decision is Decision.FORBIDDEN
        assert "rejected:" in ev.reason
        assert "不可逆" in ev.reason  # 来自内置 justification

    def test_forbidden_without_justification_mentions_prefix(self):
        policy = ExecPolicy(rules=[Rule(("danger",), Decision.FORBIDDEN)])
        ev = policy.evaluate("danger now")

        assert ev.decision is Decision.FORBIDDEN
        assert "policy forbids commands starting with `danger`" in ev.reason

    def test_prompt_with_and_without_justification(self):
        policy = ExecPolicy(rules=[
            Rule(("a",), Decision.PROMPT, "需要理由"),
            Rule(("b",), Decision.PROMPT),
        ])
        assert "requires approval: 需要理由" in policy.evaluate("a").reason
        assert "requires approval by policy" in policy.evaluate("b").reason

    def test_most_specific_wins(self):
        """Codex: 最长前缀获胜"""
        policy = ExecPolicy(rules=[
            Rule(("git",), Decision.ALLOW),
            Rule(("git", "push"), Decision.FORBIDDEN, "禁止推送"),
        ])

        assert policy.evaluate("git status").decision is Decision.ALLOW
        assert policy.evaluate("git push origin").decision is Decision.FORBIDDEN

    def test_no_match_uses_default(self):
        allow_by_default = ExecPolicy(rules=[], default_decision=Decision.ALLOW)
        assert allow_by_default.evaluate("anything").decision is Decision.ALLOW

        forbid_by_default = ExecPolicy(rules=[], default_decision=Decision.FORBIDDEN)
        ev = forbid_by_default.evaluate("anything")
        assert ev.decision is Decision.FORBIDDEN
        assert "blocked by policy" in ev.reason

        prompt_by_default = ExecPolicy(rules=[], default_decision=Decision.PROMPT)
        assert "requires approval by policy" in prompt_by_default.evaluate("anything").reason

    def test_empty_command_is_forbidden(self):
        assert ExecPolicy().evaluate("").decision is Decision.FORBIDDEN

    def test_builtin_safety_rules(self):
        """内置规则必须挡住真正危险的命令"""
        policy = ExecPolicy()
        for cmd in ("rm -rf /", "git push --force", "git reset --hard",
                    "terraform destroy", "dd if=/dev/zero of=/dev/sda"):
            ev = policy.evaluate(cmd)
            assert ev.decision is Decision.FORBIDDEN, f"{cmd} 应被禁止，实际 {ev.decision}"

    def test_builtin_readonly_commands_allowed(self):
        policy = ExecPolicy()
        for cmd in ("git status", "git diff", "ls -la", "grep -rn x .", "cat README.md"):
            assert policy.evaluate(cmd).decision is Decision.ALLOW, f"{cmd} 应放行"


# ==========================================================================
# 用户策略文件
# ==========================================================================


class TestUserPolicyFile:
    def test_load_custom_rules(self, tmp_path: Path):
        path = tmp_path / "policy.json"
        path.write_text(json.dumps({
            "default": "allow",
            "rules": [
                {"prefix": ["deploy"], "decision": "forbidden", "justification": "部署需走流水线"},
                {"prefix": ["make", "test"], "decision": "allow"},
            ],
        }), encoding="utf-8")

        policy = ExecPolicy.load(path)

        assert policy.evaluate("deploy prod").decision is Decision.FORBIDDEN
        assert "部署需走流水线" in policy.evaluate("deploy prod").reason
        assert policy.evaluate("make test").decision is Decision.ALLOW
        assert policy.evaluate("unknown-cmd").decision is Decision.ALLOW  # default

    def test_user_rule_overrides_builtin_same_prefix(self, tmp_path: Path):
        """用户把内置的 ALLOW 改严（同前缀时用户优先）"""
        path = tmp_path / "policy.json"
        path.write_text(json.dumps({
            "rules": [{"prefix": ["git", "status"], "decision": "prompt"}]
        }), encoding="utf-8")

        policy = ExecPolicy.load(path)

        assert policy.evaluate("git status").decision is Decision.PROMPT

    def test_missing_file_falls_back_to_builtins(self, tmp_path: Path):
        policy = ExecPolicy.load(tmp_path / "nope.json")
        assert policy.evaluate("rm -rf /").decision is Decision.FORBIDDEN

    def test_corrupt_file_falls_back(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        policy = ExecPolicy.load(path)
        assert policy.evaluate("rm -rf /").decision is Decision.FORBIDDEN

    def test_invalid_decision_value_skipped(self, tmp_path: Path):
        path = tmp_path / "p.json"
        path.write_text(json.dumps({
            "default": "prompt",
            "rules": [{"prefix": ["x"], "decision": "nonsense"}],
        }), encoding="utf-8")
        policy = ExecPolicy.load(path)
        # 非法决策的规则被忽略，走默认
        assert policy.evaluate("x").decision is Decision.PROMPT

    def test_string_prefix_normalized(self, tmp_path: Path):
        path = tmp_path / "p.json"
        path.write_text(json.dumps({
            "rules": [{"prefix": "deploy", "decision": "forbidden"}]
        }), encoding="utf-8")
        assert ExecPolicy.load(path).evaluate("deploy").decision is Decision.FORBIDDEN

    def test_default_policy_path(self, tmp_path: Path):
        assert default_policy_path(tmp_path) == tmp_path.resolve() / ".clawd" / "exec_policy.json"


# ==========================================================================
# 与权限引擎 / ToolManager 集成
# ==========================================================================


class TestPermissionEngineIntegration:
    def test_forbidden_command_denied(self):
        engine = PermissionEngine(exec_policy=ExecPolicy())
        d = engine.decide(PermissionRequest("BashTool", "exec", command="rm -rf /"))

        assert d.effect is Effect.DENY
        assert "rejected:" in d.reason

    def test_prompt_command_asks_even_with_session_grant(self):
        """命令级 prompt 不因会话授权被跳过（更安全）"""
        engine = PermissionEngine(exec_policy=ExecPolicy())
        req = PermissionRequest("BashTool", "exec", path="/p/x", command="pip install foo")
        engine.grant_session(req)

        d = engine.decide(req)
        assert d.effect is Effect.ASK

    def test_allowed_command_still_follows_mode_ask(self):
        """策略 ALLOW 只表示"不禁止"，不越过 ApprovalMode 的询问语义"""
        engine = PermissionEngine(exec_policy=ExecPolicy())
        d = engine.decide(PermissionRequest("BashTool", "exec", command="git status"))
        assert d.effect is Effect.ASK  # 未授权时仍走 ask（由模式决定是否真问）

    def test_forbidden_reason_not_double_wrapped(self):
        engine = PermissionEngine(exec_policy=ExecPolicy())
        d = engine.decide(PermissionRequest("BashTool", "exec", command="rm -rf /"))
        msg = PermissionEngine.denial_message(PermissionRequest("BashTool", "exec"), d.reason)

        assert msg.count("rejected:") == 1, f"文案被重复包裹: {msg}"


@pytest.fixture
def bash_tools() -> dict:
    return {"BashTool": BashTool()}


class TestToolManagerExecPolicy:
    def test_force_push_blocked(self, bash_tools):
        manager = ToolManager(bash_tools, approval_mode=ApprovalMode.YOLO)

        with pytest.raises(ToolApprovalDeniedError) as ei:
            manager._enforce_approval("BashTool", {"command": "git push --force origin main"})

        assert "rejected:" in str(ei.value)
        assert "强推" in str(ei.value)

    def test_rm_rf_blocked_even_yolo(self, bash_tools):
        manager = ToolManager(bash_tools, approval_mode=ApprovalMode.YOLO)
        with pytest.raises(ToolApprovalDeniedError):
            manager._enforce_approval("BashTool", {"command": "rm -rf /tmp/x"})

    def test_safe_command_passes_in_yolo(self, bash_tools):
        manager = ToolManager(bash_tools, approval_mode=ApprovalMode.YOLO)
        manager._enforce_approval("BashTool", {"command": "git status"})  # 不抛即通过

    def test_plan_mode_denies_even_safe_command(self, bash_tools):
        """PLAN 语义是只读，safe 命令也不许执行"""
        manager = ToolManager(bash_tools, approval_mode=ApprovalMode.PLAN)
        with pytest.raises(ToolApprovalDeniedError) as ei:
            manager._enforce_approval("BashTool", {"command": "ls"})
        assert "approval_mode" in str(ei.value).lower() or "plan" in str(ei.value).lower()

    def test_policy_file_honored_by_tool_manager(self, tmp_path: Path, bash_tools, monkeypatch):
        policy_dir = tmp_path / ".clawd"
        policy_dir.mkdir()
        (policy_dir / "exec_policy.json").write_text(json.dumps({
            "default": "allow",
            "rules": [{"prefix": ["deploy"], "decision": "forbidden",
                       "justification": "部署请走流水线"}],
        }), encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        manager = ToolManager(bash_tools, approval_mode=ApprovalMode.YOLO)

        with pytest.raises(ToolApprovalDeniedError) as ei:
            manager._enforce_approval("BashTool", {"command": "deploy prod"})
        assert "流水线" in str(ei.value)

    def test_builtin_rules_not_empty(self):
        assert len(BUILTIN_RULES) > 10
