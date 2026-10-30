"""CLI 命令注册回归测试。

## 背景（三个真实缺陷）

`src/cli/entrypoint.py` 的 `_register_command_modules()` 用
`try: ... except ImportError: pass` 包裹三处导入。这本意是"可选模块缺失时
优雅降级"，实际却把一个**硬错误**吞成了静默失败：

    src/cli/commands/agent_commands.py:16
        from ...agent.keyword_registry import get_registered_keywords
        # 该函数在 keyword_registry 中根本不存在（现名 get_all_keywords）

    src/cli/commands/workflow_commands.py:18
        from ...workflow.pipeline_orchestrator import create_ralph_verify_stage
        # 三个 stage 工厂定义在 workflow.pipeline，不在 pipeline_orchestrator

    src/cli/hud_improved.py:20
        from ...core.notifications.dispatcher import ...
        # 模块深度是 src.cli（2 层），`...` 上溯 3 层 → 越过顶层包

后果：`agent` 与 `workflow` 两个命令组（7 个命令）**整体未注册**，
`clawd agent --help` / `clawd workflow --help` 直接不可用，
而 CLI 启动无任何报错。

## 本测试的立场

不是"验证导入能过"这种弱断言，而是**直接断言命令真的注册进了 Typer app**。
导入能过但命令没挂上，同样是不合格。
"""

from __future__ import annotations

import importlib

import pytest


class TestAgentCommandsRegister:
    def test_module_imports(self):
        importlib.import_module("src.cli.commands.agent_commands")

    def test_keywords_command_is_registered(self):
        """`agent keywords` 必须出现在 CLI 里"""
        mod = importlib.import_module("src.cli.commands.agent_commands")
        names = {c.name or c.callback.__name__ for c in mod.app.registered_commands}
        assert "keywords" in names, f"实际注册的命令: {sorted(names)}"

    def test_keywords_command_runs_and_lists_registry(self, capsys):
        """命令本体可执行，且输出真实的注册表内容

        这一条覆盖改名后的语义：`get_registered_keywords()` 曾返回
        `dict[str, str]`（keyword → skill），现名 `get_all_keywords()`
        只返回 `list[str]`。命令体必须按新签名重写，而不是简单改个名字。
        """
        mod = importlib.import_module("src.cli.commands.agent_commands")
        cmd = next(c for c in mod.app.registered_commands if (c.name or "") == "keywords")
        # 显式传 json_out=False：直接调 callback 时默认值是 OptionInfo 对象（真值为 True），
        # 会误走进 `--json` 分支（v0.89.0 起该命令支持 --json），这里测的是人读渲染。
        cmd.callback(json_out=False)

        out = capsys.readouterr().out
        # 注册表里的关键词必须真的渲染出来
        from src.agent.keyword_registry import get_all_keywords

        kws = get_all_keywords()
        assert kws, "关键词注册表为空，测试前提不成立"
        assert kws[0] in out, f"关键词 '{kws[0]}' 未出现在输出中"


class TestWorkflowCommandsRegister:
    def test_module_imports(self):
        importlib.import_module("src.cli.commands.workflow_commands")

    def test_all_four_commands_registered(self):
        """workflow 组必须真的挂上 4 个命令。

        命令名以实际注册为准（ralph / ralplan / team / autopilot）——
        不要凭空假设名字，写错名字的测试会在实现改名后失去意义。
        """
        mod = importlib.import_module("src.cli.commands.workflow_commands")
        names = {c.name or c.callback.__name__ for c in mod.app.registered_commands}
        assert names == {"ralph", "ralplan", "team", "autopilot"}, (
            f"实际注册: {sorted(names)}"
        )


class TestHudImports:
    def test_hud_improved_imports(self):
        importlib.import_module("src.cli.hud_improved")

    def test_get_hud_symbol_exists(self):
        mod = importlib.import_module("src.cli.hud_improved")
        assert hasattr(mod, "get_hud")


class TestEntrypointRegistersBothGroups:
    """端到端：走生产入口的注册流程，确认命令组真的挂上了。

    这是本缺陷的**唯一有效验收方式** —— 单测模块能导入还不够，
    必须验证 `_register_command_modules()` 这条装配路径不再静默吞掉它们。
    """

    def _collect(self, app) -> list[str]:
        names: list[str] = []
        for group in app.registered_groups:
            names.append(group.name or "")
            sub = group.typer_instance
            for c in sub.registered_commands:
                names.append(f"{group.name}.{c.name or c.callback.__name__}")
        return names

    def test_agent_and_workflow_groups_present(self):
        entry = importlib.import_module("src.cli.entrypoint")
        entry._register_command_modules()
        names = self._collect(entry.app)

        assert any(n.startswith("agent.") for n in names), (
            f"agent 命令组未注册。已注册组: {sorted(set(names))}"
        )
        assert any(n.startswith("workflow.") for n in names), (
            f"workflow 命令组未注册。已注册组: {sorted(set(names))}"
        )


class TestNoSilentImportSwallow:
    """静默吞掉 ImportError 是这批缺陷能长期隐藏的直接原因。

    降级本身是合理需求（可选模块缺失不该让 CLI 起不来），但**降级必须可观测**。
    这条断言把"零失败"钉住：任何命令组注册失败都会让本测试变红。
    """

    def test_no_command_group_failed_to_register(self):
        """全部命令组都必须注册成功。

        这是对根因的护栏 —— 只修好当前三个模块而不改掉 `except: pass`，
        下一个改名导致的断链还会静默消失。
        """
        entry = importlib.import_module("src.cli.entrypoint")
        failures = entry._register_command_modules()
        assert failures == [], f"以下命令组注册失败: {failures}"

    def test_import_failure_is_reported_not_silent(self, monkeypatch):
        """整体导入失败时，必须报出失败的组名。

        反例（本次修复前的写法）：失败分支返回空列表，
        于是 `failures == []` 在最坏情况下也成立 —— 断言被自己的实现骗过。
        """
        entry = importlib.import_module("src.cli.entrypoint")

        def boom():
            raise ImportError("simulated total failure")

        monkeypatch.setattr(entry, "_load_command_modules", boom)
        monkeypatch.setattr(entry, "_REGISTERED_GROUPS", set())

        failures = entry._register_command_modules()
        assert failures, "整体导入失败却返回空失败清单 —— 回归断言会假通过"
        assert set(failures) == set(entry._COMMAND_GROUP_NAMES)

    def test_all_declared_groups_present_in_app(self):
        """清单里声明的每个组都必须真的出现在 app 上"""
        entry = importlib.import_module("src.cli.entrypoint")
        entry._register_command_modules()
        present = {g.name for g in entry.app.registered_groups}
        declared = {name for name, _m, _f in entry._load_command_modules()}
        assert declared <= present, f"缺失: {declared - present}；实际: {sorted(present)}"

    def test_registration_is_idempotent(self):
        """重复调用不得产生重复组。

        模块导入时调一次、`main()` 里又调一次；缺护栏时
        `app.registered_groups` 会出现同名重复项（实测 8 项 / 4 个名字）。
        """
        entry = importlib.import_module("src.cli.entrypoint")
        for _ in range(3):
            entry._register_command_modules()
        names = [g.name for g in entry.app.registered_groups]
        assert len(names) == len(set(names)), f"出现重复组: {names}"

    def test_run_command_is_not_shadowed_by_workflow_group(self):
        """`run`（5 阶段引擎）与 `workflow`（命令组）不得同名。

        历史缺陷：顶层命令曾叫 `workflow`，与同名命令组共存时被组遮蔽，
        `clawd workflow "目标"` 会把目标当子命令解析，永远跑不到引擎。
        """
        entry = importlib.import_module("src.cli.entrypoint")
        entry._register_command_modules()
        commands = {c.name for c in entry.app.registered_commands}
        groups = {g.name for g in entry.app.registered_groups}
        assert "run" in commands
        assert not (commands & groups), f"命令与命令组重名: {commands & groups}"

    @pytest.mark.parametrize(
        "modname",
        [
            "src.cli.commands.agent_commands",
            "src.cli.commands.workflow_commands",
            "src.cli.commands.catalog_commands",
            "src.cli.commands.setup_commands",
            "src.cli.hud_improved",
        ],
    )
    def test_module_importable_standalone(self, modname):
        """这些模块必须能被独立导入 —— 这是它们不该被 except 吞掉的前提"""
        importlib.import_module(modname)
