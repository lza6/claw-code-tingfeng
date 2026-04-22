"""
Config Generator - Clawd Code 配置管理器

从 oh-my-codex-main/src/config/generator.ts 转换而来。
负责生成、合并和维护项目配置文件（.clawd/config.toml）。

核心功能：
1. 合并 OMX 配置到现有 config.toml
2. 智能保留用户自定义设置
3. 管理 feature flags
4. 注册 MCP 服务器
5. TUI 状态行配置
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from src.agent.definitions import AGENT_DEFINITIONS

logger = logging.getLogger(__name__)

# ========== 常量定义 ==========

OMX_CONFIG_MARKER = "# oh-my-codex (OMX) Configuration"
OMX_CONFIG_END_MARKER = "# End oh-my-codex"

# 顶级OMX配置键（必须位于任何 [table] 之前）
OMX_TOP_LEVEL_KEYS = [
    "notify",
    "model_reasoning_effort",
    "developer_instructions",
]

DEFAULT_FRONTIER_MODEL = "claude-sonnet-4-6"
DEFAULT_FRONTIER_CONTEXT_WINDOW = 200000
DEFAULT_STANDARD_MODEL = "claude-haiku-4-5-20251001"

OMX_AGENTS_MAX_THREADS = 6
OMX_AGENTS_MAX_DEPTH = 2
OMX_EXPLORE_CMD_ENV = "USE_OMX_EXPLORE_CMD"
OMX_EXPLORE_ROUTING_DEFAULT = "1"

DEFAULT_TUI_STATUS_LINE = (
    'status_line = ["model-with-reasoning", "git-branch", "context-remaining", '
    '"total-input-tokens", "total-output-tokens", "five-hour-limit", "weekly-limit"]'
)


# ========== 类型定义 ==========

@dataclass
class McpServerConfig:
    """MCP 服务器配置"""
    name: str
    command: str
    args: list[str]
    enabled: bool = True
    startup_timeout_sec: int | None = None


@dataclass
class ConfigMergeResult:
    """配置合并结果"""
    final_config: str
    had_existing_omx: bool
    stripped_blocks: int
    added_keys: list[str]


# ========== TOML 解析工具函数 ==========

def _parse_root_key_values(config: str) -> dict[str, str]:
    """
    解析TOML文件顶层的键值对（在任何 [table] 之前）。

    返回：顶层键值映射
    """
    values: dict[str, str] = {}
    lines = config.splitlines()

    for line in lines:
        stripped = line.strip()
        # 遇到 table header 就停止
        if stripped.startswith('[') and stripped.endswith(']'):
            break
        # 匹配 key = value
        match = re.match(r'^([A-Za-z0-9_-]+)\s*=\s*(.+?)\s*$', stripped)
        if match:
            key, value = match.groups()
            values[key] = value

    return values


def _unwrap_toml_string(value: str | None) -> str | None:
    """去除 TOML 字符串的引号"""
    if value is None:
        return None
    m = re.match(r'^"(.+)"$', value)
    return m.group(1) if m else value


def _strip_root_level_keys(config: str, keys: list[str]) -> str:
    """
    从配置中移除指定的顶层键。

    Args:
        config: 原始配置内容
        keys: 要移除的键列表

    Returns:
        清理后的配置
    """
    lines = config.splitlines()

    # 找到第一个 table header 的位置
    first_table_idx = len(lines)
    for i, line in enumerate(lines):
        if re.match(r'^\s*\[', line):
            first_table_idx = i
            break

    result_lines = []
    for i, line in enumerate(lines):
        # 只处理顶层（table之前）的键
        if i < first_table_idx:
            # 检查这行是否是我们要移除的键
            for key in keys:
                key_pattern = rf'^\s*{re.escape(key)}\s*='
                if re.match(key_pattern, line):
                    break
            else:
                result_lines.append(line)
        else:
            result_lines.append(line)

    return '\n'.join(result_lines)


def _strip_orphaned_managed_notify(config: str) -> str:
    """移除孤立的 OMX notify 配置（当 OMX 块被删除后遗留的）"""
    # 匹配孤立的 notify 配置：notify = ["node", "路径"]
    pattern = r'^\s*notify\s*=\s*\["node",\s*".*notify-hook\.js"\]\s*$'
    lines = config.splitlines()
    result = [line for line in lines if not re.match(pattern, line)]
    # 清理多余空行
    cleaned = '\n'.join(result)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


# ========== Feature Flags 管理 ==========

def _upsert_feature_flags(config: str) -> str:
    """
    插入或更新 [features] 部分中的 OMX 标志。

    确保：
    - multi_agent = true
    - child_agents_md = true
    - 移除已废弃的 collab 标志
    """
    lines = config.splitlines()
    features_start = -1

    # 查找 [features] 部分
    for i, line in enumerate(lines):
        if re.match(r'^\s*\[features\]\s*$', line):
            features_start = i
            break

    if features_start < 0:
        # 没有 [features] 部分，在末尾添加
        base = config.rstrip()
        if base:
            return base + "\n\n[features]\nmulti_agent = true\nchild_agents_md = true\n\n"
        return "[features]\nmulti_agent = true\nchild_agents_md = true\n\n"

    # 找到 [features] 部分的结束位置
    section_end = len(lines)
    for i in range(features_start + 1, len(lines)):
        if re.match(r'^\s*\[', lines[i]):
            section_end = i
            break

    # 移除已废弃的 collab 标志
    filtered_lines = []
    for i in range(features_start + 1, section_end):
        line = lines[i]
        if re.match(r'^\s*collab\s*=', line):
            continue  # 跳过 collab
        filtered_lines.append(line)

    # 更新或添加 multi_agent 和 child_agents_md
    has_multi_agent = any(re.match(r'^\s*multi_agent\s*=', l) for l in filtered_lines)
    has_child_agents = any(re.match(r'^\s*child_agents_md\s*=', l) for l in filtered_lines)

    insert_idx = len(filtered_lines)

    if not has_multi_agent:
        filtered_lines.insert(insert_idx, "multi_agent = true")
        insert_idx += 1

    if not has_child_agents:
        filtered_lines.insert(insert_idx, "child_agents_md = true")

    # 重建配置
    new_lines = lines[:features_start + 1] + filtered_lines + lines[section_end:]
    return '\n'.join(new_lines)


def _upsert_env_settings(config: str) -> str:
    """插入或更新 [env] 部分的 OMX 设置"""
    lines = config.splitlines()
    env_start = -1

    for i, line in enumerate(lines):
        if re.match(r'^\s*\[env\]\s*$', line):
            env_start = i
            break

    if env_start < 0:
        base = config.rstrip()
        env_block = f'\n\n[env]\n{OMX_EXPLORE_CMD_ENV} = "{OMX_EXPLORE_ROUTING_DEFAULT}"\n'
        return base + env_block

    section_end = len(lines)
    for i in range(env_start + 1, len(lines)):
        if re.match(r'^\s*\[', lines[i]):
            section_end = i
            break

    # 检查是否已有设置
    has_explore_routing = any(
        re.match(rf'^\s*{re.escape(OMX_EXPLORE_CMD_ENV)}\s*=', lines[i])
        for i in range(env_start + 1, section_end)
    )

    if not has_explore_routing:
        lines.insert(section_end, f'{OMX_EXPLORE_CMD_ENV} = "{OMX_EXPLORE_ROUTING_DEFAULT}"')

    return '\n'.join(lines)


def _upsert_agents_settings(config: str) -> str:
    """插入或更新 [agents] 部分的设置"""
    lines = config.splitlines()
    agents_start = -1

    for i, line in enumerate(lines):
        if re.match(r'^\s*\[agents\]\s*$', line):
            agents_start = i
            break

    if agents_start < 0:
        base = config.rstrip()
        agents_block = (
            f'\n\n[agents]\n'
            f'max_threads = {OMX_AGENTS_MAX_THREADS}\n'
            f'max_depth = {OMX_AGENTS_MAX_DEPTH}\n\n'
        )
        return base + agents_block

    section_end = len(lines)
    for i in range(agents_start + 1, len(lines)):
        if re.match(r'^\s*\[', lines[i]):
            section_end = i
            break

    # 更新或添加 max_threads 和 max_depth
    has_max_threads = any(
        re.match(r'^\s*max_threads\s*=', lines[i])
        for i in range(agents_start + 1, section_end)
    )
    has_max_depth = any(
        re.match(r'^\s*max_depth\s*=', lines[i])
        for i in range(agents_start + 1, section_end)
    )

    if not has_max_threads:
        lines.insert(section_end, f'max_threads = {OMX_AGENTS_MAX_THREADS}')
        section_end += 1

    if not has_max_depth:
        lines.insert(section_end, f'max_depth = {OMX_AGENTS_MAX_DEPTH}')

    return '\n'.join(lines)


# ========== TUI 状态行管理 ==========

def _upsert_tui_status_line(config: str, *, include_tui: bool = True) -> tuple[str, bool]:
    """
    插入或更新 [tui] 状态的 status_line。

    Returns:
        (处理后的配置字符串, 是否已有现成的 [tui] 部分)
    """
    if not include_tui:
        return config, False

    lines = config.splitlines()
    tui_sections: list[tuple[int, int]] = []  # (start_idx, end_idx)

    # 查找所有 [tui] 部分
    for i, line in enumerate(lines):
        if re.match(r'^\s*\[tui\]\s*$', line):
            # 找到该部分的结尾
            end = len(lines)
            for j in range(i + 1, len(lines)):
                if re.match(r'^\s*\[', lines[j]):
                    end = j
                    break
            tui_sections.append((i, end))

    if not tui_sections:
        return config, False

    # 收集需保留的键（排除 status_line）
    preserved_key_lines: list[str] = []
    seen_keys: set[str] = set()

    for start, end in tui_sections:
        for i in range(start + 1, end):
            line = lines[i].strip()
            if not line or line.startswith('#'):
                continue
            match = re.match(r'^([A-Za-z0-9_-]+)\s*=', line)
            if not match:
                continue
            key = match.group(1)
            if key == "status_line" or key in seen_keys:
                continue
            seen_keys.add(key)
            preserved_key_lines.append(line)

    # 构建合并后的 [tui] 部分
    merged_section = ["[tui]"] + preserved_key_lines + [DEFAULT_TUI_STATUS_LINE, ""]

    # 重建配置，只在第一个 [tui] 位置插入
    first_start = tui_sections[0][0]
    rebuilt: list[str] = []
    i = 0
    first_replaced = False

    while i < len(lines):
        is_tui_section = any(start == i for start, _ in tui_sections)
        if is_tui_section and not first_replaced:
            # 跳过整个原 [tui] 部分
            _, end = next((s, e) for s, e in tui_sections if s == i)
            # 必要时添加空行分隔
            if rebuilt and rebuilt[-1].strip():
                rebuilt.append("")
            rebuilt.extend(merged_section)
            i = end
            first_replaced = True
        else:
            rebuilt.append(lines[i])
            i += 1

    # 压缩多余空行
    result = '\n'.join(rebuilt)
    result = re.sub(r'\n{3,}', '\n\n', result)

    return result.rstrip() + '\n', True


# ========== OMX 配置区块管理 ==========

def _strip_existing_omx_blocks(config: str) -> tuple[str, int]:
    """
    移除已存在的 OMX 配置区块（标记在 OMX_CONFIG_MARKER 和 OMX_CONFIG_END_MARKER 之间）。

    Returns:
        (清理后的配置, 移除的区块数)
    """
    cleaned = config
    removed = 0

    while True:
        marker_idx = cleaned.find(OMX_CONFIG_MARKER)
        if marker_idx < 0:
            break

        # 确定区块起始（包括前导注释和空行）
        block_start = cleaned.rfind('\n', 0, marker_idx) + 1
        if block_start == 0:
            block_start = 0

        # 寻找区块结束
        block_end = len(cleaned)
        end_idx = cleaned.find(OMX_CONFIG_END_MARKER, marker_idx)
        if end_idx >= 0:
            # 包含结束标记后的换行
            newline_after = cleaned.find('\n', end_idx)
            if newline_after >= 0:
                block_end = newline_after + 1
            else:
                block_end = len(cleaned)

        # 拼接前后部分
        before = cleaned[:block_start].rstrip()
        after = cleaned[block_end:].lstrip()

        if before and after:
            cleaned = before + '\n\n' + after
        elif before:
            cleaned = before
        elif after:
            cleaned = after
        else:
            cleaned = ""

        removed += 1

    return cleaned, removed


def _is_legacy_omx_agent_section(table_name: str) -> bool:
    """
    检查 TOML 表名是否属于遗留的 OMX 管理的 agent 配置。
    例如：agents.executor, agents."code-reviewer"
    """
    m = re.match(r'^agents\.(?:"([^"]+)"|(\w[\w-]*))$', table_name)
    if not m:
        return False
    name = m.group(1) or m.group(2) or ""
    return name in AGENT_DEFINITIONS


def _strip_orphaned_omx_sections(config: str) -> str:
    """
    移除 legacy 的 OMX 表 sections（在标记区块之外的）。
    包括 [mcp_servers.omx_*] 和 [agents.<name>] 等。
    """
    lines = config.splitlines()
    result: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        table_match = re.match(r'^\s*\[([^\]]+)\]\s*$', line)

        if table_match:
            table_name = table_match.group(1)
            # 检测是否是 OMX 管理的 section
            is_omx_section = (
                re.match(r'^mcp_servers\.omx_', table_name) or
                _is_legacy_omx_agent_section(table_name) or
                table_name == 'tui'  # tui 也可能是 OMX 管理的
            )

            if is_omx_section:
                # 删除前导的空行和 OMX 注释
                while result and (result[-1].strip() == "" or
                                 re.match(r'^#\s*(OMX|oh-my-codex)', result[-1], re.IGNORECASE)):
                    result.pop()

                # 跳过这个 table 及其所有键值对
                i += 1
                while i < len(lines) and not re.match(r'^\s*\[', lines[i]):
                    i += 1
                continue

        result.append(line)
        i += 1

    return '\n'.join(result)


def _get_omx_tables_block(package_root: str, include_tui: bool = True) -> str:
    """
    生成 OMX 的 [table] sections 配置块。
    包含所有 MCP 服务器配置和可选的 TUI 配置。
    """
    # 构建 MCP 服务器路径
    pkg_root = Path(package_root)
    state_server_path = str(pkg_root / "dist" / "mcp" / "state-server.js")
    memory_server_path = str(pkg_root / "dist" / "mcp" / "memory-server.js")
    code_intel_path = str(pkg_root / "dist" / "mcp" / "code-intel-server.js")
    trace_server_path = str(pkg_root / "dist" / "mcp" / "trace-server.js")
    team_server_path = str(pkg_root / "dist" / "mcp" / "team-server.js")

    lines = [
        "",
        "# ============================================================",
        "# oh-my-codex (OMX) Configuration",
        "# Managed by Clawd Code - manual edits preserved on next setup",
        "# ============================================================",
        "",
        "# OMX State Management MCP Server",
        '[mcp_servers.omx_state]',
        'command = "node"',
        f'args = ["{state_server_path}"]',
        "enabled = true",
        "startup_timeout_sec = 5",
        "",
        "# OMX Project Memory MCP Server",
        '[mcp_servers.omx_memory]',
        'command = "node"',
        f'args = ["{memory_server_path}"]',
        "enabled = true",
        "startup_timeout_sec = 5",
        "",
        "# OMX Code Intelligence MCP Server",
        '[mcp_servers.omx_code_intel]',
        'command = "node"',
        f'args = ["{code_intel_path}"]',
        "enabled = true",
        "startup_timeout_sec = 10",
        "",
        "# OMX Trace MCP Server",
        '[mcp_servers.omx_trace]',
        'command = "node"',
        f'args = ["{trace_server_path}"]',
        "enabled = true",
        "startup_timeout_sec = 5",
        "",
        "# OMX Team MCP Server",
        '[mcp_servers.omx_team_run]',
        'command = "node"',
        f'args = ["{team_server_path}"]',
        "enabled = true",
        "startup_timeout_sec = 5",
    ]

    if include_tui:
        lines.extend([
            "",
            "# OMX TUI StatusLine (Clawd Code v0.50.0+)",
            "[tui]",
            DEFAULT_TUI_STATUS_LINE,
            "",
        ])

    lines.extend([
        "# ============================================================",
        "# End oh-my-codex",
        "",
    ])

    return '\n'.join(lines)


def _get_root_level_lines(
    package_root: str,
    existing_config: str,
    model_override: str | None = None,
) -> list[str]:
    """
    生成 OMX 顶层配置行（位于任何 [table] 之前）。
    """
    root_values = _parse_root_key_values(existing_config)

    lines = [
        "# Clawd Code top-level settings (must be before any [table])",
    ]

    # 确定使用的模型
    existing_model = root_values.get("model")
    existing_model_unquoted = _unwrap_toml_string(existing_model)
    selected_model = model_override or existing_model_unquoted or DEFAULT_STANDARD_MODEL

    if model_override or not existing_model:
        lines.append(f'model = "{selected_model}"')

    # 添加其他顶层设置
    lines.append('model_reasoning_effort = "high"')
    lines.append(
        'developer_instructions = "You are using Clawd Code, an AI-powered coding agent '
        'framework with multi-agent collaboration, workflow orchestration, and self-healing capabilities. '
        'Follow the AGENTS.md guidance for orchestration workflows and use $skill invocations '
        'for specialized tasks. Refer to .clawd/ for project state and memory."'
    )

    return lines


# ========== 公共 API ==========

def build_merged_config(
    existing_config: str,
    package_root: str = ".",
    *,
    model_override: str | None = None,
    include_tui: bool = True,
) -> str:
    """
    将 Clawd Code 配置合并到现有 config.toml 中。

    合并策略：
    1. 移除旧的 OMX 配置区块
    2. 移除孤立的 OMX 管理键
    3. 插入/更新 feature flags
    4. 插入/更新 env settings
    5. 插入/更新 agents settings
    6. 在文件顶部插入 OMX 顶层键
    7. 在文件末尾追加 OMX 表区块

    Args:
        existing_config: 现有配置文件内容
        package_root: 项目根目录路径
        model_override: 强制使用的模型名称
        include_tui: 是否包含 TUI 配置

    Returns:
        合并后的配置完整字符串
    """
    logger = logging.getLogger(__name__)

    # 1. 清理现有的 OMX 配置区块
    config, removed_blocks = _strip_existing_omx_blocks(existing_config)
    if removed_blocks > 0:
        logger.debug(f"移除了 {removed_blocks} 个 OMX 配置区块")

    # 2. 清理孤立的 OMX 配置
    config = _strip_orphaned_omx_sections(config)
    config = _strip_root_level_keys(config, OMX_TOP_LEVEL_KEYS + ["model"])
    config = _strip_orphaned_managed_notify(config)

    # 3. 插入/更新各部分
    config = _upsert_feature_flags(config)
    config = _upsert_env_settings(config)
    config = _upsert_agents_settings(config)

    # 4. 处理 TUI
    tui_result, had_tui = _upsert_tui_status_line(config, include_tui=include_tui)
    config = tui_result

    # 5. 生成顶层行
    root_lines = _get_root_level_lines(package_root, config, model_override)

    # 6. 生成表区块
    tables_block = _get_omx_tables_block(package_root, include_tui and not had_tui)

    # 7. 组装最终配置
    body = config.strip()
    if body:
        final_config = '\n\n'.join([
            '\n'.join(root_lines),
            body,
            tables_block.rstrip()
        ])
    else:
        final_config = '\n\n'.join([
            '\n'.join(root_lines),
            tables_block.rstrip()
        ])

    return final_config + '\n'


async def merge_config(
    config_path: str,
    package_root: str = ".",
    *,
    model_override: str | None = None,
    include_tui: bool = True,
    verbose: bool = False,
) -> None:
    """
    将 Clawd Code 配置合并到指定的 config.toml 文件。

    Args:
        config_path: config.toml 文件路径
        package_root: 项目根目录路径
        model_override: 强制使用的模型名称
        include_tui: 是否包含 TUI 配置
        verbose: 是否输出详细日志

    Raises:
        FileNotFoundError: config.toml 不存在且无法创建
        PermissionError: 没有文件写入权限
    """

    config_file = Path(config_path)

    # 读取现有配置
    existing = ""
    if config_file.exists():
        existing = config_file.read_text(encoding="utf-8")
        if verbose:
            logger.info(f"读取现有配置: {config_path}")

    # 生成合并后的配置
    merged = build_merged_config(
        existing,
        package_root,
        model_override=model_override,
        include_tui=include_tui,
    )

    # 写入文件
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(merged, encoding="utf-8")

    if verbose:
        logger.info(f"配置已写入: {config_path}")


def repair_config_if_needed(
    config_path: str,
    package_root: str = ".",
    *,
    model_override: str | None = None,
) -> bool:
    """
    检查并修复配置文件中的重复 table 头等常见问题。

    Returns:
        True 如果执行了修复，False 如果无需修复
    """
    config_file = Path(config_path)
    if not config_file.exists():
        return False

    content = config_file.read_text(encoding="utf-8")

    # 检测重复的 [tui] 部分
    tui_count = len(re.findall(r'^\s*\[tui\]\s*$', content, re.MULTILINE))
    if tui_count <= 1:
        return False

    # 需要修复 - 重新合并
    merged = build_merged_config(content, package_root, model_override=model_override)
    config_file.write_text(merged, encoding="utf-8")
    logger.info(f"修复了配置文件中的重复 table: {config_path}")
    return True


# ========== 导出 ==========

__all__ = [
    "ConfigMergeResult",
    "McpServerConfig",
    "_parse_root_key_values",
    "_unwrap_toml_string",
    "build_merged_config",
    "merge_config",
    "repair_config_if_needed",
]
