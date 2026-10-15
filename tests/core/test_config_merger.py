"""Tests for src/core/config/merger.py

重写说明 (2026-10-16):
    原测试针对的是一套已被废弃的 API —— ConfigMerger 类、OMX_MARKER 标记块、
    _upsert_* 私有函数、repair_config_if_needed、strip_omx_blocks 等符号
    在当前实现中均已不存在（实现改为「按 section upsert + 顶层键清理」）。
    本文件按当前真实 API 重写，保留原有测试意图并补充幂等性等真实行为断言。
"""



from src.core.config.merger import (
    OMX_FEATURE_FLAGS,
    OMX_TOP_LEVEL_KEYS,
    escape_toml_string,
    get_model_from_config,
    get_omx_top_level_lines,
    get_reasoning_effort,
    merge_config,
    merge_config_file,
    parse_root_key_values,
    strip_omx_top_level_keys,
    strip_orphaned_notify,
    unwrap_toml_string,
    upsert_agents_settings,
    upsert_env_settings,
    upsert_feature_flags,
)

# ---------------------------------------------------------------------------
# 基础字符串工具
# ---------------------------------------------------------------------------


class TestEscapeTomlString:
    def test_plain_string_unchanged(self):
        assert escape_toml_string('simple') == 'simple'

    def test_escapes_double_quote(self):
        assert escape_toml_string('with"quote') == 'with\\"quote'

    def test_escapes_backslash(self):
        assert escape_toml_string('back\\slash') == 'back\\\\slash'

    def test_escapes_both(self):
        assert escape_toml_string('both"\\') == 'both\\"\\\\'


class TestUnwrapTomlString:
    def test_strips_double_quotes(self):
        assert unwrap_toml_string('"hello"') == 'hello'

    def test_leaves_bare_value(self):
        assert unwrap_toml_string('naked') == 'naked'

    def test_none_passthrough(self):
        assert unwrap_toml_string(None) is None

    def test_single_quotes_not_stripped(self):
        """实现只处理双引号；单引号原样返回是既定行为，锁定它防止意外变更"""
        assert unwrap_toml_string("'world'") == "'world'"


# ---------------------------------------------------------------------------
# 顶层键解析与清理
# ---------------------------------------------------------------------------


class TestParseRootKeyValues:
    def test_parses_keys_before_first_table(self):
        config = 'model = "gpt-4"\nmodel_context_window = 8192\n\n[features]\nx = 1\n'
        values = parse_root_key_values(config)
        assert values == {"model": '"gpt-4"', "model_context_window": "8192"}

    def test_ignores_keys_after_table(self):
        """表头之后的内容不属于顶层，不应被解析"""
        config = '[features]\nmodel = "should-not-appear"\n'
        assert parse_root_key_values(config) == {}

    def test_empty_config(self):
        assert parse_root_key_values("") == {}


class TestStripOmxTopLevelKeys:
    def test_removes_managed_keys(self):
        config = (
            'notify = ["a"]\n'
            'model_reasoning_effort = "high"\n'
            'model = "keep-me"\n'
            "\n[features]\nmulti_agent = true\n"
        )
        cleaned = strip_omx_top_level_keys(config)
        assert "notify" not in cleaned
        assert "model_reasoning_effort" not in cleaned
        # 非 OMX 管理的键必须保留
        assert 'model = "keep-me"' in cleaned
        assert "[features]" in cleaned

    def test_removes_marker_comment_line(self):
        config = (
            "# oh-my-codex top-level settings (must be before any [table])\n"
            'notify = ["a"]\n'
            'model = "x"\n'
        )
        cleaned = strip_omx_top_level_keys(config)
        assert "oh-my-codex top-level settings" not in cleaned
        assert 'model = "x"' in cleaned

    def test_idempotent(self):
        """连续清理两次结果应一致"""
        config = 'notify = ["a"]\nmodel = "x"\n\n[features]\n'
        once = strip_omx_top_level_keys(config)
        twice = strip_omx_top_level_keys(once)
        assert once == twice


class TestStripOrphanedNotify:
    def test_removes_legacy_notify_hook_line(self):
        config = '[notify]\nnotify = ["node", "/path/notify-hook.js"]\nother = 1\n'
        cleaned = strip_orphaned_notify(config)
        assert "notify-hook.js" not in cleaned
        assert "other = 1" in cleaned

    def test_leaves_unrelated_content(self):
        config = 'model = "gpt-4"\n'
        assert strip_orphaned_notify(config) == config


# ---------------------------------------------------------------------------
# Section upsert
# ---------------------------------------------------------------------------


class TestUpsertFeatureFlags:
    def test_creates_section_when_absent(self):
        result = upsert_feature_flags('model = "test"')
        assert "[features]" in result
        assert "multi_agent = true" in result
        assert "child_agents_md = true" in result

    def test_updates_existing_false_values(self):
        config = "[features]\nmulti_agent = false\nchild_agents_md = false\n"
        result = upsert_feature_flags(config)
        assert "multi_agent = true" in result
        assert "child_agents_md = true" in result
        assert "false" not in result

    def test_removes_deprecated_collab_key(self):
        config = "[features]\ncollab = true\nmulti_agent = false\n"
        result = upsert_feature_flags(config)
        assert "collab" not in result
        assert "multi_agent = true" in result

    def test_does_not_duplicate_on_repeat(self):
        once = upsert_feature_flags("")
        twice = upsert_feature_flags(once)
        assert twice.count("[features]") == 1
        assert twice.count("multi_agent") == 1

    def test_preserves_unrelated_sections(self):
        config = "[other]\nkey = 1\n"
        result = upsert_feature_flags(config)
        assert "[other]" in result
        assert "key = 1" in result


class TestUpsertEnvSettings:
    def test_creates_section(self):
        result = upsert_env_settings("")
        assert "[env]" in result
        assert 'USE_OMX_EXPLORE_CMD = "1"' in result

    def test_does_not_duplicate(self):
        config = '[env]\nUSE_OMX_EXPLORE_CMD = "1"\nother = "value"\n'
        result = upsert_env_settings(config)
        assert result.count("USE_OMX_EXPLORE_CMD") == 1
        assert 'other = "value"' in result


class TestUpsertAgentsSettings:
    def test_creates_section(self):
        result = upsert_agents_settings("")
        assert "[agents]" in result
        assert "max_threads = 6" in result
        assert "max_depth = 2" in result

    def test_updates_existing_values(self):
        config = "[agents]\nmax_threads = 10\nmax_depth = 5\n"
        result = upsert_agents_settings(config)
        assert "max_threads = 6" in result
        assert "max_depth = 2" in result
        assert "max_threads = 10" not in result

    def test_does_not_duplicate_keys(self):
        once = upsert_agents_settings("")
        twice = upsert_agents_settings(once)
        assert twice.count("max_threads") == 1
        assert twice.count("max_depth") == 1


class TestGetOmxTopLevelLines:
    def test_contains_marker_and_all_managed_keys(self):
        lines = get_omx_top_level_lines()
        joined = "\n".join(lines)
        assert "oh-my-codex top-level settings" in joined
        for key in OMX_TOP_LEVEL_KEYS:
            assert f"{key} = " in joined, f"缺少 OMX 管理键: {key}"

    def test_round_trips_with_strip(self):
        """生成的顶层行必须能被 strip_omx_top_level_keys 完全清除。

        这两个函数是一对逆操作；若失配，反复 merge 会让配置无限膨胀。
        """
        generated = "\n".join(get_omx_top_level_lines())
        stripped = strip_omx_top_level_keys(generated)
        for key in OMX_TOP_LEVEL_KEYS:
            assert f"{key} = " not in stripped, f"strip 未能清除 {key}"


# ---------------------------------------------------------------------------
# merge_config 集成
# ---------------------------------------------------------------------------


class TestMergeConfig:
    def test_empty_config_produces_all_managed_sections(self):
        result = merge_config("")
        assert "[features]" in result
        assert "[env]" in result
        assert "[agents]" in result
        assert "multi_agent = true" in result

    def test_preserves_user_written_values(self):
        user_config = (
            'model = "my-model"\n'
            "model_context_window = 16000\n"
            "\n[custom]\n"
            'my_key = "my_value"\n'
            "\n[features]\n"
            "custom_flag = true\n"
        )
        result = merge_config(user_config)
        assert 'model = "my-model"' in result
        assert 'my_key = "my_value"' in result
        assert "custom_flag = true" in result

    def test_model_override_wins(self):
        result = merge_config('model = "old-model"\n', model_override="claude-opus-4")
        assert 'model = "claude-opus-4"' in result

    def test_default_model_applied_when_absent(self):
        result = merge_config("")
        assert "model = " in result

    def test_is_idempotent(self):
        """重复 merge 不应让配置无限膨胀 —— 这是该模块最重要的不变量"""
        once = merge_config('model = "m"\n')
        twice = merge_config(once)
        thrice = merge_config(twice)

        assert twice == thrice, "merge_config 不是幂等的，配置会随启动次数膨胀"
        assert thrice.count("[features]") == 1
        assert thrice.count("[env]") == 1
        assert thrice.count("[agents]") == 1
        for key in OMX_TOP_LEVEL_KEYS:
            assert thrice.count(f"{key} = ") == 1, f"{key} 出现多次"

    def test_accepts_pkg_root_without_error(self):
        """pkg_root 目前是预留参数（未被实现使用），至少不应导致异常"""
        result = merge_config("", pkg_root=".")
        assert "[features]" in result


class TestMergeConfigFile:
    def test_writes_merged_config_to_disk(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('model = "old"\n', encoding="utf-8")

        merged = merge_config_file(str(config_file))

        content = config_file.read_text(encoding="utf-8")
        assert content == merged
        assert 'model = "old"' in content
        assert "[features]" in content

    def test_creates_backup_by_default(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('model = "old"\n', encoding="utf-8")

        merge_config_file(str(config_file))

        backup = config_file.with_suffix(".toml.bak")
        assert backup.exists(), "默认应创建 .bak 备份"
        assert backup.read_text(encoding="utf-8") == 'model = "old"\n'

    def test_backup_can_be_disabled(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('model = "old"\n', encoding="utf-8")

        merge_config_file(str(config_file), backup=False)

        assert not config_file.with_suffix(".toml.bak").exists()

    def test_missing_file_is_created(self, tmp_path):
        config_file = tmp_path / "brand-new.toml"

        merge_config_file(str(config_file))

        assert config_file.exists()
        assert "[features]" in config_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 便捷读取函数
# ---------------------------------------------------------------------------


class TestGetModelFromConfig:
    def test_reads_model_from_string(self):
        assert get_model_from_config('model = "gpt-4o"\n') == "gpt-4o"

    def test_reads_model_from_path(self, tmp_path):
        p = tmp_path / "c.toml"
        p.write_text('model = "claude-sonnet-4-5"\n', encoding="utf-8")
        assert get_model_from_config(p) == "claude-sonnet-4-5"

    def test_missing_path_returns_none(self, tmp_path):
        assert get_model_from_config(tmp_path / "nope.toml") is None

    def test_absent_key_returns_none(self):
        assert get_model_from_config("[features]\n") is None


class TestGetReasoningEffort:
    def test_reads_effort(self):
        assert get_reasoning_effort('model_reasoning_effort = "high"\n') == "high"

    def test_round_trips_with_merge_output(self):
        """merge 写入的 model_reasoning_effort 必须能被读回来"""
        merged = merge_config("")
        assert get_reasoning_effort(merged) is not None

    def test_absent_key_returns_none(self):
        assert get_reasoning_effort('model = "x"\n') is None


# ---------------------------------------------------------------------------
# 常量完整性
# ---------------------------------------------------------------------------


class TestConstants:
    def test_feature_flags_are_non_empty(self):
        assert OMX_FEATURE_FLAGS, "OMX_FEATURE_FLAGS 不应为空"

    def test_top_level_keys_are_non_empty(self):
        assert OMX_TOP_LEVEL_KEYS, "OMX_TOP_LEVEL_KEYS 不应为空"

    def test_top_level_keys_have_no_duplicates(self):
        assert len(OMX_TOP_LEVEL_KEYS) == len(set(OMX_TOP_LEVEL_KEYS))
