"""角色库（personas）测试

角色 = `personas/<name>.md`：frontmatter 放元信息，正文就是系统提示词。
三级搜索路径（repo → workdir → ~/.clawd），后者覆盖前者。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.personas import (
    MAX_PERSONA_CHARS,
    build_system_prefix,
    discover_personas,
    load_persona,
    parse_persona_file,
    personas_report,
    search_dirs,
)

PERSONA_TEMPLATE = """---
name: {name}
title: {title}
description: {desc}
category: {cat}
---

{body}
"""


def _write(directory: Path, name: str, title: str = "测试角色", body: str = "你是测试角色。") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(
        PERSONA_TEMPLATE.format(name=name, title=title, desc="d", cat="测试", body=body),
        encoding="utf-8",
    )
    return path


class TestDiscovery:
    def test_repo_personas_present(self):
        names = {p.name for p in discover_personas()}
        assert {"strict-engineer", "concise", "teacher", "reviewer"} <= names

    def test_search_dirs_order_is_repo_then_workdir_then_home(self):
        dirs = [str(d) for d in search_dirs()]
        assert len(dirs) >= 2
        assert any(d.endswith("personas") for d in dirs)

    def test_workdir_persona_overrides_repo(self, tmp_path: Path):
        _write(tmp_path / "personas", "concise", title="我的极简", body="用最短的话回答")
        persona = load_persona("concise", tmp_path)
        assert persona.title == "我的极简"
        assert "最短" in persona.system

    def test_duplicate_names_collapse_to_one(self, tmp_path: Path):
        _write(tmp_path / "personas", "concise", title="覆盖版")
        items = [p for p in discover_personas(tmp_path) if p.name == "concise"]
        assert len(items) == 1

    def test_report_excludes_system_prompt(self):
        report = personas_report()
        assert report
        assert all("system" not in item for item in report)
        assert all(item.get("chars", 0) > 0 for item in report)


class TestValidation:
    def test_unknown_persona_raises_with_available_list(self):
        with pytest.raises(KeyError) as exc:
            load_persona("no-such-persona")
        assert "可用" in str(exc.value)

    def test_invalid_name_skipped(self, tmp_path: Path):
        path = tmp_path / "personas" / "bad name!.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\nname: bad name!\n---\n\nbody\n", encoding="utf-8")
        assert parse_persona_file(path) is None

    def test_empty_body_skipped(self, tmp_path: Path):
        path = tmp_path / "personas" / "empty.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\nname: empty\ntitle: 空\n---\n\n   \n", encoding="utf-8")
        assert parse_persona_file(path) is None

    def test_oversized_system_is_truncated(self, tmp_path: Path):
        path = _write(tmp_path / "personas", "huge", body="x" * (MAX_PERSONA_CHARS + 100))
        persona = parse_persona_file(path)
        assert persona is not None
        assert len(persona.system) == MAX_PERSONA_CHARS

    def test_missing_title_falls_back_to_name(self, tmp_path: Path):
        path = tmp_path / "personas" / "plain.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\nname: plain\n---\n\n你是普通角色\n", encoding="utf-8")
        persona = parse_persona_file(path)
        assert persona is not None and persona.title == "plain"

    def test_file_without_frontmatter_still_loads(self, tmp_path: Path):
        path = tmp_path / "personas" / "bare.md"
        path.parent.mkdir(parents=True)
        path.write_text("只用正文当提示词\n", encoding="utf-8")
        persona = parse_persona_file(path)
        assert persona is not None
        assert persona.name == "bare"
        assert "只用正文" in persona.system


class TestSystemPrefix:
    def test_prefix_contains_title_and_body(self):
        persona = load_persona("reviewer")
        prefix = build_system_prefix(persona)
        assert "你当前的角色" in prefix
        assert persona.title in prefix
        assert "VERDICT" in prefix  # 正文确实在

    def test_builtin_personas_have_no_jailbreak_content(self):
        """内置角色只放工程/写作类；不内置绕过安全边界的提示词"""
        banned = ("越狱", "绕过安全", "jailbreak", "DAN", "无限制地回答任何")
        for persona in discover_personas():
            for token in banned:
                assert token not in persona.system, f"{persona.name} 含违规内容: {token}"
