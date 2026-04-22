"""Path utilities for claw-code-tingfeng.

统一管理项目目录、Codex 配置路径、Skill 和 Agent 查找。
参考: oh-my-codex-main/src/utils/paths.ts

设计原则:
- 所有路径操作通过此模块，消除分散的硬编码
- 支持 user/project 两级 scope
- 向后兼容现有 Codex ~/.codex 结构
"""

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    'InstalledSkillDirectory',
    'SkillRootOverlapReport',
    'detect_legacy_skill_overlap',
    'get_codex_agents_dir',
    'get_codex_config_path',
    'get_codex_home',
    'get_codex_prompts_dir',
    'get_legacy_user_skills_dir',
    'get_omx_logs_dir',
    'get_omx_notepad_path',
    'get_omx_plans_dir',
    'get_omx_project_memory_path',
    'get_omx_state_dir',
    'get_project_codex_agents_dir',
    'get_project_root',
    'get_project_skills_dir',
    'get_user_skills_dir',
    'list_installed_skill_directories',
]

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

CODEX_HOME_ENV = 'CODEX_HOME'
CLAUDE_HOME_ENV = 'CLAUDE_HOME'  # 兼容旧环境变量


def get_codex_home() -> str:
    """返回 Codex 主目录（POSIX 风格绝对路径）。

    优先级:
    1. $CODEX_HOME 环境变量
    2. $CLAUDE_HOME (旧命名，向后兼容)
    3. ~/.codex (默认)

    Returns:
        Codex 主目录路径（使用 / 分隔符）
    """
    env_val = os.environ.get(CODEX_HOME_ENV) or os.environ.get(CLAUDE_HOME_ENV)
    if env_val:
        # 环境变量值优先，只做 ~ 展开，保持路径风格一致性（使用 /）
        expanded = os.path.expanduser(env_val)
        return expanded.replace('\\', '/')

    # 使用 Path.home() 跨平台获取真实 Home 目录
    try:
        home_dir = Path.home()
        if not home_dir or str(home_dir) == '~':
            raise ValueError('Invalid home directory')
    except Exception:
        # 回退到标准环境变量
        home_env = os.environ.get('HOME') or os.environ.get('USERPROFILE')
        if not home_env:
            home_dir = Path.cwd()
        else:
            home_dir = Path(home_env)

    return str(home_dir / '.codex')


def get_project_root(start_dir: str | None = None) -> str:
    """向上查找项目根目录（含 .git 或 .codex 的目录）。

    Args:
        start_dir: 起始目录，默认当前工作目录

    Returns:
        项目根目录路径，未找到则返回 start_dir
    """
    current = start_dir or os.getcwd()
    while True:
        if os.path.isdir(os.path.join(current, '.git')):
            return current
        if os.path.isdir(os.path.join(current, '.codex')):
            return current
        parent = os.path.dirname(current)
        if parent == current:  # 到达根目录
            break
        current = parent
    return start_dir or os.getcwd()


# ---------------------------------------------------------------------------
# Config & Prompts
# ---------------------------------------------------------------------------

def get_codex_config_path() -> str:
    """返回 config.toml 路径 (~/.codex/config.toml)。"""
    home = get_codex_home()
    base = home.rstrip('/\\')
    return f"{base}/config.toml"


def get_codex_prompts_dir() -> str:
    """返回用户级 prompts 目录 (~/.codex/prompts/)。"""
    home = get_codex_home()
    base = home.rstrip('/\\')
    return f"{base}/prompts"


# ---------------------------------------------------------------------------
# Agents (Codex Native)
# ---------------------------------------------------------------------------

def get_codex_agents_dir(codex_home: str | None = None) -> str:
    """返回用户级 native agents 目录 (~/.codex/agents/)。"""
    base = codex_home or get_codex_home()
    return os.path.join(base, 'agents')


def get_project_codex_agents_dir(project_root: str | None = None) -> str:
    """返回项目级 native agents 目录 (.codex/agents/)。"""
    root = get_project_root() if project_root is None else project_root
    return os.path.join(root, '.codex', 'agents')


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

def get_user_skills_dir() -> str:
    """返回用户级技能目录 (~/.codex/skills/)。"""
    home = get_codex_home()
    home_stripped = home.rstrip('/\\')
    return f"{home_stripped}/skills"


def get_project_skills_dir(project_root: str | None = None) -> str:
    """返回项目级技能目录 (.codex/skills/)。"""
    root = get_project_root() if project_root is None else project_root
    return os.path.join(root, '.codex', 'skills')


def get_legacy_user_skills_dir() -> str:
    """返回历史遗留技能目录 (~/.agents/skills/)。"""
    home = os.path.expanduser('~')
    home_stripped = home.rstrip('/\\')
    return f"{home_stripped}/.agents/skills"


# ---------------------------------------------------------------------------
# OMX State (Claw-d Specific)
# ---------------------------------------------------------------------------

def get_omx_state_dir(project_root: str | None = None) -> str:
    """返回 OMX 状态目录 (.omx/state/)。"""
    root = get_project_root() if project_root is None else project_root
    return os.path.join(root, '.omx', 'state')


def get_omx_project_memory_path(project_root: str | None = None) -> str:
    """返回项目记忆文件 (.omx/project-memory.json)。"""
    root = get_project_root() if project_root is None else project_root
    return os.path.join(root, '.omx', 'project-memory.json')


def get_omx_notepad_path(project_root: str | None = None) -> str:
    """返回记事本文件 (.omx/notepad.md)。"""
    root = get_project_root() if project_root is None else project_root
    return os.path.join(root, '.omx', 'notepad.md')


def get_omx_plans_dir(project_root: str | None = None) -> str:
    """返回计划目录 (.omx/plans/)。"""
    root = get_project_root() if project_root is None else project_root
    return os.path.join(root, '.omx', 'plans')


def get_omx_logs_dir(project_root: str | None = None) -> str:
    """返回日志目录 (.omx/logs/)。"""
    root = get_project_root() if project_root is None else project_root
    return os.path.join(root, '.omx', 'logs')


# ---------------------------------------------------------------------------
# Skill Discovery & Catalog
# ---------------------------------------------------------------------------

@dataclass
class InstalledSkillDirectory:
    """已安装技能目录信息。"""
    name: str
    path: str
    scope: str  # 'project' 或 'user'


@dataclass
class SkillRootOverlapReport:
    """用户级技能目录与遗留目录的重叠报告。"""
    canonical_dir: str
    legacy_dir: str
    canonical_exists: bool
    legacy_exists: bool
    canonical_resolved_dir: str | None
    legacy_resolved_dir: str | None
    same_resolved_target: bool
    canonical_skill_count: int
    legacy_skill_count: int
    overlapping_skill_names: list[str]
    mismatched_skill_names: list[str]


def _read_installed_skills_from_dir(dir_path: str, scope: str) -> list[InstalledSkillDirectory]:
    """从目录读取已安装技能列表。

    Args:
        dir_path: 技能根目录
        scope: 作用域 ('project' 或 'user')

    Returns:
        技能目录列表，按名称排序
    """
    if not os.path.isdir(dir_path):
        return []

    entries = []
    try:
        for entry in os.scandir(dir_path):
            if not entry.is_dir():
                continue
            skill_md = os.path.join(entry.path, 'SKILL.md')
            if os.path.isfile(skill_md):
                entries.append(InstalledSkillDirectory(
                    name=entry.name,
                    path=entry.path,
                    scope=scope
                ))
    except OSError:
        return []

    entries.sort(key=lambda x: x.name.lower())
    return entries


def list_installed_skill_directories(project_root: str | None = None
                                     ) -> list[InstalledSkillDirectory]:
    """按优先级返回已安装技能目录列表。

    优先级: project > user (同名 skill 以 project 为准)

    Args:
        project_root: 项目根目录，默认自动查找

    Returns:
        去重后的技能目录列表
    """
    root = project_root or get_project_root()
    ordered_dirs = [
        (get_project_skills_dir(root), 'project'),
        (get_user_skills_dir(), 'user'),
    ]

    deduped: list[InstalledSkillDirectory] = []
    seen_names = set()

    for dir_path, scope in ordered_dirs:
        skills = _read_installed_skills_from_dir(dir_path, scope)
        for skill in skills:
            if skill.name in seen_names:
                continue
            seen_names.add(skill.name)
            deduped.append(skill)

    return deduped


def _hash_skill_directory(skills: list[InstalledSkillDirectory]) -> dict:
    """计算技能目录内容的哈希映射。

    Args:
        skills: 技能目录列表

    Returns:
        {skill_name: sha256_hash}
    """
    import hashlib

    hashes = {}
    for skill in skills:
        try:
            with open(os.path.join(skill.path, 'SKILL.md'), encoding='utf-8') as f:
                content = f.read()
            hashes[skill.name] = hashlib.sha256(content.encode('utf-8')).hexdigest()
        except (OSError, UnicodeError):
            pass
    return hashes


def detect_legacy_skill_overlap(
    canonical_dir: str | None = None,
    legacy_dir: str | None = None
) -> SkillRootOverlapReport:
    """检测新版 (~/.codex/skills) 与旧版 (~/.agents/skills) 技能目录的重叠情况。

    用于迁移引导，帮助用户识别重复安装的 skill。

    Args:
        canonical_dir: 新版技能目录（默认 ~/.codex/skills）
        legacy_dir: 旧版技能目录（默认 ~/.agents/skills）

    Returns:
        重叠报告，包含同名但内容不同的 skill 列表
    """
    canonical_dir = canonical_dir or get_user_skills_dir()
    legacy_dir = legacy_dir or get_legacy_user_skills_dir()

    canonical_exists = os.path.isdir(canonical_dir)
    legacy_exists = os.path.isdir(legacy_dir)

    # 异步读取（保持接口兼容，内部同步实现）
    canonical_skills = _read_installed_skills_from_dir(canonical_dir, 'user') if canonical_exists else []
    legacy_skills = _read_installed_skills_from_dir(legacy_dir, 'user') if legacy_exists else []

    # 解析真实路径（解决 symlink）
    def resolve(path: str) -> str | None:
        try:
            return os.path.realpath(path)
        except OSError:
            return None

    canonical_resolved = resolve(canonical_dir) if canonical_exists else None
    legacy_resolved = resolve(legacy_dir) if legacy_exists else None

    canonical_hashes = _hash_skill_directory(canonical_skills)
    legacy_hashes = _hash_skill_directory(legacy_skills)

    canonical_names = {s.name for s in canonical_skills}
    legacy_names = {s.name for s in legacy_skills}

    overlapping = sorted(canonical_names & legacy_names)
    mismatched = [
        name for name in overlapping
        if canonical_hashes.get(name) != legacy_hashes.get(name)
    ]

    return SkillRootOverlapReport(
        canonical_dir=canonical_dir,
        legacy_dir=legacy_dir,
        canonical_exists=canonical_exists,
        legacy_exists=legacy_exists,
        canonical_resolved_dir=canonical_resolved,
        legacy_resolved_dir=legacy_resolved,
        same_resolved_target=(canonical_resolved is not None
                              and legacy_resolved is not None
                              and canonical_resolved == legacy_resolved),
        canonical_skill_count=len(canonical_skills),
        legacy_skill_count=len(legacy_skills),
        overlapping_skill_names=overlapping,
        mismatched_skill_names=mismatched,
    )


# ---------------------------------------------------------------------------
# Package Root (用于查找 dist/ 等资源)
# ---------------------------------------------------------------------------

def get_package_root() -> str:
    """返回包根目录（含 package.json 或 pyproject.toml 的目录）。

    用于定位构建产物（dist/、scripts/）的相对路径。

    Returns:
        包根目录绝对路径
    """
    # 从当前文件向上查找
    try:
        current = os.path.dirname(os.path.abspath(__file__))
    except TypeError:
        # __file__ 可能未定义（如交互式环境）
        return os.getcwd()

    # 向上最多 5 层
    for _ in range(5):
        if os.path.isfile(os.path.join(current, 'pyproject.toml')):
            return current
        if os.path.isfile(os.path.join(current, 'package.json')):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    # 回退到 cwd
    return os.getcwd()
