"""Skill 发现与按需加载。

设计目标（参考 Anthropic Skills / addyosmani agent-skills / cc-polymath）：
- **渐进披露**：常驻上下文只放 name + description，正文按需读取；
- **单一事实源**：直接读取 `skills/<name>/SKILL.md`，不维护第二份清单；
- **低成本**：只扫描有限目录，限制数量与单文件读取大小。

这不是 skill 执行器：真实执行仍由 skill 内捆绑脚本 / 工具完成。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: 常驻技能清单的上限，避免提示词膨胀
MAX_SKILLS = 100
#: 单个 SKILL.md 注入正文的上限（字符）
MAX_SKILL_BODY_CHARS = 20000


@dataclass(frozen=True)
class SkillSummary:
    """一个可用技能的最小描述。"""

    name: str
    description: str
    path: Path


def _parse_frontmatter(text: str) -> dict:
    """解析 YAML frontmatter；失败时返回空字典（不抛异常）。"""
    if not text.startswith('---'):
        return {}
    end = text.find('\n---', 3)
    if end == -1:
        return {}
    try:
        import yaml

        data = yaml.safe_load(text[3:end])
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - frontmatter 损坏不应让启动失败
        return {}


def _candidate_roots(workdir: Path) -> list[Path]:
    """候选 skill 根目录：用户工作目录优先，其次仓库内置。"""
    project_root = Path(__file__).resolve().parents[2]
    roots = [Path(workdir) / 'skills', project_root / 'skills']
    seen: set[Path] = set()
    uniq: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        uniq.append(root)
    return uniq


def discover_skills(workdir: Path | None = None, limit: int = MAX_SKILLS) -> list[SkillSummary]:
    """发现可用技能（name + description）。

    只读取每个 SKILL.md 的前 8KB，且最多返回 ``limit`` 个。
    """
    root_dir = Path(workdir) if workdir else Path.cwd()
    out: list[SkillSummary] = []
    seen_names: set[str] = set()

    for root in _candidate_roots(root_dir):
        if not root.is_dir():
            continue
        for skill_md in sorted(root.glob('*/SKILL.md')):
            if len(out) >= limit:
                return out
            try:
                text = skill_md.read_text(encoding='utf-8', errors='replace')[:8192]
            except OSError:
                continue

            meta = _parse_frontmatter(text)
            name = str(meta.get('name') or skill_md.parent.name).strip()
            description = str(meta.get('description') or '').strip()

            if not description:
                body = text.split('\n---', 1)[-1] if text.startswith('---') else text
                for line in body.splitlines():
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#'):
                        description = stripped
                        break

            if not name or name in seen_names:
                continue
            seen_names.add(name)
            out.append(
                SkillSummary(
                    name=name,
                    description=description[:240],
                    path=skill_md,
                )
            )

    return out


def load_skill_body(skill: SkillSummary, max_chars: int = MAX_SKILL_BODY_CHARS) -> str:
    """读取 skill 正文（超长截断并明确标注）。"""
    text = skill.path.read_text(encoding='utf-8', errors='replace')
    if len(text) > max_chars:
        return text[:max_chars] + '\n\n[内容已截断，请直接读取 SKILL.md 获取完整内容]'
    return text
