"""Config Merger - 配置智能合并系统

借鉴 oh-my-codex 的配置合并逻辑。
自动合并用户现有配置，保留自定义设置，智能插入 OMX 专属配置段。

功能:
- 自动合并 config.toml，保留用户设置
- 智能 upsert feature flags
- MCP 服务器注册管理
- 环境变量管理
"""

from __future__ import annotations

import re
from pathlib import Path

# ==================== OMX 专属配置键 ====================

OMX_TOP_LEVEL_KEYS = [
    "notify",
    "model_reasoning_effort",
    "developer_instructions",
]

OMX_FEATURE_FLAGS = [
    "multi_agent",
    "child_agents_md",
]

OMX_ENV_KEYS = [
    "USE_OMX_EXPLORE_CMD",
]

OMX_AGENTS_KEYS = [
    "max_threads",
    "max_depth",
]


def escape_toml_string(value: str) -> str:
    """转义 TOML 字符串"""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def unwrap_toml_string(value: str | None) -> str | None:
    """解包 TOML 字符串"""
    if value is None:
        return None
    match = re.match(r'^"(.*)"$', value)
    return match.group(1) if match else value


def parse_root_key_values(config: str) -> dict[str, str]:
    """解析顶层键值对"""
    values: dict[str, str] = {}
    lines = config.splitlines()

    for line in lines:
        if re.match(r'^\s*\[', line):
            break  # 遇到第一个表头，停止解析
        match = re.match(r'^\s*([A-Za-z0-9_-]+)\s*=\s*(.+?)\s*$', line)
        if match:
            values[match.group(1)] = match.group(2)

    return values


def strip_omx_top_level_keys(config: str) -> str:
    """移除 OMX 管理的顶层键"""
    lines = config.splitlines()

    # 检查是否需要移除标记行
    if any(key in config for key in OMX_TOP_LEVEL_KEYS):
        lines = [
            l for l in lines
            if l.strip() != "# oh-my-codex top-level settings (must be before any [table])"
        ]

    first_table = next((i for i, l in enumerate(lines) if re.match(r'^\s*\[', l)), -1)
    boundary = first_table if first_table >= 0 else len(lines)

    result: list[str] = []
    for i, line in enumerate(lines):
        if i < boundary:
            # 检查是否是 OMX 管理的键
            is_managed = any(
                re.match(rf'^\s*{key}\s*=', line)
                for key in OMX_TOP_LEVEL_KEYS
            )
            if is_managed:
                continue
        result.append(line)

    return '\n'.join(result)


def strip_orphaned_notify(config: str) -> str:
    """移除孤立的 notify 配置"""
    # 移除独立的 notify 行
    config = re.sub(
        r'^\s*notify\s*=\s*\["node",\s*".*notify-hook\.js"\]\s*$',
        '',
        config,
        flags=re.MULTILINE
    )
    # 移除数组中的 notify-hook 引用
    config = re.sub(
        r'\n?\s*"node",\s*\n\s*".*notify-hook\.js",\s*\n\s*\]\s*(?=\n|$)',
        '',
        config
    )
    return config


def upsert_feature_flags(config: str) -> str:
    """插入/更新 feature flags"""
    lines = config.splitlines()

    # 查找 [features] 节
    features_start = -1
    for i, line in enumerate(lines):
        if re.match(r'^\s*\[features\]\s*$', line):
            features_start = i
            break

    if features_start < 0:
        # 没有 features 节，追加
        base = config.rstrip()
        feature_block = '\n'.join([
            "[features]",
            "multi_agent = true",
            "child_agents_md = true",
            "",
        ])
        return f"{base}\n{feature_block}" if base else feature_block

    # 找到 features 节边界
    section_end = len(lines)
    for i in range(features_start + 1, len(lines)):
        if re.match(r'^\s*\[', lines[i]):
            section_end = i
            break

    # 移除废弃的 collab 键
    for i in range(section_end - 1, features_start, -1):
        if re.match(r'^\s*collab\s*=', lines[i]):
            lines.pop(i)
            section_end -= 1

    # 检查并更新 multi_agent
    multi_agent_idx = -1
    child_agents_idx = -1
    for i in range(features_start + 1, section_end):
        if re.match(r'^\s*multi_agent\s*=', lines[i]):
            multi_agent_idx = i
        elif re.match(r'^\s*child_agents_md\s*=', lines[i]):
            child_agents_idx = i

    if multi_agent_idx >= 0:
        lines[multi_agent_idx] = "multi_agent = true"
    else:
        lines.insert(section_end, "multi_agent = true")
        section_end += 1

    if child_agents_idx >= 0:
        lines[child_agents_idx] = "child_agents_md = true"
    else:
        lines.insert(section_end, "child_agents_md = true")

    return '\n'.join(lines)


def upsert_env_settings(config: str) -> str:
    """插入/更新环境变量设置"""
    lines = config.splitlines()

    # 查找 [env] 节
    env_start = -1
    for i, line in enumerate(lines):
        if re.match(r'^\s*\[env\]\s*$', line):
            env_start = i
            break

    if env_start < 0:
        base = config.rstrip()
        env_block = '\n'.join([
            "[env]",
            'USE_OMX_EXPLORE_CMD = "1"',
            "",
        ])
        return f"{base}\n\n{env_block}" if base else env_block

    section_end = len(lines)
    for i in range(env_start + 1, len(lines)):
        if re.match(r'^\s*\[', lines[i]):
            section_end = i
            break

    # 检查 USE_OMX_EXPLORE_CMD
    explore_idx = -1
    for i in range(env_start + 1, section_end):
        if re.match(r'^\s*USE_OMX_EXPLORE_CMD\s*=', lines[i]):
            explore_idx = i
            break

    if explore_idx < 0:
        lines.insert(section_end, 'USE_OMX_EXPLORE_CMD = "1"')

    return '\n'.join(lines)


def upsert_agents_settings(config: str) -> str:
    """插入/更新 agents 设置"""
    lines = config.splitlines()

    # 查找 [agents] 节
    agents_start = -1
    for i, line in enumerate(lines):
        if re.match(r'^\s*\[agents\]\s*$', line):
            agents_start = i
            break

    if agents_start < 0:
        base = config.rstrip()
        agents_block = '\n'.join([
            "[agents]",
            "max_threads = 6",
            "max_depth = 2",
            "",
        ])
        return f"{base}\n\n{agents_block}" if base else agents_block

    section_end = len(lines)
    for i in range(agents_start + 1, len(lines)):
        if re.match(r'^\s*\[', lines[i]):
            section_end = i
            break

    # 检查 max_threads
    max_threads_idx = -1
    max_depth_idx = -1
    for i in range(agents_start + 1, section_end):
        if re.match(r'^\s*max_threads\s*=', lines[i]):
            max_threads_idx = i
        elif re.match(r'^\s*max_depth\s*=', lines[i]):
            max_depth_idx = i

    if max_threads_idx >= 0:
        lines[max_threads_idx] = "max_threads = 6"
    else:
        lines.insert(section_end, "max_threads = 6")
        section_end += 1

    if max_depth_idx >= 0:
        lines[max_depth_idx] = "max_depth = 2"
    else:
        lines.insert(section_end, "max_depth = 2")

    return '\n'.join(lines)


def get_omx_top_level_lines() -> list[str]:
    """生成 OMX 顶层配置行"""
    return [
        "# oh-my-codex top-level settings (must be before any [table])",
        'notify = ["notify-hook"]',
        'model_reasoning_effort = "high"',
        'developer_instructions = "Clawd Code with oh-my-codex integration. AGENTS.md is your orchestration brain. Use skill/keyword routing like $name plus spawned role-specialized subagents for specialized work."',
    ]


def merge_config(
    existing_config: str,
    pkg_root: str | Path | None = None,
    model_override: str | None = None,
) -> str:
    """
    合并配置 - 保留用户设置，插入 OMX 配置

    流程:
    1. 移除旧的 OMX 配置
    2. 插入新的顶层配置
    3. 插入/更新 feature flags
    4. 插入/更新 env 设置
    5. 插入/更新 agents 设置
    """
    # 1. 清理现有配置
    config = strip_omx_top_level_keys(existing_config)
    config = strip_orphaned_notify(config)

    # 2. 获取现有模型设置
    root_values = parse_root_key_values(config)
    existing_model = root_values.get("model")

    # 3. 构建新配置
    new_lines: list[str] = []

    # 添加 OMX 顶层设置
    new_lines.extend(get_omx_top_level_lines())

    # 添加模型覆盖 (如果指定)
    if model_override:
        new_lines.append(f'model = "{model_override}"')
    elif not existing_model:
        # 默认使用 o1-preview 或 Claude
        new_lines.append('model = "o1-preview"')

    new_lines.append("")  # 空行分隔

    config += '\n' + '\n'.join(new_lines)

    # 4. 更新 features
    config = upsert_feature_flags(config)

    # 5. 更新 env
    config = upsert_env_settings(config)

    # 6. 更新 agents
    config = upsert_agents_settings(config)

    return config


def merge_config_file(
    config_path: str | Path,
    backup: bool = True,
    model_override: str | None = None,
) -> str:
    """
    合并配置文件

    Args:
        config_path: 配置文件路径
        backup: 是否备份原文件
        model_override: 强制使用指定模型

    Returns:
        合并后的配置内容
    """
    config_path = Path(config_path)

    # 读取现有配置
    existing_config = ""
    if config_path.exists():
        if backup:
            backup_path = config_path.with_suffix('.toml.bak')
            backup_path.write_text(config_path.read_text())
        existing_config = config_path.read_text()

    # 合并
    merged = merge_config(existing_config, model_override=model_override)

    # 写回
    config_path.write_text(merged)

    return merged


# ==================== 便捷函数 ====================

def get_model_from_config(config: str | Path) -> str | None:
    """从配置中提取模型名称"""
    if isinstance(config, Path):
        if not config.exists():
            return None
        config = config.read_text()

    root = parse_root_key_values(config)
    return unwrap_toml_string(root.get("model"))


def get_reasoning_effort(config: str | Path) -> str | None:
    """从配置中提取推理努力级别"""
    if isinstance(config, Path):
        if not config.exists():
            return None
        config = config.read_text()

    root = parse_root_key_values(config)
    return unwrap_toml_string(root.get("model_reasoning_effort"))


# 导出
__all__ = [
    'OMX_FEATURE_FLAGS',
    'OMX_TOP_LEVEL_KEYS',
    'get_model_from_config',
    'get_reasoning_effort',
    'merge_config',
    'merge_config_file',
]
