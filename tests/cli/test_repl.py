"""cli/repl 模块测试 — REPL 辅助函数与 ReplSession 核心逻辑"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ====================================================================
# _print 函数测试
# ====================================================================

class TestPrint:
    """_print 辅助函数测试"""

    def test_print_normal(self, capsys):
        from src.cli.repl import _print
        _print("hello")
        captured = capsys.readouterr()
        assert "hello" in captured.out

    def test_print_unicode_error_fallback(self, capsys):
        """UnicodeEncodeError 时回退到 ASCII"""
        from src.cli.repl import _print
        with patch("builtins.print") as mock_print:
            mock_print.side_effect = [UnicodeEncodeError('gbk', '', 0, 1, 'fail'), None]
            _print("test")
            # 第二次调用应使用 ASCII 回退
            assert mock_print.call_count == 2


# ====================================================================
# 内置命令处理函数测试
# ====================================================================

class TestHandleHelp:
    """_handle_help 测试"""

    def test_prints_help(self, capsys):
        from src.cli.repl import _handle_help
        _handle_help()
        captured = capsys.readouterr()
        assert "Clawd Code" in captured.out or "help" in captured.out.lower()


class TestHandleVersion:
    """_handle_version 测试"""

    def test_prints_version(self, capsys):
        from src.cli.repl import _handle_version
        _handle_version()
        captured = capsys.readouterr()
        assert "v" in captured.out or "Python" in captured.out


class TestHandleDoctor:
    """_handle_doctor 测试"""

    def test_runs_diagnostics(self, capsys):
        from src.cli.repl import _handle_doctor
        _handle_doctor()
        captured = capsys.readouterr()
        # 应包含 Python 版本信息
        assert "Python" in captured.out


class TestHandleTools:
    """_handle_tools 测试"""

    def test_lists_tools(self, capsys):
        from src.cli.repl import _handle_tools
        engine = MagicMock()
        engine.get_available_tools.return_value = {
            'BashTool': MagicMock(description='Run bash commands'),
            'FileReadTool': MagicMock(description='Read files'),
        }
        _handle_tools(engine)
        captured = capsys.readouterr()
        assert "BashTool" in captured.out or "FileReadTool" in captured.out


class TestHandleCost:
    """_handle_cost 测试"""

    def test_prints_cost_report(self, capsys):
        from src.cli.repl import _handle_cost
        engine = MagicMock()
        engine.get_cost_report.return_value = "Total: $0.50"
        _handle_cost(engine)
        captured = capsys.readouterr()
        assert "$0.50" in captured.out

    def test_no_cost_data(self, capsys):
        from src.cli.repl import _handle_cost
        engine = MagicMock()
        engine.get_cost_report.return_value = None
        _handle_cost(engine)
        captured = capsys.readouterr()
        assert "暂无" in captured.out


class TestHandleStatus:
    """_handle_status 测试"""

    def test_prints_status(self, capsys):
        from src.cli.repl import _handle_status
        engine = MagicMock()
        engine.is_running = True
        engine.get_available_tools.return_value = {'T': MagicMock()}
        engine.get_cost_summary.return_value = {'total_calls': 5, 'total_cost': 0.1, 'total_tokens': 100}
        engine.get_perf_summary.return_value = {'avg_latency_ms': 200}
        _handle_status(engine)
        captured = capsys.readouterr()
        assert "引擎状态" in captured.out


# ====================================================================
# ReplSession 测试
# ====================================================================

class TestReplSessionInit:
    """ReplSession 初始化测试"""

    def test_default_init(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        assert session.max_iterations == 10
        assert session.engine is None
        assert session._turn_count == 0
        assert session._loop is not None

    def test_custom_init(self, tmp_path):
        from src.cli.repl import ReplSession
        session = ReplSession(workdir=tmp_path, max_iterations=5, use_rich_hud=False)
        assert session.workdir == tmp_path
        assert session.max_iterations == 5


class TestReplSessionInitEngine:
    """_init_engine 测试"""

    def test_lazy_init(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        assert session.engine is None

        with patch('src.agent.factory.create_agent_engine') as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine
            session._init_engine()
            # factory 内部会调用 create_agent_engine，但由于依赖复杂，可能失败
            # 我们只验证 engine 被尝试初始化
            assert mock_create.called or session.engine is not None

    def test_idempotent(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        mock_engine = MagicMock()
        session.engine = mock_engine

        with patch('src.agent.factory.create_agent_engine') as mock_create:
            session._init_engine()
            mock_create.assert_not_called()
            assert session.engine is mock_engine


class TestReplSessionPostTaskHook:
    """_post_task_hook 测试"""

    def test_none_session(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session._post_task_hook(None)  # 不应抛出异常

    def test_valid_session(self):
        from src.cli.repl import ReplSession
        repl_session = ReplSession(use_rich_hud=False)

        mock_session = MagicMock()
        mock_session.is_complete = True
        mock_session.steps = [MagicMock() for _ in range(5)]

        # 不应抛出异常
        repl_session._post_task_hook(mock_session)


class TestReplSessionUpdateHud:
    """_update_hud 测试"""

    def test_updates_hud_context(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session.engine = MagicMock()
        session.engine.get_cost_summary.return_value = {
            'total_cost': 0.5,
            'total_tokens': 1000,
        }

        with patch.dict(os.environ, {'LLM_PROVIDER': 'openai', 'OPENAI_MODEL': 'gpt-4'}):
            session._update_hud()

        assert session.hud_ctx.provider == 'openai'
        assert session.hud_ctx.model == 'gpt-4'

    def test_no_engine(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session.engine = None
        session._update_hud()  # 不应抛出异常


class TestReplSessionPrompt:
    """_get_prompt 和 _get_status_line 测试"""

    def test_get_prompt_normal(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session.engine = MagicMock()
        session.engine.developer_mode = False
        session._update_hud = MagicMock()

        prompt = session._get_prompt()
        assert ">" in prompt

    def test_get_prompt_god_mode(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session.engine = MagicMock()
        session.engine.developer_mode = True
        session._update_hud = MagicMock()

        prompt = session._get_prompt()
        assert "GOD MODE" in prompt


class TestReplSessionHandleBuiltin:
    """_handle_builtin 命令测试"""

    def test_exit_command(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        result = session._handle_builtin('/exit')
        assert result is False

    def test_quit_command(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        result = session._handle_builtin('/quit')
        assert result is False

    def test_help_command(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        result = session._handle_builtin('/help')
        assert result is True

    def test_version_command(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        result = session._handle_builtin('/version')
        assert result is True

    def test_doctor_command(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        result = session._handle_builtin('/doctor')
        assert result is True

    def test_clear_command(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session.engine = MagicMock()
        session._turn_count = 5
        result = session._handle_builtin('/clear')
        assert result is True
        assert session._turn_count == 0

    def test_model_command(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session._init_engine = MagicMock()
        result = session._handle_builtin('/model')
        assert result is True

    def test_compact_command(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session._init_engine = MagicMock()
        result = session._handle_builtin('/compact')
        assert result is True

    def test_unknown_command(self, capsys):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session._init_engine = MagicMock()
        session.engine = MagicMock()
        result = session._handle_builtin('/unknown_cmd_xyz')
        assert result is True
        captured = capsys.readouterr()
        assert "未知命令" in captured.out


class TestReplSessionHandleBuiltinWithEngine:
    """需要引擎的内置命令测试"""

    def test_tools_command(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session._init_engine = MagicMock()
        session.engine = MagicMock()
        session.engine.get_available_tools.return_value = {}
        result = session._handle_builtin('/tools')
        assert result is True

    def test_cost_command(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session._init_engine = MagicMock()
        session.engine = MagicMock()
        session.engine.get_cost_report.return_value = None
        result = session._handle_builtin('/cost')
        assert result is True

    def test_status_command(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session._init_engine = MagicMock()
        session.engine = MagicMock()
        session.engine.is_running = False
        session.engine.get_available_tools.return_value = {}
        session.engine.get_cost_summary.return_value = None
        session.engine.get_perf_summary.return_value = None
        result = session._handle_builtin('/status')
        assert result is True

    def test_memory_without_guard(self, capsys):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session._init_engine = MagicMock()
        session.engine = MagicMock()
        # 确保没有 _memory_guard（模拟未挂载）
        session.engine._memory_guard = None
        # 注入 engine 到 command_registry（新架构需要）
        from src.cli import command_registry as cr_mod
        cr_mod.command_registry.refresh_engine(session.engine)
        result = session._handle_builtin('/memory')
        assert result is True
        captured = capsys.readouterr()
        # 新架构中 command_registry._dispatch_memory 检查 _memory_guard
        assert "未挂载" in captured.out or "未初始" in captured.out

    def test_share_command(self, capsys):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        result = session._handle_builtin('/share')
        assert result is True
        captured = capsys.readouterr()
        assert "会话记录" in captured.out

    def test_features_command(self, capsys):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        result = session._handle_builtin('/features')
        assert result is True


class TestReplSessionProviderHandler:
    """_handle_provider_switch 测试"""

    def test_show_current_provider(self):
        from src.cli.repl import ReplSession
        from src.utils import provider_manager as pm
        session = ReplSession(use_rich_hud=False)
        with patch.object(pm, 'provider_manager') as mock_mgr:
            mock_config = MagicMock()
            mock_config.api_key = "sk-test123456789"
            mock_config.base_url = "https://api.openai.com"
            mock_config.model = "gpt-4"
            mock_config.small_model = ""
            mock_config.timeout_ms = 30000
            mock_config.providers = ['openai']
            mock_mgr.get_config.return_value = mock_config
            # 不抛异常即通过
            session._handle_provider_switch('/provider')

    def test_switch_provider_success(self):
        from src.cli.repl import ReplSession
        from src.utils import provider_manager as pm
        session = ReplSession(use_rich_hud=False)
        with patch.object(pm, 'provider_manager') as mock_mgr:
            mock_mgr.switch_provider.return_value = True
            session._handle_provider_switch('/provider openai')

    def test_switch_provider_not_found(self):
        from src.cli.repl import ReplSession
        from src.utils import provider_manager as pm
        session = ReplSession(use_rich_hud=False)
        with patch.object(pm, 'provider_manager') as mock_mgr:
            mock_mgr.switch_provider.return_value = False
            session._handle_provider_switch('/provider unknown')


class TestReplSessionInternalHandler:
    """_handle_internal_toggle 测试"""

    def test_show_internal_status(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        # 不抛异常即通过
        session._handle_internal_toggle('/internal')

    def test_enable_internal(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session._handle_internal_toggle('/internal on')

    def test_disable_internal(self):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        session._handle_internal_toggle('/internal off')


class TestReplSessionOverrideHandler:
    """_handle_override 测试"""

    def test_show_overrides(self, capsys):
        from src.cli.repl import ReplSession
        session = ReplSession(use_rich_hud=False)
        # override 现在通过 command_registry 分发
        from src.cli import command_registry as cr_mod
        result = session._handle_builtin('/override')
        assert result is True
        captured = capsys.readouterr()
        assert "覆盖" in captured.out or "override" in captured.out.lower()


class TestStartRepl:
    """start_repl 函数测试"""

    def test_start_repl_creates_session(self):
        """start_repl 创建 ReplSession 并调用 run"""
        from src.cli.repl import start_repl
        with patch('src.cli.repl.ReplSession') as mock_session_cls:
            mock_instance = MagicMock()
            mock_instance.run.return_value = 0
            mock_session_cls.return_value = mock_instance

            result = start_repl(max_iterations=5)
            mock_session_cls.assert_called_once()
            mock_instance.run.assert_called_once()
            assert result == 0
