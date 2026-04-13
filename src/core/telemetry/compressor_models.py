"""Output Compressor 数据模型和规则定义

从 output_compressor.py 拆分出来
包含: 枚举、数据类、内置过滤规则
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FilterStrategy(str, Enum):
    """过滤策略类型"""
    STATS_EXTRACTION = 'stats_extraction'
    ERROR_ONLY = 'error_only'
    GROUPING = 'grouping'
    DEDUPLICATION = 'deduplication'
    STRUCTURE_ONLY = 'structure_only'
    CODE_FILTERING = 'code_filtering'
    FAILURE_FOCUS = 'failure_focus'
    TREE_COMPRESSION = 'tree_compression'
    PROGRESS_FILTER = 'progress_filter'
    DUAL_MODE = 'dual_mode'
    STATE_MACHINE = 'state_machine'
    TRUNCATE = 'truncate'
    IDENTITY = 'identity'


@dataclass
class MatchOutputRule:
    """匹配输出并短路返回消息的规则"""
    pattern: str
    message: str
    unless: str | None = None


@dataclass
class ReplaceRule:
    """正则替换规则"""
    pattern: str
    replacement: str


@dataclass
class FilterRule:
    """单条过滤规则定义"""
    name: str
    command_pattern: str
    strategy: FilterStrategy = FilterStrategy.IDENTITY
    description: str = ''
    params: dict[str, Any] = field(default_factory=dict)

    # 流水线阶段
    strip_ansi: bool = False
    replace: list[ReplaceRule] = field(default_factory=list)
    match_output: list[MatchOutputRule] = field(default_factory=list)
    strip_lines_matching: list[str] = field(default_factory=list)
    keep_lines_matching: list[str] = field(default_factory=list)
    truncate_lines_at: int | None = None
    head_lines: int | None = None
    tail_lines: int | None = None
    max_lines: int | None = None
    on_empty: str | None = None


# ============================================================================
# 内置过滤器定义
# ============================================================================

GIT_FILTERS: list[FilterRule] = [
    FilterRule(
        name='git_status',
        command_pattern=r'(?i)^git\s+status\b',
        strategy=FilterStrategy.STATS_EXTRACTION,
        description='Git status: 1 行摘要 (分支 + 变更统计)',
        params={'format': 'git_status_summary'},
        strip_ansi=True,
        match_output=[
            MatchOutputRule(
                pattern=r'nothing to commit, working tree clean',
                message='ok (clean)',
                unless=r'branch .* is ahead'
            )
        ]
    ),
    FilterRule(
        name='git_add_commit_push',
        command_pattern=r'(?i)^git\s+(?:add|commit|push|pull)\b',
        description='Git add/commit/push/pull: 成功时返回 ok',
        strip_ansi=True,
        match_output=[
            MatchOutputRule(pattern=r'^Everything up-to-date$', message='ok (up-to-date)'),
            MatchOutputRule(pattern=r'^Already up to date\.$', message='ok (up-to-date)'),
        ],
        on_empty='ok'
    ),
    FilterRule(
        name='git_log_short',
        command_pattern=r'(?i)^git\s+log\b',
        strategy=FilterStrategy.CODE_FILTERING,
        description='Git log: 仅保留 hash + 作者 + 日期 + 消息',
        params={'max_lines': 30, 'format': 'git_log_condensed'},
        max_lines=40
    ),
]

TEST_FILTERS: list[FilterRule] = [
    FilterRule(
        name='pytest_output',
        command_pattern=r'(?i)(?:pytest|python\s+-m\s+pytest|python\s+\S*pytest)',
        strategy=FilterStrategy.FAILURE_FOCUS,
        description='Pytest: 仅显示失败用例和摘要',
        strip_ansi=True,
        max_lines=100
    ),
]

LINT_FILTERS: list[FilterRule] = [
    FilterRule(
        name='ruff_output',
        command_pattern=r'(?i)\b(?:uv\s+)?ruff\b',
        strategy=FilterStrategy.ERROR_ONLY,
        strip_ansi=True,
        max_lines=50
    ),
]

FILE_FILTERS: list[FilterRule] = [
    FilterRule(
        name='ls_output',
        command_pattern=r'(?i)^\b(?:ls|dir)\b',
        strip_ansi=True,
        truncate_lines_at=120,
        max_lines=50
    ),
    FilterRule(
        name='tree_output',
        command_pattern=r'(?i)^\btree\b',
        strategy=FilterStrategy.TREE_COMPRESSION,
        params={'max_depth': 3},
        max_lines=100
    ),
]

DEFAULT_FILTER = FilterRule(
    name='default_truncate',
    command_pattern=r'.*',
    strategy=FilterStrategy.TRUNCATE,
    description='默认: 截断到 20000 字符',
    params={'max_chars': 20000, 'max_lines': 500},
)


def load_builtin_filters() -> list[FilterRule]:
    """加载所有内置过滤器"""
    return [
        *GIT_FILTERS,
        *TEST_FILTERS,
        *LINT_FILTERS,
        *FILE_FILTERS,
        DEFAULT_FILTER,
    ]
