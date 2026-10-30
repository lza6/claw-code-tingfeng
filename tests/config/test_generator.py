"""`src/config/generator.py` 的真实行为测试。

本文件覆盖配置合并流水线的每一层（顶层键解析 → 清理 → upsert → 组装 →
落盘 → 修复），断言的是**真实输出字符串**，而不是"函数被调用过"。

三条 `xfail(strict=True)` 用例记录了本轮测试发现的真实缺陷（`src/` 未修改）：

1. 用户自定义的顶层 `model` 每次合并都会被重置为默认模型
   （`src/config/generator.py:622` 先删 `model`，`:566` 的保留分支因此变成死代码）；
2. `build_merged_config()` 不幂等：每合并一次都会多留一行头部注释与一行
   `# ======` 分隔符（`_strip_existing_omx_blocks` / `_get_root_level_lines`）；
3. `_upsert_tui_status_line()` 只合并第一个 `[tui]`，第二个原样留在输出里
   （`:344`–`:363`），直接调用会产出重复 TOML 表头。
"""

from __future__ import annotations

import pytest

from src.config.generator import (
    DEFAULT_STANDARD_MODEL,
    DEFAULT_TUI_STATUS_LINE,
    OMX_CONFIG_END_MARKER,
    OMX_CONFIG_MARKER,
    ConfigMergeResult,
    McpServerConfig,
    _get_omx_tables_block,
    _get_root_level_lines,
    _is_legacy_omx_agent_section,
    _parse_root_key_values,
    _strip_existing_omx_blocks,
    _strip_orphaned_managed_notify,
    _strip_orphaned_omx_sections,
    _strip_root_level_keys,
    _unwrap_toml_string,
    _upsert_agents_settings,
    _upsert_env_settings,
    _upsert_feature_flags,
    _upsert_tui_status_line,
    build_merged_config,
    merge_config,
    repair_config_if_needed,
)

# ==========================================================================
# 数据结构
# ==========================================================================


class TestDataclasses:
    def test_mcp_server_config_defaults(self):
        server = McpServerConfig(name="s", command="node", args=["a.js"])

        assert server.enabled is True, "MCP 服务器默认应启用"
        assert server.startup_timeout_sec is None

    def test_config_merge_result_fields(self):
        result = ConfigMergeResult(
            final_config="x", had_existing_omx=True, stripped_blocks=2, added_keys=["model"]
        )

        assert result.stripped_blocks == 2
        assert result.added_keys == ["model"]


# ==========================================================================
# 顶层键解析
# ==========================================================================


class TestParseRootKeyValues:
    def test_parses_keys_before_first_table(self):
        config = 'model = "m"\nnotify = ["node","x"]\n[t]\na = 1\n'

        values = _parse_root_key_values(config)

        assert values == {"model": '"m"', "notify": '["node","x"]'}, "只应收集第一个 table 之前的键"

    def test_stops_at_first_table_header(self):
        config = "[features]\nmulti_agent = true\n"

        assert _parse_root_key_values(config) == {}

    def test_ignores_comments_and_blank_lines(self):
        config = '# comment\n\nmodel = "m"\n'

        assert _parse_root_key_values(config) == {"model": '"m"'}

    def test_ignores_malformed_lines(self):
        config = 'this is not a kv\nmodel = "m"\n'

        assert _parse_root_key_values(config) == {"model": '"m"'}

    def test_empty_config(self):
        assert _parse_root_key_values("") == {}


class TestUnwrapTomlString:
    def test_strips_double_quotes(self):
        assert _unwrap_toml_string('"claude-sonnet"') == "claude-sonnet"

    def test_keeps_bare_value(self):
        assert _unwrap_toml_string("42") == "42"

    def test_none_passthrough(self):
        assert _unwrap_toml_string(None) is None


class TestStripRootLevelKeys:
    def test_removes_only_top_level_occurrences(self):
        config = 'model = "m"\nkeep = 1\n[t]\nmodel = "inner"\n'

        result = _strip_root_level_keys(config, ["model"])

        assert result == 'keep = 1\n[t]\nmodel = "inner"', "table 内的同名键必须保留"

    def test_removes_multiple_keys(self):
        config = "notify = 1\nmodel = 2\nkeep = 3\n"

        result = _strip_root_level_keys(config, ["notify", "model"])

        assert result == "keep = 3"

    def test_noop_when_key_absent(self):
        assert _strip_root_level_keys("keep = 1\n", ["model"]) == "keep = 1"

    def test_handles_indented_key(self):
        assert _strip_root_level_keys('   model = "m"\nkeep = 1\n', ["model"]) == "keep = 1"


class TestStripOrphanedManagedNotify:
    def test_removes_omx_notify_line(self):
        config = 'a = 1\nnotify = ["node", "/x/notify-hook.js"]\nb = 2\n'

        result = _strip_orphaned_managed_notify(config)

        assert "notify-hook.js" not in result
        assert result == "a = 1\nb = 2"

    def test_keeps_user_notify_with_other_program(self):
        config = 'notify = ["slack", "/usr/bin/slack-notify"]\n'

        result = _strip_orphaned_managed_notify(config)

        assert 'notify = ["slack", "/usr/bin/slack-notify"]' in result

    def test_collapses_extra_blank_lines(self):
        config = 'a = 1\nnotify = ["node", "hook/notify-hook.js"]\n\n\n\nb = 2\n'

        result = _strip_orphaned_managed_notify(config)

        assert "\n\n\n" not in result
        assert result == "a = 1\n\nb = 2"


# ==========================================================================
# [features] / [env] / [agents] upsert
# ==========================================================================


class TestUpsertFeatureFlags:
    def test_empty_config_gets_block(self):
        assert _upsert_feature_flags("") == (
            "[features]\nmulti_agent = true\nchild_agents_md = true\n\n"
        )

    def test_appends_block_when_section_missing(self):
        result = _upsert_feature_flags("a = 1")

        assert result == "a = 1\n\n[features]\nmulti_agent = true\nchild_agents_md = true\n\n"

    def test_drops_deprecated_collab_flag(self):
        result = _upsert_feature_flags("[features]\ncollab = true\nother = 1\n")

        assert "collab" not in result, "已废弃的 collab 标志必须被移除"
        assert result == "[features]\nother = 1\nmulti_agent = true\nchild_agents_md = true"

    def test_keeps_existing_managed_flags(self):
        config = "[features]\nmulti_agent = true\nchild_agents_md = true\n"

        result = _upsert_feature_flags(config)

        assert result == "[features]\nmulti_agent = true\nchild_agents_md = true"
        assert result.count("multi_agent") == 1, "不得重复插入"

    def test_does_not_escape_into_next_table(self):
        config = "[features]\ncollab = true\n\n[tui]\nx = 1\n"

        result = _upsert_feature_flags(config)

        assert result == "[features]\n\nmulti_agent = true\nchild_agents_md = true\n[tui]\nx = 1"


class TestUpsertEnvSettings:
    def test_appends_env_block_when_missing(self):
        result = _upsert_env_settings("")

        assert result == '\n\n[env]\nUSE_OMX_EXPLORE_CMD = "1"\n'

    def test_inserts_into_existing_env_section(self):
        result = _upsert_env_settings('[env]\nFOO = "bar"\n')

        assert result == '[env]\nFOO = "bar"\nUSE_OMX_EXPLORE_CMD = "1"'

    def test_preserves_user_value(self):
        result = _upsert_env_settings('[env]\nUSE_OMX_EXPLORE_CMD = "0"\n')

        assert result == '[env]\nUSE_OMX_EXPLORE_CMD = "0"', "用户显式关闭时必须保留"
        assert result.count("USE_OMX_EXPLORE_CMD") == 1


class TestUpsertAgentsSettings:
    def test_appends_agents_block_when_missing(self):
        result = _upsert_agents_settings("")

        assert result == "\n\n[agents]\nmax_threads = 6\nmax_depth = 2\n\n"

    def test_fills_missing_max_depth(self):
        result = _upsert_agents_settings("[agents]\nmax_threads = 1\n")

        assert result == "[agents]\nmax_threads = 1\nmax_depth = 2", (
            "已有用户值不得被覆盖，只补缺失键"
        )

    def test_keeps_both_existing_values(self):
        result = _upsert_agents_settings("[agents]\nmax_threads = 1\nmax_depth = 1\n")

        assert result == "[agents]\nmax_threads = 1\nmax_depth = 1"
        assert result.count("max_threads") == 1

    def test_inserts_inside_section_before_following_table(self):
        """新键必须落在 [agents] 段内，而不是被塞到下一个表之后。

        这是纯字符串拼接最容易出错的地方：段边界算错就会把键写进
        别人的表（TOML 里等于改了另一个 section 的配置）。
        """
        config = "[agents]\nmax_depth = 1\n\n[tui]\ntheme = \"x\"\n"

        result = _upsert_agents_settings(config)

        agents_section = result.split("[tui]")[0]
        assert "max_threads = 6" in agents_section, "max_threads 必须落在 [agents] 段内"
        assert result.split("[tui]")[1] == '\ntheme = "x"', "下一个表的内容不得被改动"


# ==========================================================================
# [tui] 状态行
# ==========================================================================


class TestUpsertTuiStatusLine:
    def test_include_tui_false_returns_input_unchanged(self):
        config = '[tui]\ntheme = "dark"\n'

        result, had_tui = _upsert_tui_status_line(config, include_tui=False)

        assert result == config
        assert had_tui is False

    def test_no_tui_section_reports_false(self):
        result, had_tui = _upsert_tui_status_line("[model]\nx = 1\n")

        assert result == "[model]\nx = 1\n"
        assert had_tui is False

    def test_preserves_user_keys_and_replaces_status_line(self):
        config = '[model]\nx = 1\n\n[tui]\ntheme = "dark"\nstatus_line = ["old"]\n'

        result, had_tui = _upsert_tui_status_line(config)

        assert had_tui is True
        assert result.count("[tui]") == 1
        assert 'theme = "dark"' in result, "用户自定义 TUI 键必须保留"
        assert DEFAULT_TUI_STATUS_LINE in result
        assert '["old"]' not in result, "旧 status_line 必须被替换"
        assert result.endswith("\n")

    def test_blank_line_inserted_before_merged_section(self):
        config = '[model]\nx = 1\n[tui]\na = "b"\n'

        result, _ = _upsert_tui_status_line(config)

        assert "[model]\nx = 1\n\n[tui]" in result, "合并后的 [tui] 前应有空行分隔"

    def test_deduplicates_keys_across_sections(self):
        config = '[tui]\na = 1\n[tui]\na = 2\nb = 3\n'

        result, had_tui = _upsert_tui_status_line(config)

        assert had_tui is True
        # 第一个 [tui] 的键优先（seen_keys 去重），b 从第二个补进来
        assert "a = 1\nb = 3\n" in result
        assert "a = 2" in result, (
            "缺陷标记 src/config/generator.py:350-363 —— 第二个 [tui] 段被原样追加，"
            "本次断言只锁定当前真实行为"
        )

    def test_skips_comments_and_non_kv_lines(self):
        config = '[tui]\n# 用户注释\ngarbage line without equals\ntheme = "dark"\n'

        result, had_tui = _upsert_tui_status_line(config)

        assert had_tui is True
        assert 'theme = "dark"' in result, "注释与非法行应被跳过，合法键仍要保留"
        assert "# 用户注释" not in result
        assert "garbage line without equals" not in result

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "缺陷 src/config/generator.py:344-363：_upsert_tui_status_line 只替换第一个 "
            "[tui]，第二个重复表头被原样保留，输出非法 TOML（同一文件已有两个 [tui]）"
        ),
    )
    def test_duplicate_tui_sections_collapse_to_one(self):
        config = '[tui]\na = 1\n[tui]\nb = 3\n'

        result, _ = _upsert_tui_status_line(config)

        assert result.count("[tui]") == 1


# ==========================================================================
# OMX 区块清理
# ==========================================================================


class TestStripExistingOmxBlocks:
    def test_noop_without_marker(self):
        cleaned, removed = _strip_existing_omx_blocks("a = 1\n")

        assert cleaned == "a = 1\n"
        assert removed == 0

    def test_removes_block_between_markers(self):
        config = (
            "# ============\n"
            f"{OMX_CONFIG_MARKER}\n[tui]\nx = 1\n{OMX_CONFIG_END_MARKER}\ntail = 1\n"
        )

        cleaned, removed = _strip_existing_omx_blocks(config)

        assert removed == 1
        assert OMX_CONFIG_MARKER not in cleaned
        assert "[tui]" not in cleaned, "受管区块内的表必须一并移除"
        assert "tail = 1" in cleaned

    def test_block_without_end_marker_removes_rest(self):
        config = f"a = 1\n{OMX_CONFIG_MARKER}\n[tui]\nx = 1\n"

        cleaned, removed = _strip_existing_omx_blocks(config)

        assert removed == 1
        assert cleaned == "a = 1"

    def test_only_block_leaves_empty_string(self):
        config = f"{OMX_CONFIG_MARKER}\n[tui]\nx = 1\n{OMX_CONFIG_END_MARKER}\n"

        cleaned, removed = _strip_existing_omx_blocks(config)

        assert removed == 1
        assert cleaned == ""

    def test_end_marker_at_eof_without_newline(self):
        """结束标记正好是文件结尾（无换行）时也要整块删掉。"""
        config = f"a = 1\n{OMX_CONFIG_MARKER}\n[tui]\nx = 1\n{OMX_CONFIG_END_MARKER}"

        cleaned, removed = _strip_existing_omx_blocks(config)

        assert removed == 1
        assert cleaned == "a = 1"

    def test_counts_multiple_blocks(self):
        config = (
            f"{OMX_CONFIG_MARKER}\n[tui]\na = 1\n{OMX_CONFIG_END_MARKER}\n"
            "mid = 1\n"
            f"{OMX_CONFIG_MARKER}\n[tui]\nb = 2\n{OMX_CONFIG_END_MARKER}\n"
        )

        cleaned, removed = _strip_existing_omx_blocks(config)

        assert removed == 2
        assert cleaned == "mid = 1"


class TestLegacyAgentSection:
    def test_known_agent_plain_name(self):
        assert _is_legacy_omx_agent_section("agents.executor") is True

    def test_known_agent_quoted_name(self):
        assert _is_legacy_omx_agent_section('agents."code-reviewer"') is True

    def test_unknown_agent_name(self):
        assert _is_legacy_omx_agent_section("agents.my-own-agent-zzz") is False

    def test_non_agent_table(self):
        assert _is_legacy_omx_agent_section("mcp_servers.omx_state") is False


class TestStripOrphanedOmxSections:
    def test_removes_managed_tables(self):
        config = (
            "keep = 1\n"
            "[mcp_servers.omx_state]\ncommand = \"node\"\n"
            "[agents.executor]\nmodel = \"m\"\n"
            "[tui]\na = 1\n"
            "[other]\nb = 2\n"
        )

        result = _strip_orphaned_omx_sections(config)

        assert result == "keep = 1\n[other]\nb = 2", "只保留非受管表"

    def test_removes_preceding_omx_comment(self):
        config = "keep = 1\n\n# OMX state server\n[mcp_servers.omx_memory]\ncommand = \"node\"\n"

        result = _strip_orphaned_omx_sections(config)

        assert result == "keep = 1"
        assert "OMX state server" not in result

    def test_keeps_user_mcp_servers(self):
        result = _strip_orphaned_omx_sections('[mcp_servers.mine]\ncommand = "python"\n')

        assert result == '[mcp_servers.mine]\ncommand = "python"', "非 omx_ 前缀的 MCP 服务器必须保留"


# ==========================================================================
# 表区块与顶层行生成
# ==========================================================================


class TestOmxTablesBlock:
    def test_contains_all_managed_mcp_servers(self):
        block = _get_omx_tables_block("pkg")

        for server in (
            "omx_state",
            "omx_memory",
            "omx_code_intel",
            "omx_trace",
            "omx_team_run",
        ):
            assert f"[mcp_servers.{server}]" in block
        assert block.count(OMX_CONFIG_END_MARKER) == 1

    def test_paths_are_built_from_package_root(self):
        block = _get_omx_tables_block("myroot")

        assert "state-server.js" in block
        assert "myroot" in block.replace("\\", "/") or "myroot" in block

    def test_include_tui_toggle(self):
        with_tui = _get_omx_tables_block("pkg", include_tui=True)
        without_tui = _get_omx_tables_block("pkg", include_tui=False)

        assert "[tui]" in with_tui
        assert DEFAULT_TUI_STATUS_LINE in with_tui
        assert "[tui]" not in without_tui


class TestRootLevelLines:
    def test_defaults_to_standard_model_when_absent(self):
        lines = _get_root_level_lines("pkg", "")

        assert f'model = "{DEFAULT_STANDARD_MODEL}"' in lines
        assert 'model_reasoning_effort = "high"' in lines
        assert any(line.startswith("developer_instructions = ") for line in lines)

    def test_model_override_wins(self):
        lines = _get_root_level_lines("pkg", 'model = "user-model"\n', model_override="forced")

        assert 'model = "forced"' in lines

    def test_existing_model_kept_without_duplicate_line(self):
        lines = _get_root_level_lines("pkg", 'model = "user-model"\n')

        model_lines = [line for line in lines if line.startswith("model =")]
        assert model_lines == [], (
            "调用方已保留原 model 行时不得再写一条（否则 TOML 出现重复键）"
        )


# ==========================================================================
# build_merged_config（端到端字符串契约）
# ==========================================================================


class TestBuildMergedConfig:
    def test_empty_config_produces_complete_document(self):
        merged = build_merged_config("", "pkg")

        assert merged.startswith("# Clawd Code top-level settings")
        assert f'model = "{DEFAULT_STANDARD_MODEL}"' in merged
        assert "[features]" in merged
        assert "[env]" in merged
        assert "[agents]" in merged
        assert "[mcp_servers.omx_state]" in merged
        assert "[tui]" in merged
        assert merged.endswith("\n")

    def test_top_level_keys_precede_every_table(self):
        merged = build_merged_config('custom_top = 1\n[t]\nx = 1\n', "pkg")

        first_table = merged.index("\n[")
        assert merged.index("custom_top = 1") < first_table, (
            "顶层键必须位于任何 [table] 之前，否则 TOML 会把它归到上一个表"
        )

    def test_user_tables_survive(self):
        merged = build_merged_config('[my_plugin]\nurl = "http://x"\n', "pkg")

        assert '[my_plugin]\nurl = "http://x"' in merged

    def test_user_feature_kept_and_collab_dropped(self):
        merged = build_merged_config("[features]\ncollab = true\nmine = true\n", "pkg")

        assert "mine = true" in merged
        assert "collab = true" not in merged, "已废弃的 collab 标志必须清除"
        assert "multi_agent = true" in merged

    def test_user_env_value_not_clobbered(self):
        merged = build_merged_config('[env]\nUSE_OMX_EXPLORE_CMD = "0"\n', "pkg")

        assert merged.count("USE_OMX_EXPLORE_CMD") == 1
        assert 'USE_OMX_EXPLORE_CMD = "0"' in merged

    def test_model_override_propagates(self):
        merged = build_merged_config("", "pkg", model_override="my-model")

        assert 'model = "my-model"' in merged
        assert merged.count("model = ") == 1

    def test_include_tui_false_leaves_no_tui_section(self):
        merged = build_merged_config("", "pkg", include_tui=False)

        assert "[tui]" not in merged
        assert "[mcp_servers.omx_state]" in merged

    def test_previous_managed_block_is_replaced_not_duplicated(self):
        first = build_merged_config("", "pkg")

        second = build_merged_config(first, "pkg")

        assert second.count(OMX_CONFIG_MARKER) == 1
        assert second.count("[mcp_servers.omx_state]") == 1

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "缺陷 src/config/generator.py:622：合并前无条件剥离顶层 model，"
            "导致 :566 的 existing_model 分支失效——用户自定义模型每次 setup 都被重置为默认"
        ),
    )
    def test_user_model_preserved_when_no_override(self):
        merged = build_merged_config('model = "user-model"\n', "pkg")

        assert 'model = "user-model"' in merged

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "缺陷 src/config/generator.py:390 + :560：每次合并都残留一行 '# ======' 与"
            "一行头部注释，重复执行 merge_config 会让 config.toml 无限增肥"
        ),
    )
    def test_merge_is_idempotent(self):
        once = build_merged_config('[my_plugin]\nx = 1\n', "pkg")
        twice = build_merged_config(once, "pkg")

        assert twice == once


# ==========================================================================
# 落盘：merge_config / repair_config_if_needed
# ==========================================================================


class TestMergeConfigFile:
    async def test_creates_file_and_parent_dirs(self, tmp_path):
        target = tmp_path / "nested" / "config.toml"

        await merge_config(str(target), "pkg")

        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "[mcp_servers.omx_state]" in content

    async def test_reads_and_merges_existing_content(self, tmp_path):
        target = tmp_path / "config.toml"
        target.write_text('[mine]\nflag = true\n', encoding="utf-8")

        await merge_config(str(target), "pkg", verbose=True)

        content = target.read_text(encoding="utf-8")
        assert "[mine]" in content, "已有用户配置不得丢失"
        assert "[features]" in content

    async def test_model_override_written(self, tmp_path):
        target = tmp_path / "config.toml"

        await merge_config(str(target), "pkg", model_override="forced-model")

        assert 'model = "forced-model"' in target.read_text(encoding="utf-8")

    async def test_include_tui_false_honored_on_disk(self, tmp_path):
        target = tmp_path / "config.toml"

        await merge_config(str(target), "pkg", include_tui=False)

        assert "[tui]" not in target.read_text(encoding="utf-8")

    async def test_written_file_points_at_bundled_servers(self, tmp_path):
        target = tmp_path / "config.toml"

        await merge_config(str(target), "pkg")

        content = target.read_text(encoding="utf-8")
        assert "dist" in content
        for script in ("state-server.js", "memory-server.js", "team-server.js"):
            assert script in content

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "缺陷 src/config/generator.py:482-529：MCP 参数用 str(Path) 直接嵌入 TOML "
            "字符串，Windows 上产出 args = [\"C:\\pkg\\dist\\...\"] —— \\p 是保留转义序列，"
            "生成的 config.toml 无法被任何合规 TOML 解析器读取"
        ),
    )
    async def test_output_is_valid_toml(self, tmp_path):
        import toml

        target = tmp_path / "config.toml"

        await merge_config(str(target), "pkg")

        parsed = toml.load(target)
        assert parsed["model"] == DEFAULT_STANDARD_MODEL
        assert parsed["features"]["multi_agent"] is True
        assert "omx_state" in parsed["mcp_servers"]


class TestRepairConfigIfNeeded:
    def test_missing_file_returns_false(self, tmp_path):
        assert repair_config_if_needed(str(tmp_path / "absent.toml"), "pkg") is False

    def test_single_tui_section_needs_no_repair(self, tmp_path):
        target = tmp_path / "config.toml"
        target.write_text('[tui]\na = "b"\n', encoding="utf-8")

        assert repair_config_if_needed(str(target), "pkg") is False
        assert target.read_text(encoding="utf-8") == '[tui]\na = "b"\n', "无需修复时不得改写文件"

    def test_duplicate_tui_sections_are_repaired(self, tmp_path):
        target = tmp_path / "config.toml"
        target.write_text('[tui]\na = "b"\n[tui]\nc = "d"\n', encoding="utf-8")

        repaired = repair_config_if_needed(str(target), "pkg")

        assert repaired is True
        content = target.read_text(encoding="utf-8")
        assert content.count("[tui]") == 1, "修复后必须只剩一个 [tui] 表头"

    def test_repair_is_stable_on_second_run(self, tmp_path):
        target = tmp_path / "config.toml"
        target.write_text('[tui]\na = "b"\n[tui]\nc = "d"\n', encoding="utf-8")
        repair_config_if_needed(str(target), "pkg")

        assert repair_config_if_needed(str(target), "pkg") is False, (
            "第一次修复后不该再报告需要修复"
        )
