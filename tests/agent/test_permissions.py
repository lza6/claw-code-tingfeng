"""权限引擎测试 —— OpenCode 会话授权 + Codex 拒绝理由回灌 + Pi 写入边界"""

from __future__ import annotations

import asyncio

from pathlib import Path

import pytest

from src.agent.tool_manager import ToolManager
from src.core.approval_mode import ApprovalMode
from src.core.exceptions import ToolApprovalDeniedError
from src.core.permissions import (
    Decision,
    Effect,
    PermissionEngine,
    PermissionRequest,
    SessionGrants,
    extract_target_path,
    protected_reason,
)
from src.tools_runtime.bash_tool import BashTool
from src.tools_runtime.file_edit_tool import FileEditTool
from src.tools_runtime.file_read_tool import FileReadTool


# ==========================================================================
# 保护路径（Pi 的写入边界思路，Windows 可移植部分）
# ==========================================================================


class TestProtectedPaths:
    @pytest.mark.parametrize("path,keyword", [
        (".git/config", "版本控制目录"),
        ("repo/.git/HEAD", "版本控制目录"),
        ("secret.pem", "密钥/证书"),
        ("certs/server.key", "密钥/证书"),
        ("id_rsa", "私钥文件"),
        (".clawd_host_port", "敏感运行时凭据"),
    ])
    def test_protected_paths_have_reason(self, path, keyword):
        reason = protected_reason(path)
        assert reason is not None, f"{path} 应受保护"
        assert keyword in reason

    @pytest.mark.parametrize("path", ["src/app.py", "README.md", "tests/x_test.py", None, ""])
    def test_normal_paths_not_protected(self, path):
        assert protected_reason(path) is None


# ==========================================================================
# 会话级授权（OpenCode 的 sessionPermissions）
# ==========================================================================


class TestSessionGrants:
    def test_grant_then_match(self):
        grants = SessionGrants()
        req = PermissionRequest("FileEditTool", "write", "/proj/src/a.py")

        assert grants.matches(req) is False
        grants.grant(req)
        assert grants.matches(req) is True

    def test_grant_scoped_to_directory(self):
        """OpenCode 的语义：授权按目录复用，换目录要重新问"""
        grants = SessionGrants()
        grants.grant(PermissionRequest("FileEditTool", "write", "/proj/src/a.py"))

        same_dir = PermissionRequest("FileEditTool", "write", "/proj/src/b.py")
        other_dir = PermissionRequest("FileEditTool", "write", "/proj/docs/c.md")

        assert grants.matches(same_dir) is True
        assert grants.matches(other_dir) is False

    def test_grant_scoped_to_tool_and_action(self):
        grants = SessionGrants()
        grants.grant(PermissionRequest("FileEditTool", "write", "/proj/src/a.py"))

        assert grants.matches(PermissionRequest("BashTool", "exec", "/proj/src/a.py")) is False

    def test_grant_scoped_to_session(self):
        grants = SessionGrants()
        grants.grant(PermissionRequest("FileEditTool", "write", "/p/a.py", session_id="s1"))

        assert grants.matches(PermissionRequest("FileEditTool", "write", "/p/a.py", session_id="s1"))
        assert not grants.matches(
            PermissionRequest("FileEditTool", "write", "/p/a.py", session_id="s2")
        )

    def test_clear_all_and_by_session(self):
        grants = SessionGrants()
        grants.grant(PermissionRequest("T", "write", "/p/a", session_id="s1"))
        grants.grant(PermissionRequest("T", "write", "/p/b", session_id="s2"))

        grants.clear("s1")
        assert len(grants) == 1
        grants.clear()
        assert len(grants) == 0


# ==========================================================================
# 决策顺序
# ==========================================================================


class TestDecide:
    def test_read_always_allowed(self):
        engine = PermissionEngine()
        assert engine.decide(PermissionRequest("FileReadTool", "read", "a.py")).effect is Effect.ALLOW

    def test_protected_write_denied_with_reason(self):
        engine = PermissionEngine()
        d = engine.decide(PermissionRequest("FileEditTool", "write", ".git/config"))

        assert d.effect is Effect.DENY
        assert "版本控制目录" in d.reason

    def test_protected_still_denied_in_yolo_by_default(self):
        """密钥/版本库不该因为开了 YOLO 就能改"""
        engine = PermissionEngine()
        d = engine.decide(
            PermissionRequest("FileEditTool", "write", "id_rsa"), approval_mode="yolo"
        )
        assert d.effect is Effect.DENY

    def test_protect_can_be_relaxed_explicitly(self):
        engine = PermissionEngine(protect_even_in_yolo=False)
        d = engine.decide(
            PermissionRequest("FileEditTool", "write", "id_rsa"), approval_mode="yolo"
        )
        assert d.effect is Effect.ASK

    def test_session_grant_beats_ask(self):
        engine = PermissionEngine()
        req = PermissionRequest("FileEditTool", "write", "/p/src/a.py")
        engine.grant_session(req)

        assert engine.decide(req).effect is Effect.ALLOW

    def test_unknown_case_asks(self):
        engine = PermissionEngine()
        assert engine.decide(PermissionRequest("FileEditTool", "write", "/p/src/a.py")).effect is Effect.ASK


class TestDenialMessage:
    def test_codex_style_format(self):
        req = PermissionRequest("FileEditTool", "write", ".git/config")
        msg = PermissionEngine.denial_message(req, "版本控制目录内禁止写入")

        assert msg.startswith("`FileEditTool`")
        assert "rejected:" in msg
        assert "版本控制控制" not in msg and "版本控制目录内禁止写入" in msg

    def test_message_without_path(self):
        req = PermissionRequest("BashTool", "exec", None)
        msg = PermissionEngine.denial_message(req, "策略禁止")
        assert "`BashTool` rejected: 策略禁止" == msg


class TestExtractTargetPath:
    @pytest.mark.parametrize("args,expected", [
        ({"path": "a.py"}, "a.py"),
        ({"file_path": "b.py"}, "b.py"),
        ({"filepath": "c.py"}, "c.py"),
        ({"filename": "d.py"}, "d.py"),
        ({"file": "e.py"}, "e.py"),
        ({}, None),
        (None, None),
        ({"path": "   "}, None),
    ])
    def test_common_keys(self, args, expected):
        assert extract_target_path(args) == expected

    def test_exec_cwd_fallback(self):
        got = extract_target_path({"cwd": "/proj/src"})
        assert got is not None and got.endswith("_")


# ==========================================================================
# 与 ToolManager 的集成（真实门禁路径）
# ==========================================================================


@pytest.fixture
def tools(tmp_path: Path) -> dict:
    target = tmp_path / "ok.txt"
    target.write_text("old", encoding="utf-8")
    return {"FileEditTool": FileEditTool(), "FileReadTool": FileReadTool(), "BashTool": BashTool()}


class TestToolManagerIntegration:
    def test_protected_write_denied_even_without_callback(self, tools, tmp_path):
        """新行为：保护路径在没有回调时也必须拒绝（此前非交互=全放行）"""
        manager = ToolManager(tools, approval_mode=ApprovalMode.DEFAULT)
        git_cfg = tmp_path / ".git" / "config"
        git_cfg.parent.mkdir()
        git_cfg.write_text("x", encoding="utf-8")

        with pytest.raises(ToolApprovalDeniedError) as ei:
            manager._enforce_approval("FileEditTool", {"file_path": str(git_cfg), "content": "hack"})

        assert "rejected:" in str(ei.value)
        assert "版本控制目录" in str(ei.value)

    def test_protected_denied_in_yolo(self, tools, tmp_path):
        manager = ToolManager(tools, approval_mode=ApprovalMode.YOLO)
        with pytest.raises(ToolApprovalDeniedError):
            manager._enforce_approval("FileEditTool", {"file_path": ".git/config", "content": "x"})

    def test_read_tool_never_blocked(self, tools):
        manager = ToolManager(tools, approval_mode=ApprovalMode.PLAN)
        manager._enforce_approval("FileReadTool", {"file_path": "a.py"})  # 不抛异常即通过

    def test_plan_mode_still_denies_writes(self, tools, tmp_path):
        manager = ToolManager(tools, approval_mode=ApprovalMode.PLAN)
        with pytest.raises(ToolApprovalDeniedError):
            manager._enforce_approval(
                "FileEditTool", {"file_path": str(tmp_path / "ok.txt"), "content": "x"}
            )

    def test_approval_grants_session_and_skips_second_prompt(self, tools, tmp_path):
        """OpenCode 的核心洞见：批准一次，同目录同类操作不再问"""
        prompts: list[str] = []

        def confirm(tool_name, kind, args):
            prompts.append(tool_name)
            return True

        manager = ToolManager(
            tools, approval_mode=ApprovalMode.DEFAULT, confirm_callback=confirm
        )
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("x", encoding="utf-8")
        f2.write_text("y", encoding="utf-8")

        manager._enforce_approval("FileEditTool", {"file_path": str(f1), "content": "1"})
        manager._enforce_approval("FileEditTool", {"file_path": str(f2), "content": "2"})

        assert len(prompts) == 1, f"第二次同目录写入不应再询问，实际问了 {len(prompts)} 次"

    def test_different_directory_prompts_again(self, tools, tmp_path):
        prompts: list[str] = []

        def confirm(tool_name, kind, args):
            prompts.append(tool_name)
            return True

        manager = ToolManager(
            tools, approval_mode=ApprovalMode.DEFAULT, confirm_callback=confirm
        )
        d1 = tmp_path / "src"
        d2 = tmp_path / "docs"
        d1.mkdir()
        d2.mkdir()
        (d1 / "a.py").write_text("x", encoding="utf-8")
        (d2 / "a.md").write_text("y", encoding="utf-8")

        manager._enforce_approval("FileEditTool", {"file_path": str(d1 / "a.py"), "content": "1"})
        manager._enforce_approval("FileEditTool", {"file_path": str(d2 / "a.md"), "content": "2"})

        assert len(prompts) == 2

    def test_user_denial_reason_reaches_model(self, tools, tmp_path):
        manager = ToolManager(
            tools, approval_mode=ApprovalMode.DEFAULT, confirm_callback=lambda *a: False
        )
        target = tmp_path / "ok.txt"

        with pytest.raises(ToolApprovalDeniedError) as ei:
            manager._enforce_approval(
                "FileEditTool", {"file_path": str(target), "content": "x"}
            )

        assert "rejected:" in str(ei.value)
        assert "用户拒绝" in str(ei.value)

    def test_denial_exception_is_model_visible(self, tools, tmp_path):
        """契约：拒绝异常必须是 ToolExecutionError 子类

        ToolManager 层**故意抛异常**（不在此处吞掉）；由 `engine_loop` 捕获
        `ToolExecutionError` 并转成 `ToolResult(success=False, error=...)` 回灌给模型
        —— 这正是 Codex 的做法：拒绝要带理由让模型换方案，而不是静默或穿透。
        """
        from src.core.exceptions import ToolExecutionError

        manager = ToolManager(tools, approval_mode=ApprovalMode.PLAN)
        target = tmp_path / "ok.txt"

        with pytest.raises(ToolApprovalDeniedError) as ei:
            asyncio.run(
                manager.execute_tool("FileEditTool", {"file_path": str(target), "content": "x"})
            )

        assert isinstance(ei.value, ToolExecutionError), "必须是 ToolExecutionError 子类才会被环路转成 tool result"
        assert ei.value.details.get("tool_name") == "FileEditTool"
