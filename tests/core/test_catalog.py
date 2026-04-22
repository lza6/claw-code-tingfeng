"""Tests for src/core/catalog.py"""

import os
import json
import pytest
from datetime import datetime
from pathlib import Path

from src.core.catalog import (
    SkillManifest,
    AgentManifest,
    CatalogManifest,
    generate_catalog_manifest,
    _parse_skill_markdown,
    CatalogError,
    ManifestValidationError,
    validate_catalog_manifest,
    list_skill_names,
    get_skill_info,
    get_catalog_counts,
    to_public_catalog_contract,
)


# ---------------------------------------------------------------------------
# SKILL.md Parsing
# ---------------------------------------------------------------------------

def test_parse_skill_markdown_basic(tmp_path):
    """无 frontmatter 时提取第一行为描述。"""
    skill_md = tmp_path / 'SKILL.md'
    content = '# My Skill\n\nSome details...\n'
    skill_md.write_text(content, encoding='utf-8')

    meta = _parse_skill_markdown(str(skill_md))
    assert meta['name'] == skill_md.parent.name
    assert 'Some details' in meta['description'] or 'My Skill' in meta['description']
    assert meta['status'] == 'active'


def test_parse_skill_markdown_with_frontmatter(tmp_path):
    """含 frontmatter 正确解析字段。"""
    skill_md = tmp_path / 'SKILL.md'
    content = '''---
name: debugger
description: Debugs code and fixes issues
status: alias
canonical: code-reviewer
tags: [testing, quality]
core: true
---
Full description here.
'''
    skill_md.write_text(content, encoding='utf-8')

    meta = _parse_skill_markdown(str(skill_md))
    assert meta['name'] == 'debugger'
    assert meta['description'] == 'Debugs code and fixes issues'
    assert meta['status'] == 'alias'
    assert meta['canonical'] == 'code-reviewer'
    assert 'testing' in meta['tags']
    assert meta['core'] is True


def test_parse_skill_markdown_missing_file(tmp_path):
    """文件不存在返回空字典。"""
    missing = tmp_path / 'no_SKILL.md'
    meta = _parse_skill_markdown(str(missing))
    assert meta == {}


# ---------------------------------------------------------------------------
# Manifest Generation
# ---------------------------------------------------------------------------

def test_generate_catalog_manifest_empty(tmp_path, monkeypatch):
    """无技能时返回空清单。"""
    # 直接 patch catalog 模块中的 list_installed_skill_directories
    monkeypatch.setattr('src.core.catalog.list_installed_skill_directories', lambda root=None: [])
    monkeypatch.setattr('src.core.catalog.get_project_root', lambda: str(tmp_path))

    manifest = generate_catalog_manifest(str(tmp_path))
    assert manifest.skills == []
    assert manifest.agents == []
    assert manifest.catalog_version == '1.0.0'


def test_generate_catalog_manifest_with_skills(tmp_path, monkeypatch):
    """正确扫描并解析技能。"""
    skills_dir = tmp_path / '.codex' / 'skills'
    skills_dir.mkdir(parents=True)

    # 创建两个 skill
    for name in ['code-reviewer', 'debugger']:
        skill_dir = skills_dir / name
        skill_dir.mkdir()
        (skill_dir / 'SKILL.md').write_text(
            f'# {name}\n\nDescription for {name}', encoding='utf-8'
        )

    # Mock list_installed_skill_directories 返回扫描结果
    from src.core.paths import InstalledSkillDirectory
    mock_skills = [
        InstalledSkillDirectory(name='code-reviewer', path=str(skills_dir / 'code-reviewer'), scope='user'),
        InstalledSkillDirectory(name='debugger', path=str(skills_dir / 'debugger'), scope='user'),
    ]
    monkeypatch.setattr('src.core.catalog.list_installed_skill_directories', lambda root=None: mock_skills)

    manifest = generate_catalog_manifest(str(tmp_path))
    names = {s.name for s in manifest.skills}
    assert names == {'code-reviewer', 'debugger'}


def test_generate_catalog_manifest_ignores_invalid(tmp_path, monkeypatch):
    """无 SKILL.md 的目录被跳过。"""
    skills_dir = tmp_path / 'skills'
    skills_dir.mkdir()
    (skills_dir / 'incomplete').mkdir()  # 无 SKILL.md

    from src.core.paths import InstalledSkillDirectory
    mock_skills = [
        InstalledSkillDirectory(name='incomplete', path=str(skills_dir / 'incomplete'), scope='user'),
    ]
    monkeypatch.setattr('src.core.catalog.list_installed_skill_directories', lambda root=None: mock_skills)

    manifest = generate_catalog_manifest(str(tmp_path))
    assert len(manifest.skills) == 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_validate_catalog_manifest_valid():
    raw = {
        'catalog_version': '1.0.0',
        'generated_at': '2025-01-01T00:00:00',
        'skills': [
            {'name': 'test', 'description': 'A test skill', 'path': '/tmp/test', 'scope': 'user'}
        ],
        'agents': []
    }
    manifest = validate_catalog_manifest(raw)
    assert manifest.catalog_version == '1.0.0'
    assert len(manifest.skills) == 1
    assert manifest.skills[0].name == 'test'


def test_validate_catalog_manifest_missing_name():
    raw = {
        'catalog_version': '1.0.0',
        'skills': [{'description': 'no name'}]  # 缺失 name
    }
    with pytest.raises(ManifestValidationError):
        validate_catalog_manifest(raw)


# ---------------------------------------------------------------------------
# Public Contract & Stats
# ---------------------------------------------------------------------------

def test_get_catalog_counts():
    manifest = CatalogManifest(
        skills=[
            SkillManifest(name='a', description='', path='', scope='user', core=True),
            SkillManifest(name='b', description='', path='', scope='user'),
            SkillManifest(name='c', description='', path='', scope='user', status='alias'),
        ],
        agents=[
            AgentManifest(
                name='planner', description='', reasoning_effort='medium',
                posture='frontier-orchestrator', model_class='frontier',
                routing_role='leader', tools='analysis', category='build'
            )
        ]
    )
    counts = get_catalog_counts(manifest)
    assert counts.total_skills == 3
    assert counts.core_skills == 1
    assert counts.aliased_skills == 1
    assert counts.total_agents == 1
    assert counts.by_category.get('build') == 1


def test_to_public_catalog_contract():
    manifest = CatalogManifest(
        catalog_version='1.0.0',
        generated_at='2025-01-01T00:00:00',
        skills=[
            SkillManifest(name='debugger', description='', path='', scope='user', status='alias', canonical='fixer'),
            SkillManifest(name='internal-skill', description='', path='', scope='user', status='internal'),
        ],
        agents=[]
    )
    contract = to_public_catalog_contract(manifest)
    assert contract.version == '1.0.0'
    assert 'debugger' in [a['name'] for a in contract.aliases]
    assert contract.aliases[0]['canonical'] == 'fixer'
    assert 'internal-skill' in contract.internal_hidden


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def test_list_skill_names(monkeypatch):
    manifest = CatalogManifest(
        skills=[
            SkillManifest(name='a', description='', path='', scope='user', status='active'),
            SkillManifest(name='b', description='', path='', scope='user', status='active'),
            SkillManifest(name='c', description='', path='', scope='user', status='alias'),
        ]
    )
    monkeypatch.setattr('src.core.catalog.generate_catalog_manifest', lambda root=None: manifest)
    names = list_skill_names()
    assert set(names) == {'a', 'b'}


def test_get_skill_info_found(monkeypatch):
    manifest = CatalogManifest(
        skills=[SkillManifest(name='debugger', description='Debug', path='/tmp', scope='user')]
    )
    monkeypatch.setattr('src.core.catalog.generate_catalog_manifest', lambda root=None: manifest)
    skill = get_skill_info('debugger')
    assert skill is not None
    assert skill.name == 'debugger'


def test_get_skill_info_not_found(monkeypatch):
    monkeypatch.setattr('src.core.catalog.generate_catalog_manifest', lambda root=None: CatalogManifest())
    assert get_skill_info('nonexistent') is None
