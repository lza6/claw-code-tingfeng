"""Skill 渐进披露与按需加载测试（P1-10）。"""
from __future__ import annotations

from pathlib import Path

from src.agent._system_prompt import build_system_prompt
from src.agent.skill_loader import discover_skills, load_skill_body
from src.tools_runtime.skill_tool import SkillTool


def _make_skill(root: Path, name: str, description: str, body: str = '# Steps\n1. do it') -> Path:
    skill_dir = root / 'skills' / name
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / 'SKILL.md'
    skill_md.write_text(
        f'---\nname: {name}\ndescription: {description}\n---\n\n{body}\n',
        encoding='utf-8',
    )
    return skill_md


def test_discover_reads_frontmatter(tmp_path):
    _make_skill(tmp_path, 'demo-skill', '演示技能')
    skills = discover_skills(tmp_path)
    hit = [s for s in skills if s.name == 'demo-skill']
    assert hit, '应发现 demo-skill'
    assert hit[0].description == '演示技能'
    assert hit[0].path.name == 'SKILL.md'


def test_system_prompt_injects_summary_only(tmp_path):
    _make_skill(tmp_path, 'demo-skill', '演示技能', body='# Steps\nSECRET_BODY_MARKER')
    skills = discover_skills(tmp_path)
    prompt = build_system_prompt({}, skills=skills)

    assert '可用技能' in prompt
    assert 'demo-skill' in prompt
    assert '演示技能' in prompt
    # 渐进披露：正文不应常驻系统提示
    assert 'SECRET_BODY_MARKER' not in prompt
    assert 'SkillTool' in prompt


def test_no_skills_means_no_block():
    prompt = build_system_prompt({}, skills=[])
    assert '可用技能' not in prompt


def test_skill_tool_loads_body(tmp_path):
    _make_skill(tmp_path, 'demo-skill', '演示技能', body='# Steps\nSECRET_BODY_MARKER')
    tool = SkillTool(workdir=tmp_path)
    result = tool.execute(name='demo-skill')

    assert result.success is True
    assert 'SECRET_BODY_MARKER' in result.output


def test_skill_tool_rejects_unknown_and_traversal(tmp_path):
    _make_skill(tmp_path, 'demo-skill', '演示技能')
    tool = SkillTool(workdir=tmp_path)

    for bad in ('does-not-exist', '../../etc/passwd', '/etc/passwd', ''):
        result = tool.execute(name=bad)
        assert result.success is False, bad


def test_load_skill_body_truncates(tmp_path):
    _make_skill(tmp_path, 'long-skill', '长技能', body='x' * 500)
    skill = next(s for s in discover_skills(tmp_path) if s.name == 'long-skill')
    body = load_skill_body(skill, max_chars=100)
    # 正文只保留前 max_chars 个字符，随后附明确截断说明（含原文长度与文件路径）
    head, _, notice = body.partition('[内容已截断')
    assert len(head.rstrip(chr(10))) == 100
    assert '内容已截断' in body
    assert str(len(skill.path.read_text(encoding='utf-8'))) in notice
    assert '100' in notice
