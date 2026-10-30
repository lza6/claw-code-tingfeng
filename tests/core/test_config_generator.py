"""`src/core/config/generator.py` 的真实行为测试。

覆盖：配置目录探测、技能发现与 frontmatter 解析、AGENTS.md 覆盖生成、
MCP 配置生成、features 片段、Codex config.toml 合并（dry-run / 写盘 /
用户配置优先 / 既有 TOML 损坏）、报告生成、CLI 命令与注册。

原先这里用三处 `xfail(strict=True)` 记录真实缺陷（**v0.88.4 已全部修复**，断言改为正向）：

1. `generate_tool_signatures()` 曾 import 不存在的 `src.tools_runtime.tool_manager`
   → 调用必崩。现改为**调用方注入 tools**（core 不 import 上层）；
2. `config_generate_command()` 曾调 `logger.setLevel(...)`，而 `ClawdLogger` 没这个方法
   → `clawd config generate` 100% 崩溃。现 `ClawdLogger` 已补 `setLevel()`；
3. frontmatter 写 `categories: []` 时 `[][0]` 抛 `IndexError` 被吞 → 技能**静默消失**。
   现由 `_first_category()` 处理空列表。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import toml
import typer
from typer.testing import CliRunner

import src.core.config.generator as gen_mod
from src.core.config.generator import (
    DEFAULT_MCP_SERVERS,
    DEFAULT_OMX_CONFIG,
    ConfigGenerator,
    MCPConfig,
    SkillDefinition,
    config_generate_command,
    setup_cli_commands,
)

# ==========================================================================
# 夹具：最小可用的项目目录
# ==========================================================================


def _write_skill(root: Path, dir_name: str, body: str) -> Path:
    skill_dir = root / "skills" / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    """隔离的项目根 + 隔离的 home（避免读真实 ~/.claude）。"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    root = tmp_path / "project"
    root.mkdir()
    return root


def _generator(project: Path) -> ConfigGenerator:
    return ConfigGenerator(project_root=project, claude_config_dir=project / "claude")


# ==========================================================================
# 构造与配置目录探测
# ==========================================================================


class TestConfigGeneratorInit:
    def test_defaults_derive_dirs_from_project_root(self, project):
        gen = ConfigGenerator(project_root=project, claude_config_dir=project / "cfg")

        assert gen.skills_dir == project / "skills"
        assert gen.agents_dir == project / "agents"

    def test_find_claude_config_prefers_dot_claude(self, project):
        (Path.home() / ".claude").mkdir()
        (Path.home() / ".config" / "claude").mkdir(parents=True)

        gen = ConfigGenerator(project_root=project)

        assert gen.claude_config_dir == Path.home() / ".claude"

    def test_find_claude_config_falls_back_to_config_dir(self, project):
        (Path.home() / ".config" / "claude").mkdir(parents=True)

        gen = ConfigGenerator(project_root=project)

        assert gen.claude_config_dir == Path.home() / ".config" / "claude"

    def test_find_claude_config_uses_project_clawd(self, project):
        (project / ".clawd").mkdir()

        gen = ConfigGenerator(project_root=project)

        assert gen.claude_config_dir == project / ".clawd", "本机无 ~/.claude 时应退回项目目录"

    def test_find_claude_config_last_resort_is_home_dot_claude(self, project):
        gen = ConfigGenerator(project_root=project)

        assert gen.claude_config_dir == Path.home() / ".claude"
        assert not gen.claude_config_dir.exists()


# ==========================================================================
# 技能发现与解析
# ==========================================================================


class TestDiscoverSkills:
    def test_missing_skills_dir_returns_empty(self, project):
        assert _generator(project).discover_skills() == []

    def test_parses_frontmatter_fields(self, project):
        _write_skill(
            project,
            "alpha-build",
            "---\n"
            "name: alpha\n"
            "description: builds things\n"
            "intent: implement\n"
            "tags: [core, build]\n"
            "category: engineering\n"
            "---\nbody\n",
        )

        skills = _generator(project).discover_skills()

        assert len(skills) == 1
        skill = skills[0]
        assert skill.name == "alpha"
        assert skill.description == "builds things"
        assert skill.intent == "implement"
        assert skill.tags == ["core", "build"]
        assert skill.category == "engineering"
        assert skill.filepath == project / "skills" / "alpha-build" / "SKILL.md"

    def test_category_falls_back_to_first_categories_entry(self, project):
        _write_skill(
            project,
            "beta",
            "---\nname: beta\ndescription: d\ncategories: [first, second]\n---\n",
        )

        skill = _generator(project).discover_skills()[0]

        assert skill.category == "first"

    def test_skill_without_frontmatter_uses_dir_name(self, project):
        _write_skill(project, "plain-skill", "no frontmatter at all\n")

        skill = _generator(project).discover_skills()[0]

        assert skill.name == "plain-skill", "无 frontmatter 时应回退到目录名"
        assert skill.description == ""
        assert skill.intent is None

    def test_skips_dirs_without_skill_md_and_plain_files(self, project):
        _write_skill(project, "good", "---\nname: good\n---\n")
        (project / "skills" / "empty-dir").mkdir(parents=True)
        (project / "skills" / "README.txt").write_text("x", encoding="utf-8")

        skills = _generator(project).discover_skills()

        assert [s.name for s in skills] == ["good"]

    def test_broken_yaml_is_skipped_not_raised(self, project):
        _write_skill(project, "good", "---\nname: good\n---\n")
        _write_skill(project, "broken", "---\n: : bad yaml\n---\n")

        skills = _generator(project).discover_skills()

        assert [s.name for s in skills] == ["good"], "单个技能解析失败不得影响其余技能"

    def test_discovery_order_is_deterministic(self, project):
        for name in ("c-skill", "a-skill", "b-skill"):
            _write_skill(project, name, f"---\nname: {name}\n---\n")

        first = [s.name for s in _generator(project).discover_skills()]
        second = [s.name for s in _generator(project).discover_skills()]

        assert first == second
        assert first == sorted(first)

    def test_empty_categories_list_still_discovers_skill(self, project):
        _write_skill(
            project, "gamma", "---\nname: gamma\ndescription: d\ncategories: []\n---\n"
        )

        skills = _generator(project).discover_skills()

        assert [s.name for s in skills] == ["gamma"]


# ==========================================================================
# AGENTS.md 覆盖
# ==========================================================================


class TestGenerateAgentsOverride:
    def test_dash_in_name_becomes_underscore(self):
        skills = [SkillDefinition(name="code-review", description="reviews code")]

        content = _generator(Path(".")).generate_agents_override(skills)

        assert "### code_review" in content
        assert "reviews code" in content

    def test_optional_fields_rendered_only_when_present(self):
        skills = [
            SkillDefinition(
                name="full",
                description="has everything",
                intent="deliver",
                tags=["a", "b"],
            ),
            SkillDefinition(name="bare", description=""),
        ]

        content = _generator(Path(".")).generate_agents_override(skills)

        assert "**Tags**: a, b" in content
        assert "**Intent**: deliver" in content
        assert content.count("**Tags**") == 1, "无 tags 的技能不应出现空 Tags 行"
        assert content.count("---") == 2, "每个技能后跟一条分隔线"

    def test_empty_skill_list_still_has_header(self):
        content = _generator(Path(".")).generate_agents_override([])

        assert "## Agent Roles" in content
        assert "###" not in content


# ==========================================================================
# MCP / features 片段
# ==========================================================================


class TestGenerateMcpConfig:
    def test_all_servers_include_project_pythonpath(self, project):
        servers = _generator(project).generate_mcp_config()

        assert set(servers) == set(DEFAULT_MCP_SERVERS)
        for name, cfg in servers.items():
            assert cfg["env"]["PYTHONPATH"] == str(project), f"{name} 缺少 PYTHONPATH"
            assert cfg["command"] == DEFAULT_MCP_SERVERS[name].command
            assert cfg["args"] == DEFAULT_MCP_SERVERS[name].args
            assert cfg["description"] == DEFAULT_MCP_SERVERS[name].description

    def test_removed_broken_code_intel_server_stays_removed(self, project):
        servers = _generator(project).generate_mcp_config()

        assert "clawd-code-intel" not in servers, (
            "该条目曾指向从未存在的 src.core.mcp.code_intel_server，恢复会让用户必踩启动失败"
        )

    def test_mcp_config_dataclass_defaults(self):
        cfg = MCPConfig(name="n", command="python")

        assert cfg.args == []
        assert cfg.env == {}
        assert cfg.description == ""


class TestGenerateOmxFeatures:
    def test_all_feature_flags_enabled(self, project):
        payload = _generator(project).generate_omx_features()

        flags = payload["features"]
        assert all(flags.values()), "生成的功能开关应全部为 True"
        assert set(flags) >= {
            "persistence",
            "team_mode",
            "worktree_isolation",
            "self_fission",
            "quality_gate",
            "budget_guard",
            "mcp_servers",
        }

    def test_top_level_prompt_fields_present(self, project):
        payload = _generator(project).generate_omx_features()

        assert payload["model_reasoning_effort"] == "auto"
        assert "Clawd Code" in payload["developer_instructions"]
        assert "{event}" in payload["notify"]

    def test_default_template_declares_features_section(self):
        assert "[features]" in DEFAULT_OMX_CONFIG
        assert "[mcp_servers]" in DEFAULT_OMX_CONFIG


# ==========================================================================
# 工具签名（含真实缺陷）
# ==========================================================================


class TestGenerateToolSignatures:
    """工具清单由调用方注入（core 不 import `tools_runtime`，见 core 边界治理）"""

    def test_uses_injected_tools_and_skips_broken_ones(self, project):
        class GoodTool:
            @staticmethod
            def get_signature():
                return {"name": "good", "parameters": {}}

        class BrokenTool:
            @staticmethod
            def get_signature():
                raise RuntimeError("cannot introspect")

        signatures = _generator(project).generate_tool_signatures(
            {"good": GoodTool, "broken": BrokenTool}
        )

        assert signatures == [{"name": "good", "parameters": {}}], (
            "单个工具签名失败不得中断整个收集过程"
        )

    def test_accepts_iterable_of_tools(self, project):
        class T:
            @staticmethod
            def get_signature():
                return {"name": "t", "parameters": {}}

        assert _generator(project).generate_tool_signatures([T]) == [
            {"name": "t", "parameters": {}}
        ]

    def test_empty_injection_returns_empty_list(self, project):
        assert _generator(project).generate_tool_signatures({}) == []
        assert _generator(project).generate_tool_signatures([]) == []

    def test_without_injection_returns_empty_instead_of_crashing(self, project):
        """不注入时返回 [] —— 以前是"偷偷依赖不存在的模块"直接 ModuleNotFoundError"""
        assert _generator(project).generate_tool_signatures() == []

    def test_real_registry_can_be_injected(self, project):
        """用仓库里真实的 ToolRegistry 注入，签名能真出来（打通而非只看桩）"""
        from src.tools_runtime.file_read_tool import FileReadTool
        from src.tools_runtime.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(FileReadTool())

        sigs = _generator(project).generate_tool_signatures(registry._tools)

        assert sigs, "真实注册表应有工具签名"
        first = sigs[0]
        assert first["name"] == "FileReadTool", first
        assert "file_path" in first["parameters"]["properties"], first
        assert first["parameters"]["properties"]["file_path"]["type"] == "string", first


# ==========================================================================
# Codex config.toml 合并
# ==========================================================================


class TestMergeIntoCodexConfig:
    def test_dry_run_writes_nothing(self, project):
        _write_skill(project, "s1", "---\nname: s1\ndescription: d\n---\n")
        gen = _generator(project)

        merged = gen.merge_into_codex_config(dry_run=True)

        assert merged["features"]["persistence"] is True
        assert not (project / "claude" / "config.toml").exists()
        assert not (project / ".clawd" / "AGENTS.md").exists()

    def test_writes_config_and_agents_override(self, project):
        _write_skill(project, "s1", "---\nname: s1\ndescription: does s1\n---\n")
        gen = _generator(project)

        gen.merge_into_codex_config()

        config_path = project / "claude" / "config.toml"
        agents_path = project / ".clawd" / "AGENTS.md"
        assert config_path.exists() and agents_path.exists()

        parsed = toml.load(config_path)
        assert parsed["model_reasoning_effort"] == "auto"
        assert "clawd-state" in parsed["mcp_servers"], "默认 MCP 服务器必须落盘"
        assert "s1" in agents_path.read_text(encoding="utf-8")

    def test_existing_user_config_wins_over_generated_defaults(self, project):
        config_path = project / "claude" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            '[features]\npersistence = false\n\n[model]\nname = "mine"\n', encoding="utf-8"
        )

        merged = _generator(project).merge_into_codex_config(dry_run=True)

        # 合并是**浅合并**：用户只要写了 [features]，整个 features 表就以用户为准
        assert merged["features"] == {"persistence": False}
        assert merged["model"] == {"name": "mine"}

    def test_existing_custom_mcp_server_preserved(self, project):
        config_path = project / "claude" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            '[mcp_servers.mine]\ncommand = "my-binary"\n', encoding="utf-8"
        )

        merged = _generator(project).merge_into_codex_config(dry_run=True)

        assert merged["mcp_servers"]["mine"]["command"] == "my-binary"
        assert "clawd-state" in merged["mcp_servers"], "用户既有配置不得阻止默认服务器补齐"

    def test_corrupted_existing_toml_does_not_abort(self, project):
        config_path = project / "claude" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("this is not toml = = =\n", encoding="utf-8")

        merged = _generator(project).merge_into_codex_config(dry_run=True)

        assert merged["features"]["persistence"] is True, "读到坏配置应降级为生成全新配置"
        assert "clawd-state" in merged["mcp_servers"]

    def test_corrupted_existing_config_is_overwritten_on_real_run(self, project):
        config_path = project / "claude" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("broken = = =\n", encoding="utf-8")

        _generator(project).merge_into_codex_config()

        parsed = toml.load(config_path)
        assert parsed["model_reasoning_effort"] == "auto"

    def test_default_config_path_is_claude_config_dir(self, project):
        gen = _generator(project)

        gen.merge_into_codex_config()

        assert (gen.claude_config_dir / "config.toml").exists()


# ==========================================================================
# 报告
# ==========================================================================


class TestGenerateReport:
    def test_report_contains_counts_and_next_steps(self, project):
        gen = _generator(project)
        skills = [
            SkillDefinition(name="s1", description="first"),
            SkillDefinition(name="s2", description="second"),
        ]
        config = {
            "mcp_servers": {"a": {}, "b": {}},
            "features": {"persistence": True},
        }

        report = gen._generate_report(skills, config, dry_run=True)

        assert "发现技能: 2 个" in report
        assert "  - s1: first..." in report
        assert "MCP 服务器: 2 个" in report
        assert "  - persistence: True" in report
        assert "Dry-run: True" in report
        assert "clawd chat" in report

    def test_report_truncates_long_descriptions(self, project):
        gen = _generator(project)
        long_desc = "x" * 200

        report = gen._generate_report(
            [SkillDefinition(name="s", description=long_desc)], {}, dry_run=False
        )

        assert "x" * 61 not in report
        assert "x" * 60 + "..." in report


# ==========================================================================
# CLI 命令
# ==========================================================================


class TestConfigGenerateCommand:
    def test_dry_run_prints_preview(self, project, monkeypatch, capsys):
        monkeypatch.chdir(project)
        # 缺陷根因见下方 xfail：这里换成真实 stdlib logger，使命令其余逻辑可被测
        import logging as std_logging

        monkeypatch.setattr(gen_mod, "logger", std_logging.getLogger("cfg-test"))

        config_generate_command(dry_run=True)

        out = capsys.readouterr().out
        assert "[预览模式]" in out
        assert "features" in out
        assert not (project / ".clawd" / "AGENTS.md").exists(), "dry-run 不得落盘"

    def test_failure_is_logged_and_reraised(self, project, monkeypatch):
        import logging as std_logging

        monkeypatch.setattr(gen_mod, "logger", std_logging.getLogger("cfg-test"))
        monkeypatch.setattr(
            ConfigGenerator,
            "merge_into_codex_config",
            lambda self, **kw: (_ for _ in ()).throw(ValueError("boom")),
        )

        with pytest.raises(ValueError, match="boom"):
            config_generate_command(dry_run=True)

    def test_verbose_sets_debug_level(self, project, monkeypatch):
        import logging as std_logging

        test_logger = std_logging.getLogger("cfg-verbose-test")
        test_logger.setLevel(std_logging.WARNING)
        monkeypatch.setattr(gen_mod, "logger", test_logger)
        monkeypatch.chdir(project)

        config_generate_command(dry_run=True, verbose=True)

        assert test_logger.level == std_logging.DEBUG

    def test_command_runs_with_real_logger(self, project, monkeypatch):
        """真 logger（ClawdLogger）下命令能跑通 —— v0.88.4 给它补了 setLevel()"""
        monkeypatch.chdir(project)

        config_generate_command(dry_run=True)


class TestSetupCliCommands:
    def _app(self) -> typer.Typer:
        app = typer.Typer()
        setup_cli_commands(app)
        return app

    def test_registers_both_commands(self):
        app = self._app()

        names = {
            cmd.name or (cmd.callback.__name__ if cmd.callback else "")
            for cmd in app.registered_commands
        }

        assert any("config-generate" in (n or "") for n in names)
        assert any("config-show" in (n or "") for n in names)

    def test_config_show_reports_missing_file(self, project, monkeypatch):
        monkeypatch.chdir(project)
        runner = CliRunner()

        result = runner.invoke(self._app(), ["config-show"])

        assert result.exit_code == 0
        assert "配置文件不存在" in result.stdout

    def test_config_show_prints_existing_file(self, project, monkeypatch):
        (Path.home() / ".claude").mkdir()
        config_path = Path.home() / ".claude" / "config.toml"
        config_path.write_text('model_reasoning_effort = "high"\n', encoding="utf-8")
        monkeypatch.chdir(project)
        runner = CliRunner()

        result = runner.invoke(self._app(), ["config-show"])

        assert result.exit_code == 0
        assert 'model_reasoning_effort = "high"' in result.stdout

    def test_config_generate_cli_forwards_options(self, project, monkeypatch):
        """`--dry-run` 必须一路传到 config_generate_command（否则会意外写盘）。"""
        import logging as std_logging

        monkeypatch.setattr(gen_mod, "logger", std_logging.getLogger("cfg-cli-test"))
        monkeypatch.chdir(project)
        runner = CliRunner()

        result = runner.invoke(self._app(), ["config-generate", "--dry-run"])

        assert result.exit_code == 0
        assert "[预览模式]" in result.stdout
        assert not (project / ".clawd" / "AGENTS.md").exists()


# ==========================================================================
# P3-1：工具签名必须有**生产**调用方（CLI 注入 → 落盘 / dry-run 只回传）
#
# 此前 `generate_tool_signatures()` 实现正确、也有测试，但除测试外零调用方 ——
# 等于"能力存在但从不运行"。现在由 CLI 层注入真实工具清单：
# 非 dry-run 落 tool_signatures.json，dry-run 放回返回 dict 的独立键。
# ==========================================================================


class _FakeTool:
    """最小工具桩：走 `_tool_signature` 的通用分支（name + parameter_schemas）"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"{name} 描述"
        self.parameter_schemas: tuple = ()


class TestToolSignaturesHaveProductionCaller:
    def test_signatures_land_in_tool_signatures_json(self, project):
        gen = _generator(project)
        sigs = gen.generate_tool_signatures([_FakeTool("BashTool"), _FakeTool("FileReadTool")])

        gen.merge_into_codex_config(tool_signatures=sigs)

        path = project / "claude" / "tool_signatures.json"
        assert path.is_file(), "非 dry-run 应把签名写进目标配置目录"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert [s["name"] for s in data] == ["BashTool", "FileReadTool"], data

        # config.toml 是 codex 的配置，签名绝不能混进去（污染用户配置）
        cfg = toml.load(project / "claude" / "config.toml")
        assert gen_mod.TOOL_SIGNATURES_PREVIEW_KEY not in cfg, cfg.keys()
        assert "tool_signatures" not in cfg, cfg.keys()

    def test_dry_run_keeps_signatures_in_returned_dict_only(self, project):
        gen = _generator(project)
        sigs = gen.generate_tool_signatures([_FakeTool("GlobTool")])

        merged = gen.merge_into_codex_config(dry_run=True, tool_signatures=sigs)

        assert not (project / "claude" / "tool_signatures.json").exists(), "dry-run 不许落盘"
        assert not (project / "claude" / "config.toml").exists()
        preview = merged[gen_mod.TOOL_SIGNATURES_PREVIEW_KEY]
        assert [s["name"] for s in preview] == ["GlobTool"], preview

    def test_report_counts_signatures(self, project):
        gen = _generator(project)

        assert "工具签名: 2 个" in gen._generate_report(
            [], {}, True, tool_signatures=[{"name": "a"}, {"name": "b"}]
        ), "报告必须写出签名数量"
        assert "工具签名: 0 个" in gen._generate_report([], {}, True)

    def test_command_without_tools_reports_zero_and_writes_no_file(
        self, project, monkeypatch, capsys
    ):
        """不注入工具清单时：配置照常生成，但签名如实报 0，不写空文件、不假造"""
        monkeypatch.chdir(project)
        config_path = project / "claude" / "config.toml"

        config = config_generate_command(config_path=config_path, tools=None)

        assert config_path.is_file(), "配置本身仍应正常写出"
        assert not (project / "claude" / "tool_signatures.json").exists()
        assert gen_mod.TOOL_SIGNATURES_PREVIEW_KEY not in config
        # 状态行走 stderr（stdout 留给 `--json`），但必须如实说 0
        captured = capsys.readouterr()
        assert "工具签名: 0 个" in captured.err, captured.err
        assert captured.out == "", "stdout 必须干净（--json | jq 依赖它）"

    def test_command_with_tools_writes_signature_file(self, project, monkeypatch):
        monkeypatch.chdir(project)
        config_path = project / "claude" / "config.toml"

        config = config_generate_command(config_path=config_path, tools=[_FakeTool("BashTool")])

        data = json.loads(
            (project / "claude" / "tool_signatures.json").read_text(encoding="utf-8")
        )
        assert [s["name"] for s in data] == ["BashTool"], data
        assert gen_mod.TOOL_SIGNATURES_PREVIEW_KEY not in config
