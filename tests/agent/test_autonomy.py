"""挂机自主决策引擎测试（无人值守时"自己跑完"的规则与护栏）"""

from __future__ import annotations

import json

from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.agent.autonomy import (
    Action,
    AutonomyBudget,
    AutonomyEngine,
    AutonomyLevel,
    level_from_env,
)
from src.agent.tool_manager import ToolManager
from src.core.approval_mode import ApprovalMode
from src.core.exceptions import ToolApprovalDeniedError
from src.core.permissions import Effect, PermissionRequest
from src.tools_runtime.file_edit_tool import FileEditTool


runner = CliRunner()


# ==========================================================================
# 级别与中文命名
# ==========================================================================


class TestLevels:
    def test_labels_are_chinese(self):
        assert "有人盯" in AutonomyLevel.SUPERVISED.label
        assert "半挂机" in AutonomyLevel.SEMI.label
        assert "全挂机" in AutonomyLevel.UNATTENDED.label

    def test_level_from_env(self, monkeypatch):
        monkeypatch.setenv("CLAWD_AUTONOMY", "unattended")
        assert level_from_env() is AutonomyLevel.UNATTENDED

    def test_level_from_env_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("CLAWD_AUTONOMY", "nonsense")
        assert level_from_env() is AutonomyLevel.SUPERVISED

    def test_level_from_env_missing_uses_default(self, monkeypatch):
        monkeypatch.delenv("CLAWD_AUTONOMY", raising=False)
        assert level_from_env() is AutonomyLevel.SUPERVISED


# ==========================================================================
# 决策规则
# ==========================================================================


def _req(action="write", path="src/a.py", tool="FileEditTool", command=None, session="s"):
    return PermissionRequest(tool, action, path, session_id=session, command=command)


class TestSupervised:
    def test_ask_stays_ask(self, tmp_path: Path):
        engine = AutonomyEngine(AutonomyLevel.SUPERVISED, workdir=tmp_path, audit=False)
        d = engine.decide_permission(_req(), Effect.ASK, "需你确认")

        assert d.action is Action.ASK
        assert d.needs_human is True

    def test_allow_and_deny_follow_permission_engine(self, tmp_path: Path):
        engine = AutonomyEngine(AutonomyLevel.SUPERVISED, workdir=tmp_path, audit=False)

        assert engine.decide_permission(_req(), Effect.ALLOW).action is Action.PROCEED
        assert engine.decide_permission(_req(), Effect.DENY, "受保护").action is Action.SKIP


class TestSemi:
    def test_low_risk_auto_proceeds(self, tmp_path: Path):
        engine = AutonomyEngine(AutonomyLevel.SEMI, workdir=tmp_path, audit=False)
        assert engine.decide_permission(_req(), Effect.ASK).action is Action.PROCEED

    def test_protected_path_asks_human(self, tmp_path: Path):
        engine = AutonomyEngine(AutonomyLevel.SEMI, workdir=tmp_path, audit=False)
        d = engine.decide_permission(_req(path=".git/config"), Effect.ASK)

        assert d.action is Action.ASK
        assert d.needs_human is True
        assert "高风险" in d.reason


class TestUnattended:
    def test_normal_write_proceeds(self, tmp_path: Path):
        engine = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path)
        d = engine.decide_permission(_req(path="src/app.py"), Effect.ASK)

        assert d.action is Action.PROCEED
        assert "自决放行" in d.reason

    def test_protected_write_skipped(self, tmp_path: Path):
        engine = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path)
        d = engine.decide_permission(_req(path=".git/config"), Effect.ASK)

        assert d.action is Action.SKIP
        assert "受保护" in d.reason
        assert "请换个不触碰该路径的做法" in d.reason

    def test_forbidden_command_skipped(self, tmp_path: Path):
        engine = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path)
        d = engine.decide_permission(
            _req(action="exec", path=None, tool="BashTool", command="rm -rf /"),
            Effect.DENY,
            "`rm -rf /` rejected: 递归强删不可逆",
        )

        assert d.action is Action.SKIP
        assert "rejected" in d.reason or "禁止" in d.reason

    def test_prompt_command_never_auto_approved(self, tmp_path: Path):
        """挂机时"需审批的命令"绝不能默认放行 —— 这是最关键的一条"""
        engine = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path)
        d = engine.decide_permission(
            _req(action="exec", path=None, tool="BashTool", command="pip install foo"),
            Effect.ASK,
            "`pip install foo` requires approval by policy",
        )

        assert d.action is Action.SKIP
        assert "需要人工审批" in d.reason
        assert "无人可批" in d.reason

    def test_audit_log_is_written_with_chinese_keys(self, tmp_path: Path):
        engine = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path)
        engine.decide_permission(_req(path="src/x.py"), Effect.ASK)

        audit = tmp_path / ".clawd" / "autonomy" / "decisions.jsonl"
        assert audit.is_file()
        entry = json.loads(audit.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert entry["决策"] == "放行"
        assert "挂机级别" in entry and "理由" in entry


# ==========================================================================
# 停止条件（护栏）
# ==========================================================================


class TestStopConditions:
    def test_consecutive_skips_abort(self, tmp_path: Path):
        engine = AutonomyEngine(
            AutonomyLevel.UNATTENDED, workdir=tmp_path,
            budget=AutonomyBudget(max_skips=3), audit=False,
        )
        for _ in range(3):
            engine.decide_permission(_req(path=".git/config"), Effect.ASK)

        stop, why = engine.check_stop()

        assert stop is True
        assert "硬闯安全护栏" in why

    def test_max_iterations(self, tmp_path: Path):
        engine = AutonomyEngine(
            AutonomyLevel.UNATTENDED, workdir=tmp_path,
            budget=AutonomyBudget(max_iterations=5), audit=False,
        )
        assert engine.check_stop(iterations=5)[0] is True
        assert engine.check_stop(iterations=4)[0] is False

    def test_consecutive_failures(self, tmp_path: Path):
        engine = AutonomyEngine(
            AutonomyLevel.UNATTENDED, workdir=tmp_path,
            budget=AutonomyBudget(max_consecutive_failures=3), audit=False,
        )
        stop, why = engine.check_stop(consecutive_failures=3)
        assert stop is True
        assert "连续失败" in why

    def test_cost_budget(self, tmp_path: Path):
        engine = AutonomyEngine(
            AutonomyLevel.UNATTENDED, workdir=tmp_path,
            budget=AutonomyBudget(max_cost_usd=1.0), audit=False,
        )
        stop, why = engine.check_stop(cost_usd=1.5)
        assert stop is True
        assert "预算上限" in why

    def test_summary_is_chinese(self, tmp_path: Path):
        engine = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path, audit=False)
        engine.decide_permission(_req(path="src/a.py"), Effect.ASK)
        engine.decide_permission(_req(path=".git/config"), Effect.ASK)

        text = engine.summary()

        assert "挂机级别" in text
        assert "自主放行 1 次" in text
        assert "主动跳过 1 次" in text


# ==========================================================================
# 与 ToolManager 集成
# ==========================================================================


@pytest.fixture
def tools() -> dict:
    return {"FileEditTool": FileEditTool()}


class TestToolManagerAutonomy:
    def test_unattended_auto_proceeds_normal_write(self, tools, tmp_path):
        engine = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path, audit=False)
        manager = ToolManager(tools, approval_mode=ApprovalMode.DEFAULT, autonomy=engine)
        target = tmp_path / "src" / "a.py"
        target.parent.mkdir()
        target.write_text("x", encoding="utf-8")

        manager._enforce_approval("FileEditTool", {"file_path": str(target), "content": "y"})  # 不抛即通过

    def test_unattended_skips_protected(self, tools, tmp_path):
        engine = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path, audit=False)
        manager = ToolManager(tools, approval_mode=ApprovalMode.DEFAULT, autonomy=engine)

        with pytest.raises(ToolApprovalDeniedError) as ei:
            manager._enforce_approval(
                "FileEditTool", {"file_path": ".git/config", "content": "x"}
            )
        assert "受保护" in str(ei.value)

    def test_supervised_keeps_old_behavior(self, tools, tmp_path):
        """有人盯时保持原样：无回调 → 放行（不改变既有契约）"""
        engine = AutonomyEngine(AutonomyLevel.SUPERVISED, workdir=tmp_path, audit=False)
        manager = ToolManager(tools, approval_mode=ApprovalMode.DEFAULT, autonomy=engine)
        target = tmp_path / "a.py"
        target.write_text("x", encoding="utf-8")

        manager._enforce_approval("FileEditTool", {"file_path": str(target), "content": "y"})


class TestPermissionsCli:
    def test_permissions_command_explains_in_chinese(self):
        result = runner.invoke(__import__("src.cli.entrypoint", fromlist=["app"]).app, ["permissions"])

        assert result.exit_code == 0
        for token in ("审批模式", "挂机级别", "权限结论", "受保护"):
            assert token in result.output

    def test_permissions_rules_flag_lists_builtin_rules(self):
        from src.cli.entrypoint import app as cli_app

        result = runner.invoke(cli_app, ["permissions", "--rules"])

        assert result.exit_code == 0
        assert "禁止执行" in result.output
        assert "rm -rf" in result.output


class TestUnattendedExecPolicyAware:
    """挂机自决必须区分"策略允许"与"策略要求审批"（真实 E2E 抓到的缺陷）"""

    def test_policy_allow_proceeds(self, tmp_path: Path):
        engine = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path, audit=False)
        d = engine.decide_permission(
            _req(action="exec", path=None, tool="BashTool", command="ls -la ."),
            Effect.ASK, "策略允许", policy="allow",
        )

        assert d.action is Action.PROCEED
        assert "允许清单" in d.reason

    def test_policy_prompt_skipped(self, tmp_path: Path):
        engine = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path, audit=False)
        d = engine.decide_permission(
            _req(action="exec", path=None, tool="BashTool", command="pip install x"),
            Effect.ASK, "`pip install x` requires approval by policy", policy="prompt",
        )

        assert d.action is Action.SKIP

    def test_no_policy_verdict_skipped_conservatively(self, tmp_path: Path):
        """没有命中任何规则（默认需审批）→ 挂机时保守跳过"""
        engine = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path, audit=False)
        d = engine.decide_permission(
            _req(action="exec", path=None, tool="BashTool", command="some-unknown-cmd"),
            Effect.ASK, "", policy="",
        )

        assert d.action is Action.SKIP

    def test_permission_engine_exposes_policy_verdict(self):
        """闭环：PermissionEngine 必须把策略判决传出来，否则上面三条无法实现"""
        from src.core.exec_policy import ExecPolicy
        from src.core.permissions import PermissionEngine

        engine = PermissionEngine(exec_policy=ExecPolicy())

        assert engine.decide(_req(action="exec", command="ls -la .")).policy == "allow"
        assert engine.decide(_req(action="exec", command="pip install x")).policy == "prompt"
        assert engine.decide(_req(action="exec", command="rm -rf /")).policy == "forbidden"


class TestAllowedCommandHint:
    """真实 E2E 教训：不告诉模型可用清单，它会反复试复合命令，白烧迭代"""

    def test_hint_lists_allowed_commands_in_chinese(self, tmp_path: Path):
        engine = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path, audit=False)

        hint = engine.allowed_command_hint()

        assert "挂机模式下的命令限制" in hint
        assert "`git status`" in hint or "`ls`" in hint
        assert "管道" in hint and "复合命令" in hint
        assert "一次只发一条简单命令" in hint

    def test_hint_injected_into_system_prompt_when_unattended(self, tmp_path: Path):
        from src.agent.engine import AgentEngine

        engine = AgentEngine(workdir=tmp_path)
        engine.autonomy = AutonomyEngine(AutonomyLevel.UNATTENDED, workdir=tmp_path, audit=False)
        engine.system_prompt = "BASE-PROMPT"

        prompt = engine._system_prompt_with_autonomy_hint()

        assert prompt.startswith("BASE-PROMPT")
        assert "挂机模式下的命令限制" in prompt

    def test_hint_not_injected_when_supervised(self, tmp_path: Path):
        from src.agent.engine import AgentEngine

        engine = AgentEngine(workdir=tmp_path)
        engine.autonomy = None
        engine.system_prompt = "BASE-PROMPT"

        assert engine._system_prompt_with_autonomy_hint() == "BASE-PROMPT"
