"""审批模式门禁回归测试。

## 背景（真实缺陷）

`ApprovalMode` 此前只在配置层被读写，**没有任何运行时消费者**
（全仓库 grep `approval_mode` 在 `src/` 下只命中配置模块）。

后果：用户按文档把 `approval_mode` 设为 `plan`（语义是"仅分析，不修改文件"），
Agent **照样写盘**。这是一个"装饰性控制"——用户以为锁了，其实没有。

实测确认（修复前）：

    ToolManager(tools).execute_tool('FileEditTool', {...})
    → 成功写盘，无任何拦截

## 修复范围（重要，勿误读）

本门禁**只实施 PLAN 模式的硬性只读拒绝**。PLAN 的判定结果是明确的"拒绝"，
不需要交互 UI。

DEFAULT / AUTO_EDIT / YOLO 不做运行时拦截 —— 因为本仓库**没有任何交互式
审批设施**，DEFAULT 语义中的"需要审批"无法落地；强行拦截会让开箱即用的
默认配置直接不可用。补齐交互审批属于**新功能**，不在缺陷修复范围内。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from src.agent.tool_manager import ToolManager, classify_tool
from src.core.approval_mode import ApprovalMode
from src.core.exceptions import ErrorCode, ToolApprovalDeniedError, ToolExecutionError
from src.tools_runtime.bash_tool import BashTool
from src.tools_runtime.file_edit_tool import FileEditTool
from src.tools_runtime.file_read_tool import FileReadTool


@pytest.fixture
def workdir() -> Path:
    return Path.cwd()


def _manager(workdir: Path, mode: ApprovalMode) -> ToolManager:
    return ToolManager(
        {
            "FileReadTool": FileReadTool(base_path=workdir),
            "FileEditTool": FileEditTool(base_path=workdir),
            "BashTool": BashTool(workdir=workdir),
        },
        approval_mode=mode,
    )


# ---------------------------------------------------------------------------
# 工具分类
# ---------------------------------------------------------------------------


class TestClassifyTool:
    @pytest.mark.parametrize("name", ["FileReadTool", "GlobTool", "GrepTool", "HotFilesTool"])
    def test_read_tools(self, name: str):
        assert classify_tool(name) == "read"

    @pytest.mark.parametrize("name", ["FileEditTool", "WriteTool", "PatchTool"])
    def test_write_tools(self, name: str):
        assert classify_tool(name) == "write"

    @pytest.mark.parametrize("name", ["BashTool", "ShellTool", "CommandTool", "ExecTool"])
    def test_exec_tools(self, name: str):
        assert classify_tool(name) == "exec"

    def test_exec_takes_priority_over_write(self):
        """名字同时含两类标记时，exec 更严格，应优先归类为 exec"""
        assert classify_tool("BashEditTool") == "exec"


# ---------------------------------------------------------------------------
# PLAN：硬性只读
# ---------------------------------------------------------------------------


class TestPlanModeIsReadOnly:
    def test_read_tool_allowed(self, workdir: Path):
        m = _manager(workdir, ApprovalMode.PLAN)
        result = asyncio.run(m.execute_tool("FileReadTool", {"file_path": "README.md"}))
        assert result.success is True, result.error

    def test_write_tool_denied(self, workdir: Path):
        m = _manager(workdir, ApprovalMode.PLAN)
        with pytest.raises(ToolApprovalDeniedError):
            asyncio.run(m.execute_tool("FileEditTool", {"file_path": "x.py", "content": "y=1"}))

    def test_exec_tool_denied(self, workdir: Path):
        m = _manager(workdir, ApprovalMode.PLAN)
        with pytest.raises(ToolApprovalDeniedError):
            asyncio.run(m.execute_tool("BashTool", {"command": "echo hi"}))

    def test_denied_error_is_actionable(self, workdir: Path):
        """错误信息必须告诉用户怎么解锁，而不是只说"被拒" """
        m = _manager(workdir, ApprovalMode.PLAN)
        with pytest.raises(ToolApprovalDeniedError) as exc_info:
            asyncio.run(m.execute_tool("BashTool", {"command": "echo hi"}))

        err = exc_info.value
        assert err.code == ErrorCode.TOOL_APPROVAL_DENIED
        assert "approval_mode" in err.message
        assert "plan" in err.message
        assert err.details["tool_kind"] == "exec"

    def test_denied_is_not_recoverable(self, workdir: Path):
        """重试不会改变结果，必须标 recoverable=False"""
        m = _manager(workdir, ApprovalMode.PLAN)
        with pytest.raises(ToolApprovalDeniedError) as exc_info:
            asyncio.run(m.execute_tool("BashTool", {"command": "echo hi"}))
        assert exc_info.value.recoverable is False

    def test_parallel_path_also_gated(self, workdir: Path):
        """并行分支必须同样过门禁 —— 否则门禁只挡住一半请求"""
        m = _manager(workdir, ApprovalMode.PLAN)
        with pytest.raises(ToolApprovalDeniedError):
            asyncio.run(m.execute_tools_parallel([("BashTool", {"command": "echo hi"})]))

    def test_write_is_actually_blocked(self, workdir: Path, tmp_path: Path):
        """端到端：被拒后磁盘上不应出现该文件"""
        m = _manager(tmp_path, ApprovalMode.PLAN)
        target = tmp_path / "should_not_exist.py"
        with pytest.raises(ToolApprovalDeniedError):
            asyncio.run(m.execute_tool(
                "FileEditTool",
                {"file_path": str(target), "content": "x = 1"},
            ))
        assert not target.exists(), "PLAN 模式下文件仍被写入"


# ---------------------------------------------------------------------------
# DEFAULT / AUTO_EDIT / YOLO：不拦截（当前无交互审批设施）
# ---------------------------------------------------------------------------


class TestNonPlanModesUnchanged:
    @pytest.mark.parametrize("mode", [ApprovalMode.DEFAULT, ApprovalMode.AUTO_EDIT, ApprovalMode.YOLO])
    def test_exec_allowed(self, workdir: Path, mode: ApprovalMode):
        """回归：默认配置下的行为不得被改变

        若这里失败，说明门禁把开箱即用的默认模式也拦了 —— 那会让 Agent
        完全不可用（而项目尚无交互审批 UI 可供用户放行）。
        """
        m = _manager(workdir, mode)
        result = asyncio.run(m.execute_tool("BashTool", {"command": "echo ok"}))
        assert result.success is True, result.error

    @pytest.mark.parametrize("mode", [ApprovalMode.DEFAULT, ApprovalMode.AUTO_EDIT, ApprovalMode.YOLO])
    def test_read_allowed(self, workdir: Path, mode: ApprovalMode):
        m = _manager(workdir, mode)
        result = asyncio.run(m.execute_tool("FileReadTool", {"file_path": "README.md"}))
        assert result.success is True, result.error


# ---------------------------------------------------------------------------
# 与 Agent 环路的衔接
# ---------------------------------------------------------------------------


class TestAgentLoopIntegration:
    """拒绝必须是**模型可见的 ToolResult**，不能穿透到自愈引擎。

    Agent 环路 `engine_loop._execute_single_tool` 只捕获 `ToolExecutionError`
    并转成 `ToolResult(success=False, error=...)`。若抛的是它的兄弟类
    （如 SecurityError），异常会穿透出去触发自愈引擎去"修复"一个
    **策略拒绝** —— 策略拒绝不是缺陷，模型应当看到它并调整策略。
    """

    def test_denial_is_a_tool_execution_error_subclass(self):
        assert issubclass(ToolApprovalDeniedError, ToolExecutionError)

    def test_denial_becomes_tool_result_not_exception(self):
        from src.agent.engine_loop import AgentLoopConfig, _execute_single_tool

        workdir = Path.cwd()
        m = _manager(workdir, ApprovalMode.PLAN)
        cfg = AgentLoopConfig(
            goal="t", llm_provider=None, messages=[], max_iterations=1,
            system_prompt="", tools=m.tools, _execute_tool=m.execute_tool,
        )

        _name, _args, result = asyncio.run(
            _execute_single_tool(cfg, "BashTool", {"command": "echo hi"}, "[test]")
        )

        assert result.success is False
        assert "E2009" in (result.error or "")
        assert "plan" in (result.error or "")

    def test_read_tool_still_works_in_plan_via_loop(self):
        from src.agent.engine_loop import AgentLoopConfig, _execute_single_tool

        workdir = Path.cwd()
        m = _manager(workdir, ApprovalMode.PLAN)
        cfg = AgentLoopConfig(
            goal="t", llm_provider=None, messages=[], max_iterations=1,
            system_prompt="", tools=m.tools, _execute_tool=m.execute_tool,
        )

        _n, _a, result = asyncio.run(
            _execute_single_tool(cfg, "FileReadTool", {"file_path": "README.md"}, "[test]")
        )
        assert result.success is True, result.error


# ---------------------------------------------------------------------------
# 配置链路
# ---------------------------------------------------------------------------


class TestConfigWiring:
    def test_reads_mode_from_settings_when_not_injected(self, monkeypatch):
        """不显式传参时，应自动从配置读取 —— 否则用户设了也不生效"""
        monkeypatch.setenv("APPROVAL_MODE", "plan")
        m = ToolManager({})
        assert m.approval_mode == ApprovalMode.PLAN

    def test_explicit_param_overrides_settings(self, monkeypatch):
        monkeypatch.setenv("APPROVAL_MODE", "plan")
        m = ToolManager({}, approval_mode=ApprovalMode.YOLO)
        assert m.approval_mode == ApprovalMode.YOLO

    def test_failure_falls_back_to_default_not_yolo(self, monkeypatch):
        """配置读取失败时必须退回 DEFAULT

        最危险的降级方向是"读不到配置就放开全部管控"，必须锁死。
        """
        import src.core.config.models as models

        class _Boom:
            def __init__(self, *_a, **_kw):
                raise RuntimeError("simulated config failure")

        monkeypatch.setattr(models, "AgentSettings", _Boom)

        # 直接验证降级函数本身（而非整个 __init__）
        assert ToolManager._load_approval_mode() == ApprovalMode.DEFAULT

        # 且经 __init__ 也不应炸、不应放大权限
        m = ToolManager({})
        assert m.approval_mode == ApprovalMode.DEFAULT

    def test_env_example_documents_the_switch(self):
        """用户必须能从 .env.example 发现这个开关"""
        text = (Path.cwd() / ".env.example").read_text(encoding="utf-8")
        assert "APPROVAL_MODE" in text
        assert "plan" in text


class TestSilentFalseSecurityIsDisclosed:
    """DEFAULT / AUTO_EDIT 声明了审批语义，但本版本无法实施。

    不说明的后果是**静默的虚假安全感** —— 用户读到
    "DEFAULT: 编辑文件或执行 shell 需要审批" 会以为有保护。
    这比明说"不支持"更危险。构造时必须一次性告警。
    """

    @pytest.mark.parametrize("mode", [ApprovalMode.DEFAULT, ApprovalMode.AUTO_EDIT])
    def test_warns_when_mode_cannot_be_enforced(self, caplog, mode):
        import logging

        with caplog.at_level(logging.WARNING, logger="agent.tool_manager"):
            ToolManager({}, approval_mode=mode)

        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "未提供交互式确认回调" in joined
        assert mode.value in joined

    def test_plan_mode_does_not_warn_about_unenforceable(self, caplog):
        """PLAN 是被真正实施的，不该有这条告警"""
        import logging

        with caplog.at_level(logging.WARNING, logger="agent.tool_manager"):
            ToolManager({}, approval_mode=ApprovalMode.PLAN)

        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "未提供交互式确认回调" not in joined

    def test_yolo_does_not_warn(self, caplog):
        """YOLO 的语义（全部自动批准）恰好就是当前实际行为，无需告警"""
        import logging

        with caplog.at_level(logging.WARNING, logger="agent.tool_manager"):
            ToolManager({}, approval_mode=ApprovalMode.YOLO)

        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "未提供交互式确认回调" not in joined


# ---------------------------------------------------------------------------
# 四种模式的完整语义矩阵（v0.54.0 补齐交互式审批后）
# ---------------------------------------------------------------------------


class TestFullModeMatrix:
    """`ApprovalMode` 文档声明了四种语义，这里逐格验证。

    | 模式 | read | write | exec |
    |:---|:---|:---|:---|
    | plan       | 放行 | 拒绝 | 拒绝 |
    | default    | 放行 | 询问 | 询问 |
    | auto-edit  | 放行 | 放行 | 询问 |
    | yolo       | 放行 | 放行 | 放行 |

    "询问"的含义：有 `confirm_callback` 时按回调结果决定；无回调时放行
    （非交互场景不能因为没人应答就卡死，也不能因此改变既有行为）。
    """

    def _outcome(self, workdir, mode, cb, tool, args) -> str:
        # 只读用例需要一个真实存在的文件，否则会因"文件不存在"抛
        # ToolInvalidArgsError 而非走到审批判定，测不到我们想测的东西。
        (Path(workdir) / "README.md").write_text("probe", encoding="utf-8")
        # BashTool 默认只允许进程 cwd；tmp_path 在别处，需显式放行。
        # 这条调用本身也是 `set_allowed_workdirs` 的回归验证 —— 修复前它
        # 完全无效（值导入 vs 重新绑定），见 bash_executor._is_safe_path。
        from src.tools_runtime.bash_constants import set_allowed_workdirs

        set_allowed_workdirs([Path(workdir)])
        m = ToolManager(
            {
                "FileReadTool": FileReadTool(base_path=workdir),
                "FileEditTool": FileEditTool(base_path=workdir),
                "BashTool": BashTool(workdir=workdir),
            },
            approval_mode=mode,
            confirm_callback=cb,
        )
        try:
            asyncio.run(m.execute_tool(tool, args))
            return "allow"
        except ToolApprovalDeniedError:
            return "deny"

    def _row(self, workdir, mode, cb) -> tuple[str, str, str]:
        x = workdir / "_probe.py"
        return (
            self._outcome(workdir, mode, cb, "FileReadTool", {"file_path": "README.md"}),
            self._outcome(workdir, mode, cb, "FileEditTool", {"file_path": str(x), "content": "v=1"}),
            self._outcome(workdir, mode, cb, "BashTool", {"command": "echo hi"}),
        )

    def test_plan_is_read_only_regardless_of_callback(self, tmp_path):
        for cb in (None, lambda *a: True, lambda *a: False):
            assert self._row(tmp_path, ApprovalMode.PLAN, cb) == ("allow", "deny", "deny")

    def test_yolo_allows_everything(self, tmp_path):
        for cb in (None, lambda *a: True, lambda *a: False):
            assert self._row(tmp_path, ApprovalMode.YOLO, cb) == ("allow", "allow", "allow")

    def test_default_without_callback_preserves_legacy_behaviour(self, tmp_path):
        """非交互场景（脚本/CI）行为必须与修复前一致 —— 否则会破坏自动化"""
        assert self._row(tmp_path, ApprovalMode.DEFAULT, None) == ("allow", "allow", "allow")

    def test_default_asks_for_both_write_and_exec(self, tmp_path):
        assert self._row(tmp_path, ApprovalMode.DEFAULT, lambda *a: True) == ("allow", "allow", "allow")
        assert self._row(tmp_path, ApprovalMode.DEFAULT, lambda *a: False) == ("allow", "deny", "deny")

    def test_auto_edit_auto_approves_write_but_asks_for_exec(self, tmp_path):
        """auto-edit 的语义是"自动批准文件编辑"，但 shell 仍需审批"""
        assert self._row(tmp_path, ApprovalMode.AUTO_EDIT, lambda *a: False) == ("allow", "allow", "deny")
        assert self._row(tmp_path, ApprovalMode.AUTO_EDIT, lambda *a: True) == ("allow", "allow", "allow")

    def test_read_never_asks(self, tmp_path):
        """只读工具不该打断用户 —— 否则每个文件读都要确认，无法使用"""
        asked = []

        def spy(name, kind, args):
            asked.append(name)
            return True

        self._outcome(tmp_path, ApprovalMode.DEFAULT, spy, "FileReadTool", {"file_path": "README.md"})
        assert asked == [], f"只读工具不应触发审批，实际触发了: {asked}"

    def test_callback_receives_tool_name_kind_and_args(self, tmp_path):
        seen = []

        def spy(name, kind, args):
            seen.append((name, kind, args))
            return True

        self._outcome(tmp_path, ApprovalMode.DEFAULT, spy, "BashTool", {"command": "echo probe"})
        assert len(seen) == 1
        name, kind, args = seen[0]
        assert name == "BashTool"
        assert kind == "exec"
        assert args == {"command": "echo probe"}

    def test_set_confirm_callback_enables_approval_after_construction(self, tmp_path):
        """REPL 是在引擎构造之后才挂载回调的，这条路径必须可用"""
        from src.tools_runtime.bash_constants import set_allowed_workdirs

        set_allowed_workdirs([Path(tmp_path)])
        m = ToolManager(
            {"BashTool": BashTool(workdir=tmp_path)},
            approval_mode=ApprovalMode.DEFAULT,
        )
        # 挂载前：放行
        r1 = asyncio.run(m.execute_tool("BashTool", {"command": "echo a"}))
        assert r1.success is True

        # 挂载后：拒绝生效
        m.set_confirm_callback(lambda *a: False)
        with pytest.raises(ToolApprovalDeniedError):
            asyncio.run(m.execute_tool("BashTool", {"command": "echo b"}))

        # 卸载后：恢复放行
        m.set_confirm_callback(None)
        r3 = asyncio.run(m.execute_tool("BashTool", {"command": "echo c"}))
        assert r3.success is True


# ---------------------------------------------------------------------------
# 交互式确认：用户应答的判定 + 异常安全性
# ---------------------------------------------------------------------------


class TestInteractiveConfirmPrompt:
    """验证 REPL 的确认提示本身。

    这条路径只做"用户说了什么 → 是否放行"的判定，不涉及工具执行。
    重点是**异常安全性**：审批环节出任何问题时，保守的一方必须是
    "不执行"，而不是"放行"。
    """

    def _session(self):
        from src.cli.repl_session import ReplSession

        # 不跑 __init__（会初始化引擎），只借用方法
        s = ReplSession.__new__(ReplSession)
        s._safe_print = lambda *a, **k: None  # 静音输出
        return s

    @pytest.mark.parametrize("typed,expected", [
        ("y", True),
        ("Y", True),
        ("yes", True),
        ("YES", True),
        ("n", False),
        ("no", False),
        ("", False),
        ("whatever", False),
        ("yeah sure", False),
    ])
    def test_user_answer_mapping(self, typed, expected):
        s = self._session()
        with patch("builtins.input", return_value=typed):
            assert s._confirm_tool_execution("BashTool", "exec", {"command": "x"}) is expected

    def test_eof_is_denied(self):
        """管道关闭 / 无 stdin 时不能默认放行"""
        s = self._session()
        with patch("builtins.input", side_effect=EOFError):
            assert s._confirm_tool_execution("BashTool", "exec", {"command": "x"}) is False

    def test_keyboard_interrupt_is_denied(self):
        """用户按 Ctrl+C 想中断 —— 应当理解为"不要执行" """
        s = self._session()
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            assert s._confirm_tool_execution("BashTool", "exec", {"command": "x"}) is False

    def test_unexpected_error_is_denied(self):
        """提示环节自身出错时也不能放行"""
        s = self._session()
        with patch("builtins.input", side_effect=OSError("tty gone")):
            assert s._confirm_tool_execution("BashTool", "exec", {"command": "x"}) is False
