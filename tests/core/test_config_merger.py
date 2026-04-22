"""Tests for src/core/config/merger.py"""

import os
import pytest
from src.core.config.merger import (
    ConfigMerger,
    merge_config,
    repair_config_if_needed,
    strip_omx_blocks,
    escape_toml_string,
    parse_toml_string_value,
    _strip_top_level_keys,
    _upsert_feature_flags,
    _upsert_env_settings,
    _upsert_agents_settings,
    _upsert_tui_status_line,
    _build_top_level_lines,
    OMX_MARKER,
    OMX_MARKER_END,
)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def test_escape_toml_string():
    assert escape_toml_string('simple') == 'simple'
    assert escape_toml_string('with"quote') == 'with\\"quote'
    assert escape_toml_string('back\\slash') == 'back\\\\slash'
    assert escape_toml_string('both"\\') == 'both\\"\\\\'


def test_parse_toml_string_value():
    assert parse_toml_string_value('"hello"') == 'hello'
    assert parse_toml_string_value("'world'") == 'world'
    assert parse_toml_string_value('naked') == 'naked'
    assert parse_toml_string_value('"with\\"quote"') == 'with"quote'


def test_strip_top_level_keys():
    config = '''model = "gpt-4"
model_context_window = 8192

[features]
multi_agent = true
'''
    cleaned, removed = _strip_top_level_keys(config, ['model', 'model_context_window'])
    assert 'model' not in cleaned
    assert 'model_context_window' not in cleaned
    assert '[features]' in cleaned
    assert removed == 2


# ---------------------------------------------------------------------------
# Feature Flags
# ---------------------------------------------------------------------------

def test_upsert_feature_flags_creates_section():
    config = 'model = "test"'
    result = _upsert_feature_flags(config)
    assert '[features]' in result
    assert 'multi_agent = true' in result
    assert 'child_agents_md = true' in result


def test_upsert_feature_flags_updates_existing():
    config = '''[features]
multi_agent = false
child_agents_md = false
'''
    result = _upsert_feature_flags(config)
    assert 'multi_agent = true' in result
    assert 'child_agents_md = true' in result


def test_upsert_feature_flags_removes_collab():
    config = '''[features]
collab = true
multi_agent = false
'''
    result = _upsert_feature_flags(config)
    assert 'collab' not in result
    assert 'multi_agent = true' in result


# ---------------------------------------------------------------------------
# Env Settings
# ---------------------------------------------------------------------------

def test_upsert_env_settings_creates():
    config = ''
    result = _upsert_env_settings(config)
    assert '[env]' in result
    assert 'USE_OMX_EXPLORE_CMD = "1"' in result


def test_upsert_env_settings_does_not_duplicate():
    config = '''[env]
USE_OMX_EXPLORE_CMD = "1"
other = "value"
'''
    result = _upsert_env_settings(config)
    assert result.count('USE_OMX_EXPLORE_CMD') == 1


# ---------------------------------------------------------------------------
# Agents Settings
# ---------------------------------------------------------------------------

def test_upsert_agents_settings_creates():
    config = ''
    result = _upsert_agents_settings(config)
    assert '[agents]' in result
    assert 'max_threads = 6' in result
    assert 'max_depth = 2' in result


def test_upsert_agents_settings_updates():
    config = '''[agents]
max_threads = 10
max_depth = 5
'''
    result = _upsert_agents_settings(config)
    assert 'max_threads = 6' in result
    assert 'max_depth = 2' in result


# ---------------------------------------------------------------------------
# TUI Status Line
# ---------------------------------------------------------------------------

def test_upsert_tui_status_line_no_section():
    config = 'model = "test"'
    result, had = _upsert_tui_status_line(config)
    assert had is False
    assert result == config  # 未修改


def test_upsert_tui_status_line_with_section():
    config = '''[tui]
custom_key = "custom_value"
'''
    result, had = _upsert_tui_status_line(config)
    assert had is True
    assert 'custom_key = "custom_value"' in result
    assert 'status_line' in result


def test_upsert_tui_status_line_preserves_other_keys():
    config = '''[tui]
key1 = "val1"
key2 = "val2"
'''
    result, _ = _upsert_tui_status_line(config)
    assert 'key1 = "val1"' in result
    assert 'key2 = "val2"' in result
    # status_line 只出现一次
    assert result.count('status_line') == 1


# ---------------------------------------------------------------------------
# Top-level lines
# ---------------------------------------------------------------------------

def test_build_top_level_lines_no_model():
    config = ''
    lines = _build_top_level_lines(config)
    assert any('model = ' in l for l in lines)
    assert any('model_reasoning_effort' in l for l in lines)


def test_build_top_level_lines_model_override():
    config = ''
    lines = _build_top_level_lines(config, model_override='claude-opus-4')
    assert 'model = "claude-opus-4"' in lines


# ---------------------------------------------------------------------------
# OMX Block Stripping
# ---------------------------------------------------------------------------

def test_strip_omx_blocks_single():
    config = f'''before

{OMX_MARKER}
# something
key = "value"
{OMX_MARKER_END}

after'''
    cleaned, count = strip_omx_blocks(config)
    assert 'before' in cleaned
    assert 'after' in cleaned
    assert 'something' not in cleaned
    assert count == 1


def test_strip_omx_blocks_multiple():
    config = f'''{OMX_MARKER}
a = 1
{OMX_MARKER_END}
middle
{OMX_MARKER}
b = 2
{OMX_MARKER_END}'''
    cleaned, count = strip_omx_blocks(config)
    assert 'middle' in cleaned
    assert count == 2


# ---------------------------------------------------------------------------
# ConfigMerger integration
# ---------------------------------------------------------------------------

def test_config_merger_empty_config(tmp_path):
    """空配置正确生成 OMX 块。"""
    merger = ConfigMerger(pkg_root=str(tmp_path))
    result = merger.merge('')

    assert OMX_MARKER in result
    assert '[features]' in result
    assert '[env]' in result
    assert '[agents]' in result
    assert 'multi_agent = true' in result


def test_config_merger_preserves_user_config(tmp_path):
    """用户手写的配置段不被删除。"""
    user_config = '''model = "my-model"
model_context_window = 16000

[custom]
my_key = "my_value"

[features]
custom_flag = true
'''
    merger = ConfigMerger(pkg_root=str(tmp_path))
    result = merger.merge(user_config)

    assert 'model = "my-model"' in result
    assert 'my_key = "my_value"' in result
    assert 'custom_flag = true' in result


def test_config_merger_atomic_write(tmp_path):
    """apply_to_file 执行原子写。"""
    config_file = tmp_path / 'config.toml'
    config_file.write_text('model = "old"')

    merger = ConfigMerger(pkg_root=str(tmp_path))
    merger.apply_to_file(str(config_file), verbose=False)

    content = config_file.read_text()
    assert 'model = "old"' in content  # 保留
    assert OMX_MARKER in content


def test_repair_config_if_needed_no_duplicate(tmp_path):
    """无重复 [tui] 时不修改。"""
    config_file = tmp_path / 'config.toml'
    config_file.write_text('[tui]\nkey = "value"\n')

    repaired = repair_config_if_needed(str(config_file), pkg_root=str(tmp_path))
    assert repaired is False


def test_repair_config_if_needed_with_duplicate(tmp_path):
    """检测到重复 [tui] 触发修复。"""
    broken = '''[tui]
status_line = ["a"]

[tui]
status_line = ["b"]
'''
    config_file = tmp_path / 'config.toml'
    config_file.write_text(broken)

    repaired = repair_config_if_needed(str(config_file), pkg_root=str(tmp_path))
    assert repaired is True

    fixed = config_file.read_text()
    tui_count = fixed.count('[tui]')
    assert tui_count == 1, f'Expected 1 [tui], got {tui_count}'


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def test_merge_config_function(tmp_path):
    """merge_config 便捷函数正常工作。"""
    config_file = tmp_path / 'config.toml'
    config_file.write_text('')

    merge_config(str(config_file), pkg_root=str(tmp_path), verbose=False)
    content = config_file.read_text()
    assert OMX_MARKER in content or '[features]' in content
