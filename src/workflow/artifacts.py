"""
Planning Artifacts - 规划产物读取模块

从 oh-my-codex-main/src/planning/artifacts.ts 汲取。
读取 .omx/plans 目录中的 PRD、test spec、deep interview 等文件。

功能:
- read_planning_artifacts(): 读取所有规划产物路径
- is_planning_complete(): 检查 PRD + test spec 是否完整
- read_approved_execution_launch_hint(): 解析 team/ralph 执行命令
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ===== 类型定义 =====
@dataclass
class PlanningArtifacts:
    """规划产物"""
    plans_dir: str
    specs_dir: str
    prd_paths: list[str]
    test_spec_paths: list[str]
    deep_interview_spec_paths: list[str]


@dataclass
class ApprovedPlanContext:
    """已批准计划上下文"""
    source_path: str
    test_spec_paths: list[str]
    deep_interview_spec_paths: list[str]


@dataclass
class ApprovedExecutionLaunchHint:
    """已批准执行启动提示"""
    source_path: str
    test_spec_paths: list[str]
    deep_interview_spec_paths: list[str]
    mode: str  # 'team' | 'ralph'
    command: str
    task: str
    worker_count: Optional[int] = None
    agent_type: Optional[str] = None
    linked_ralph: bool = False


# ===== 常量 =====
PRD_PATTERN = re.compile(r'^prd-.*\.md$', re.IGNORECASE)
TEST_SPEC_PATTERN = re.compile(r'^test-?spec-.*\.md$', re.IGNORECASE)
DEEP_INTERVIEW_SPEC_PATTERN = re.compile(r'^deep-interview-.*\.md$', re.IGNORECASE)


# ===== 工具函数 =====
def _read_matching_paths(dir_path: str, pattern: re.Pattern) -> list[str]:
    """读取匹配模式的文件路径"""
    dir_path_obj = Path(dir_path)
    if not dir_path_obj.exists():
        return []

    try:
        return sorted([
            str(dir_path_obj / f)
            for f in os.listdir(dir_path)
            if pattern.match(f)
        ])
    except (OSError, PermissionError):
        return []


def _decode_quoted_value(raw: str) -> Optional[str]:
    """解码引号中的值"""
    normalized = raw.strip()
    if not normalized:
        return None
    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        pass
    # 处理单引号或双引号包裹
    if ((normalized.startswith('"') and normalized.endswith('"'))
            or (normalized.startswith("'") and normalized.endswith("'"))):
        return normalized[1:-1]
    return None


def _artifact_slug(path: str, prefix_pattern: re.Pattern) -> Optional[str]:
    """从文件路径提取 slug"""
    filename = os.path.basename(path)
    match = prefix_pattern.match(filename)
    if match:
        return match.group('slug')
    return None


def _filter_artifacts_for_slug(
    paths: list[str],
    prefix_pattern: re.Pattern,
    slug: Optional[str],
) -> list[str]:
    """按 slug 过滤产物"""
    if not slug:
        return []
    return [p for p in paths if _artifact_slug(p, prefix_pattern) == slug]


# ===== 公共 API =====
def get_plans_dir(cwd: str = ".") -> str:
    """获取 plans 目录路径"""
    return os.path.join(cwd, '.omx', 'plans')


def get_specs_dir(cwd: str = ".") -> str:
    """获取 specs 目录路径"""
    return os.path.join(cwd, '.omx', 'specs')


def read_planning_artifacts(cwd: str = ".") -> PlanningArtifacts:
    """读取所有规划产物路径

    参数:
        cwd: 项目根目录

    返回:
        PlanningArtifacts 包含所有产物路径
    """
    plans_dir = get_plans_dir(cwd)
    specs_dir = get_specs_dir(cwd)

    return PlanningArtifacts(
        plans_dir=plans_dir,
        specs_dir=specs_dir,
        prd_paths=_read_matching_paths(plans_dir, PRD_PATTERN),
        test_spec_paths=_read_matching_paths(plans_dir, TEST_SPEC_PATTERN),
        deep_interview_spec_paths=_read_matching_paths(specs_dir, DEEP_INTERVIEW_SPEC_PATTERN),
    )


def is_planning_complete(artifacts: PlanningArtifacts) -> bool:
    """检查规划是否完整 (PRD + test spec 都存在)

    参数:
        artifacts: 规划产物

    返回:
        True 表示规划完整
    """
    return len(artifacts.prd_paths) > 0 and len(artifacts.test_spec_paths) > 0


def read_approved_plan_text(cwd: str = ".") -> Optional[tuple[str, ApprovedPlanContext]]:
    """读取已批准的计划文本

    参数:
        cwd: 项目根目录

    返回:
        (content, context) 元组或 None
    """
    artifacts = read_planning_artifacts(cwd)
    if not is_planning_complete(artifacts):
        return None

    # 取最新的 PRD
    latest_prd_path = artifacts.prd_paths[-1]
    if not latest_prd_path or not os.path.exists(latest_prd_path):
        return None

    # 提取 slug
    slug = _artifact_slug(latest_prd_path, re.compile(r'^prd-(?P<slug>.*)\.md$', re.IGNORECASE))
    if not slug:
        return None

    try:
        with open(latest_prd_path, 'r', encoding='utf-8') as f:
            content = f.read()

        context = ApprovedPlanContext(
            source_path=latest_prd_path,
            test_spec_paths=_filter_artifacts_for_slug(
                artifacts.test_spec_paths,
                re.compile(r'^test-?spec-(?P<slug>.*)\.md$', re.IGNORECASE),
                slug
            ),
            deep_interview_spec_paths=_filter_artifacts_for_slug(
                artifacts.deep_interview_spec_paths,
                re.compile(r'^deep-interview-(?P<slug>.*)\.md$', re.IGNORECASE),
                slug
            ),
        )
        return content, context
    except (OSError, UnicodeDecodeError):
        return None


def read_approved_execution_launch_hint(
    cwd: str = ".",
    mode: str = "team",
) -> Optional[ApprovedExecutionLaunchHint]:
    """读取已批准的执行启动提示

    从 PRD 内容中解析 team 或 ralph 命令。

    参数:
        cwd: 项目根目录
        mode: 'team' 或 'ralph'

    返回:
        ApprovedExecutionLaunchHint 或 None
    """
    result = read_approved_plan_text(cwd)
    if not result:
        return None

    content, context = result

    if mode == "team":
        # 匹配 team 命令: $team [ralph] <count>[:role] "<task>"
        team_pattern = re.compile(
            r'(?P<command>(?:omx\s+team|\$team)\s+(?P<ralph>ralph\s+)?(?P<count>\d+)(?::(?P<role>[a-z][a-z0-9-]*))?\s+(?P<task>"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'))',
            re.IGNORECASE
        )
        matches = list(team_pattern.finditer(content))
        if not matches:
            return None
        last_match = matches[-1]
        groups = last_match.groupdict()
        task = _decode_quoted_value(groups.get('task', ''))
        if not task:
            return None

        return ApprovedExecutionLaunchHint(
            source_path=context.source_path,
            test_spec_paths=context.test_spec_paths,
            deep_interview_spec_paths=context.deep_interview_spec_paths,
            mode='team',
            command=groups['command'],
            task=task,
            worker_count=int(groups['count']) if groups.get('count') else None,
            agent_type=groups.get('role'),
            linked_ralph=bool(groups.get('ralph', '').strip()),
        )

    elif mode == "ralph":
        # 匹配 ralph 命令: $ralph "<task>"
        ralph_pattern = re.compile(
            r'(?P<command>(?:omx\s+ralph|\$ralph)\s+(?P<task>"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'))',
            re.IGNORECASE
        )
        matches = list(ralph_pattern.finditer(content))
        if not matches:
            return None
        last_match = matches[-1]
        groups = last_match.groupdict()
        task = _decode_quoted_value(groups.get('task', ''))
        if not task:
            return None

        return ApprovedExecutionLaunchHint(
            source_path=context.source_path,
            test_spec_paths=context.test_spec_paths,
            deep_interview_spec_paths=context.deep_interview_spec_paths,
            mode='ralph',
            command=groups['command'],
            task=task,
        )

    return None


# ===== 便捷函数 =====
def get_latest_prd_path(cwd: str = ".") -> Optional[str]:
    """获取最新的 PRD 文件路径"""
    artifacts = read_planning_artifacts(cwd)
    return artifacts.prd_paths[-1] if artifacts.prd_paths else None


def get_test_specs_for_prd(prd_path: str, cwd: str = ".") -> list[str]:
    """获取指定 PRD 对应的测试规格文件"""
    slug = _artifact_slug(prd_path, re.compile(r'^prd-(?P<slug>.*)\.md$', re.IGNORECASE))
    if not slug:
        return []

    artifacts = read_planning_artifacts(cwd)
    return _filter_artifacts_for_slug(
        artifacts.test_spec_paths,
        re.compile(r'^test-?spec-(?P<slug>.*)\.md$', re.IGNORECASE),
        slug
    )


# ===== 导出 =====
__all__ = [
    "PlanningArtifacts",
    "ApprovedPlanContext",
    "ApprovedExecutionLaunchHint",
    "get_plans_dir",
    "get_specs_dir",
    "read_planning_artifacts",
    "is_planning_complete",
    "read_approved_plan_text",
    "read_approved_execution_launch_hint",
    "get_latest_prd_path",
    "get_test_specs_for_prd",
]