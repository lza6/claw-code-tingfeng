"""Skill and agent catalog for claw-code-tingfeng.

参考: oh-my-codex-main/src/catalog/reader.ts
提供技能/代理清单、计数、别名解析等功能。

主要用途:
- 启动时扫描 skills/ 目录生成清单
- 提供技能去重与合并声明
- 供 CLI 命令 (skill list, skill info) 使用
- 支持配置文件的技能注册表同步
"""

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .paths import get_project_root, list_installed_skill_directories

__all__ = [
    'AgentManifest',
    'CatalogCounts',
    'CatalogError',
    'CatalogManifest',
    'SkillManifest',
    'generate_catalog_manifest',
    'get_catalog_counts',
    'read_catalog_manifest',
    'to_public_catalog_contract',
    'try_read_catalog_manifest',
    'validate_catalog_manifest',
]

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CatalogError(Exception):
    """清单相关错误基类。"""
    pass


class ManifestNotFoundError(CatalogError):
    """清单文件未找到。"""
    pass


class ManifestValidationError(CatalogError):
    """清单格式校验失败。"""
    pass


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class SkillManifest:
    """Skill 清单条目。"""
    name: str
    description: str
    path: str
    scope: str  # 'project' 或 'user'
    status: str = 'active'  # 'active' | 'alias' | 'merged' | 'internal'
    canonical: str | None = None  # 若 status 为 alias/merged，指向目标 skill
    tags: list[str] = field(default_factory=list)
    core: bool = False
    # 元数据
    checksum: str | None = None
    size_bytes: int | None = None
    last_modified: str | None = None


@dataclass
class AgentManifest:
    """Agent 清单条目。"""
    name: str
    description: str
    reasoning_effort: str  # 'low' | 'medium' | 'high'
    posture: str  # 'frontier-orchestrator' | 'deep-worker' | 'fast-lane'
    model_class: str  # 'frontier' | 'standard' | 'fast'
    routing_role: str  # 'leader' | 'specialist' | 'executor'
    tools: str  # 'read-only' | 'analysis' | 'execution' | 'data'
    category: str  # 'build' | 'review' | 'domain' | 'product' | 'coordination'


@dataclass
class CatalogManifest:
    """完整技能/代理清单。"""
    catalog_version: str = '1.0.0'
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    skills: list[SkillManifest] = field(default_factory=list)
    agents: list[AgentManifest] = field(default_factory=list)


@dataclass
class CatalogCounts:
    """Skill/Agent 计数统计。"""
    total_skills: int = 0
    core_skills: int = 0
    aliased_skills: int = 0
    merged_skills: int = 0
    total_agents: int = 0
    by_category: dict[str, int] = field(default_factory=dict)


@dataclass
class PublicCatalogContract:
    """公开 API 清单格式（供 CLI 或外部工具消费）。"""
    generated_at: str
    version: str
    counts: CatalogCounts
    core_skills: list[str]
    skills: list[SkillManifest]
    agents: list[AgentManifest]
    aliases: list[dict[str, str]]  # [{'name': ..., 'canonical': ...}, ...]
    internal_hidden: list[str]


# ---------------------------------------------------------------------------
# SKILL.md Parsing
# ---------------------------------------------------------------------------

def _parse_skill_markdown(path: str) -> dict[str, Any]:
    """解析 SKILL.md 提取元数据。

    支持的 frontmatter 格式 (YAML-like):
    ```markdown
    ---
    name: skill-name
    description: Short one-line description
    status: active|alias|merged|internal
    canonical: target-skill  # if status is alias/merged
    tags: [tag1, tag2]
    core: true|false
    ---
    ```

    若无 frontmatter，则使用文件名和空描述。
    """
    try:
        with open(path, encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return {}

    meta = {
        'name': os.path.basename(os.path.dirname(path)),
        'description': '',
        'status': 'active',
        'canonical': None,
        'tags': [],
        'core': False,
    }

    # 简单 frontmatter 解析
    if content.startswith('---'):
        end_marker = content.find('\n---\n', 4)
        if end_marker > 0:
            frontmatter = content[4:end_marker]
            for line in frontmatter.splitlines():
                if ':' not in line:
                    continue
                key, _, val = line.partition(':')
                key = key.strip().lower()
                val = val.strip()
                if key in ('name', 'description', 'status', 'canonical'):
                    meta[key] = val
                elif key == 'tags':
                    # 解析列表: [a, b] 或 a, b
                    val = val.strip('[]')
                    meta[key] = [t.strip() for t in val.split(',') if t.strip()]
                elif key == 'core':
                    meta[key] = val.lower() in ('true', '1', 'yes')

    # 若无描述，取第一行非空
    if not meta['description']:
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                meta['description'] = line[:120]
                break

    # 文件级统计
    stat = os.stat(path)
    meta['checksum'] = hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
    meta['size_bytes'] = stat.st_size
    meta['last_modified'] = datetime.fromtimestamp(stat.st_mtime).isoformat()

    return meta


# ---------------------------------------------------------------------------
# Manifest Generation
# ---------------------------------------------------------------------------

def generate_catalog_manifest(project_root: str | None = None) -> CatalogManifest:
    """扫描技能目录生成清单。

    Args:
        project_root: 项目根目录，默认自动查找

    Returns:
        完整清单对象
    """
    root = project_root or get_project_root()
    skill_dirs = list_installed_skill_directories(root)

    manifest = CatalogManifest(
        catalog_version='1.0.0',
        generated_at=datetime.now().isoformat(),
    )

    for skill_dir in skill_dirs:
        skill_md = os.path.join(skill_dir.path, 'SKILL.md')
        if not os.path.isfile(skill_md):
            continue

        meta = _parse_skill_markdown(skill_md)
        skill = SkillManifest(
            name=skill_dir.name,
            description=meta.get('description', ''),
            path=skill_dir.path,
            scope=skill_dir.scope,
            status=meta.get('status', 'active'),
            canonical=meta.get('canonical'),
            tags=meta.get('tags', []),
            core=meta.get('core', False),
            checksum=meta.get('checksum'),
            size_bytes=meta.get('size_bytes'),
            last_modified=meta.get('last_modified'),
        )
        manifest.skills.append(skill)

    # 排序：core first，然后 alphabetical
    manifest.skills.sort(key=lambda s: (0 if s.core else 1, s.name.lower()))

    # TODO: 扫描 agents/ 目录生成 AgentManifest（暂留空）
    # manifest.agents = ...

    return manifest


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_catalog_manifest(manifest: dict) -> CatalogManifest:
    """验证外部输入的清单字典，转换为强类型 CatalogManifest。

    Raises:
        ManifestValidationError: 校验失败
    """
    try:
        version = str(manifest.get('catalog_version', '1.0.0'))
        generated_at = str(manifest.get('generated_at', datetime.now().isoformat()))
    except Exception as e:
        raise ManifestValidationError(f'Invalid top-level fields: {e}')

    skills = []
    for s in manifest.get('skills', []):
        if not isinstance(s, dict) or 'name' not in s:
            raise ManifestValidationError(f'Invalid skill entry: {s}')
        skills.append(SkillManifest(
            name=s['name'],
            description=str(s.get('description', '')),
            path=str(s.get('path', '')),
            scope=str(s.get('scope', 'user')),
            status=str(s.get('status', 'active')),
            canonical=s.get('canonical'),
            tags=list(s.get('tags', [])),
            core=bool(s.get('core', False)),
            checksum=s.get('checksum'),
            size_bytes=s.get('size_bytes'),
            last_modified=s.get('last_modified'),
        ))

    return CatalogManifest(
        catalog_version=version,
        generated_at=generated_at,
        skills=skills,
        agents=[],
    )


# ---------------------------------------------------------------------------
# Read / Try-Read (with caching)
# ---------------------------------------------------------------------------

_cached_manifest: CatalogManifest | None = None
_cached_path: str | None = None


def _resolve_manifest_path(pkg_root: str) -> str:
    """定位清单文件路径。

    搜索顺序:
    1. <pkg_root>/templates/catalog-manifest.json
    2. <pkg_root>/src/catalog/manifest.json
    3. <pkg_root>/dist/catalog/manifest.json
    """
    candidates = [
        os.path.join(pkg_root, 'templates', 'catalog-manifest.json'),
        os.path.join(pkg_root, 'src', 'catalog', 'manifest.json'),
        os.path.join(pkg_root, 'dist', 'catalog', 'manifest.json'),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    raise ManifestNotFoundError('catalog-manifest.json not found in standard locations')


def read_catalog_manifest(pkg_root: str | None = None) -> CatalogManifest:
    """读取并验证清单文件。

    使用简单缓存（进程内）。
    """
    global _cached_manifest, _cached_path

    root = pkg_root or get_project_root()
    path = _resolve_manifest_path(root)

    if _cached_manifest and _cached_path == path:
        return _cached_manifest

    with open(path, encoding='utf-8') as f:
        raw = json.load(f)

    manifest = validate_catalog_manifest(raw)
    _cached_manifest = manifest
    _cached_path = path

    return manifest


def try_read_catalog_manifest(pkg_root: str | None = None) -> CatalogManifest | None:
    """尝试读取清单，文件不存在或错误时返回 None。"""
    try:
        return read_catalog_manifest(pkg_root)
    except (ManifestNotFoundError, OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Counts & Stats
# ---------------------------------------------------------------------------

def get_catalog_counts(manifest: CatalogManifest | None = None) -> CatalogCounts:
    """从清单提取统计计数。

    Args:
        manifest: 清单对象，默认实时扫描

    Returns:
        统计结果
    """
    if manifest is None:
        manifest = generate_catalog_manifest()

    counts = CatalogCounts(
        total_skills=len(manifest.skills),
        core_skills=sum(1 for s in manifest.skills if s.core),
        aliased_skills=sum(1 for s in manifest.skills if s.status == 'alias'),
        merged_skills=sum(1 for s in manifest.skills if s.status == 'merged'),
        total_agents=len(manifest.agents),
    )

    # 按分类统计 agent
    for agent in manifest.agents:
        counts.by_category[agent.category] = counts.by_category.get(agent.category, 0) + 1

    return counts


# ---------------------------------------------------------------------------
# Public Contract
# ---------------------------------------------------------------------------

def to_public_catalog_contract(manifest: CatalogManifest) -> PublicCatalogContract:
    """转换为公开 API 格式（供 CLI 输出或外部调用）。"""
    aliases = [
        {'name': s.name, 'canonical': s.canonical}
        for s in manifest.skills
        if s.status in ('alias', 'merged') and s.canonical
    ]
    internal_hidden = [s.name for s in manifest.skills if s.status == 'internal']

    return PublicCatalogContract(
        generated_at=manifest.generated_at,
        version=manifest.catalog_version,
        counts=get_catalog_counts(manifest),
        core_skills=[s.name for s in manifest.skills if s.core],
        skills=manifest.skills,
        agents=manifest.agents,
        aliases=aliases,
        internal_hidden=internal_hidden,
    )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def list_skill_names(project_root: str | None = None) -> list[str]:
    """快速列出所有可用技能名称。"""
    manifest = generate_catalog_manifest(project_root)
    return [s.name for s in manifest.skills if s.status == 'active']


def get_skill_info(name: str, project_root: str | None = None) -> SkillManifest | None:
    """获取单个技能详细信息。"""
    manifest = generate_catalog_manifest(project_root)
    for skill in manifest.skills:
        if skill.name == name:
            return skill
    return None
