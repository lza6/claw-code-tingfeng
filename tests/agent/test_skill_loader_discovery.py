"""技能发现/加载测试（回归：分组技能全部不可发现 + 正文静默截断）

两个已修缺陷：
1. `discover_skills` 只做一层 `glob('*/SKILL.md')` → `skills/reverse/<子技能>/SKILL.md`
   一个都扫不到（实测 63 个，51 个逆向技能对 agent 形同不存在）。
2. `MAX_SKILL_BODY_CHARS = 20000` 而最大的技能 23,159 字符 → 尾部指令被静默丢弃。
"""

from __future__ import annotations

from pathlib import Path

from src.agent import skill_loader
from src.agent.skill_loader import discover_skills, load_skill_body

SKILL_TEMPLATE = """---
name: {name}
description: {desc}
---

# {name}
正文第一行。
"""


def _write_skill(root: Path, name: str, desc: str = "示例技能") -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SKILL_TEMPLATE.format(name=name, desc=desc), encoding="utf-8")
    return path


class TestDiscovery:
    def test_nested_grouped_skills_are_discovered(self, tmp_path: Path):
        root = tmp_path / "skills"
        _write_skill(root, "top-level")
        _write_skill(root, "reverse/android-re")
        _write_skill(root, "reverse/api-security")

        names = {s.name for s in discover_skills(tmp_path)}
        assert {"top-level", "reverse/android-re", "reverse/api-security"} <= names

    def test_repo_skills_include_grouped_reverse_entries(self):
        """真实仓库：`skills/reverse/*` 必须出现在发现结果里"""
        names = {s.name for s in discover_skills()}
        assert "android-reverse-engineering" in names
        assert "api-security" in names
        assert len(names) > 63, "递归发现后数量应显著多于旧的一层扫描"

    def test_frontmatter_name_and_description_parsed(self, tmp_path: Path):
        root = tmp_path / "skills"
        _write_skill(root, "grp/demo", desc="做某件具体事")
        found = {s.name: s for s in discover_skills(tmp_path)}
        assert found["grp/demo"].description == "做某件具体事"

    def test_distinct_dirs_with_distinct_names_both_kept(self, tmp_path: Path):
        root = tmp_path / "skills"
        _write_skill(root, "a/dup", desc="first")
        _write_skill(root, "b/dup", desc="second")
        names = {s.name for s in discover_skills(tmp_path)}
        assert {"a/dup", "b/dup"} <= names

    def test_same_frontmatter_name_deduped(self, tmp_path: Path):
        """两个目录的 frontmatter 声明同一个 name，只应出现一次"""
        root = tmp_path / "skills"
        for sub in ("c/same", "d/same"):
            path = root / sub / "SKILL.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "---\nname: same\ndescription: d\n---\n\n# x\n", encoding="utf-8"
            )
        names = [s.name for s in discover_skills(tmp_path)]
        assert names.count("same") == 1

    def test_limit_is_respected(self, tmp_path: Path):
        root = tmp_path / "skills"
        for i in range(5):
            _write_skill(root, f"grp/s{i}")
        assert len(discover_skills(tmp_path, limit=3)) == 3

    def test_limit_covers_current_repo_skills(self):
        """仓库现有技能数必须低于上限，否则会静默丢技能"""
        assert len(discover_skills()) < skill_loader.MAX_SKILLS


class TestLoadBody:
    def test_short_body_returned_unchanged(self, tmp_path: Path):
        root = tmp_path / "skills"
        path = _write_skill(root, "grp/short")
        skill = discover_skills(tmp_path)[0]
        assert load_skill_body(skill) == path.read_text(encoding="utf-8")

    def test_truncation_is_announced_with_real_length(self, tmp_path: Path):
        root = tmp_path / "skills"
        _write_skill(root, "grp/long")
        skill = next(s for s in discover_skills(tmp_path) if s.name == "grp/long")
        body = load_skill_body(skill, max_chars=50)
        assert "内容已截断" in body
        assert "50" in body

    def test_default_limit_does_not_truncate_repo_skills(self):
        """现有最大技能（约 23k 字符）必须能完整加载"""
        for skill in discover_skills():
            assert "内容已截断" not in load_skill_body(skill), skill.name
