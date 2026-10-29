"""角色库 —— 可选的系统提示词模板，让用户不用自己写提示词

设计取舍（为什么这样做）：

- **文件即角色**：一个角色 = `personas/<name>.md`，YAML frontmatter 放元信息，
  正文就是系统提示词。不用数据库、不用二次解析，用户随时能加/改/删。
- **三级搜索路径**：项目 `personas/` → 工作目录 `personas/` → `~/.clawd/personas/`，
  同名时**后者覆盖前者**（方便团队统一底库 + 个人覆盖）。
- **不做隐式注入**：只有显式选中的角色才会进系统提示词；不选就完全走默认行为。
- **可审计**：`clawd role show <name>` 直接把最终系统提示词打印出来，
  会话里也会记录用了哪个角色（`metadata.persona`），避免"它为什么这么说话"说不清。

关于"越狱/绕过安全审查"类角色：本仓库**不内置**这类提示词内容。
机制是通用的（用户可以在自己的 `personas/` 目录放任意模板），但内置库只放
工程与写作类角色，避免把"绕过安全边界"当成产品默认能力。
"""
from __future__ import annotations

import logging

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 单个角色系统提示词的长度上限（超过说明该拆成技能/references 而不是塞进提示词）
MAX_PERSONA_CHARS = 12_000
#: 角色标识只允许这些字符（同时用于文件名与 URL/CLI 参数）
ALLOWED_NAME = set("abcdefghijklmnopqrstuvwxyz0123456789-_")


@dataclass(frozen=True)
class Persona:
    """一个角色（系统提示词模板）"""

    name: str
    title: str
    description: str = ""
    category: str = "通用"
    system: str = ""
    source: Path | None = None

    def to_dict(self, *, include_system: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "chars": len(self.system),
        }
        if include_system:
            data["system"] = self.system
        if self.source is not None:
            data["source"] = str(self.source)
        return data


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """拆出 YAML frontmatter 与正文；没有 frontmatter 时元信息为空"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4 :]
    try:
        import yaml

        meta = yaml.safe_load(raw) or {}
        if not isinstance(meta, dict):
            return {}, body
        return meta, body
    except Exception as e:  # noqa: BLE001 — frontmatter 坏了不该让整个库崩
        logger.warning(f"角色 frontmatter 解析失败（已跳过元信息）: {e}")
        return {}, body


def _is_valid_name(name: str) -> bool:
    return bool(name) and all(ch in ALLOWED_NAME for ch in name)


def search_dirs(workdir: Path | str | None = None) -> list[Path]:
    """角色搜索路径（按优先级从低到高，后者覆盖前者）"""
    dirs: list[Path] = []
    repo_root = Path(__file__).resolve().parents[2]
    dirs.append(repo_root / "personas")
    base = Path(workdir) if workdir else Path.cwd()
    dirs.append(base / "personas")
    dirs.append(Path.home() / ".clawd" / "personas")

    seen: set[Path] = set()
    uniq: list[Path] = []
    for d in dirs:
        try:
            resolved = d.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        uniq.append(d)
    return uniq


def parse_persona_file(path: Path) -> Persona | None:
    """解析单个角色文件；非法/空正文返回 None（并记录原因）"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(f"角色文件读取失败 {path}: {e}")
        return None

    meta, body = _parse_frontmatter(text)
    name = str(meta.get("name") or path.stem).strip()
    if not _is_valid_name(name):
        logger.warning(f"角色名非法（只用字母/数字/-/_）: {name!r} @ {path}")
        return None

    system = body.strip()
    if not system:
        logger.warning(f"角色正文为空（正文即系统提示词）: {path}")
        return None
    if len(system) > MAX_PERSONA_CHARS:
        logger.warning(
            f"角色 {name} 系统提示词 {len(system)} 字符超过上限 {MAX_PERSONA_CHARS}，已截断"
        )
        system = system[:MAX_PERSONA_CHARS]

    return Persona(
        name=name,
        title=str(meta.get("title") or meta.get("display_name") or name).strip(),
        description=str(meta.get("description") or "").strip(),
        category=str(meta.get("category") or "通用").strip(),
        system=system,
        source=path,
    )


def discover_personas(workdir: Path | str | None = None) -> list[Persona]:
    """发现全部角色（高优先级目录覆盖同名低优先级）"""
    found: dict[str, Persona] = {}
    for directory in search_dirs(workdir):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            persona = parse_persona_file(path)
            if persona is not None:
                found[persona.name] = persona  # 后出现的覆盖先出现的
    return sorted(found.values(), key=lambda p: (p.category, p.name))


def load_persona(name: str, workdir: Path | str | None = None) -> Persona:
    """按名字取角色

    Raises:
        KeyError: 角色不存在（消息里附可用角色，便于排错）
    """
    key = (name or "").strip()
    for persona in discover_personas(workdir):
        if persona.name == key:
            return persona
    available = ", ".join(p.name for p in discover_personas(workdir)) or "(空)"
    raise KeyError(f"角色不存在: {key!r}；可用: {available}")


def build_system_prefix(persona: Persona) -> str:
    """把角色转成注入系统提示词的文本块"""
    header = f"## 你当前的角色：{persona.title}（{persona.name}）"
    if persona.description:
        header += f"\n（角色说明：{persona.description}）"
    return f"{header}\n\n{persona.system.strip()}"


def personas_report(workdir: Path | str | None = None) -> list[dict[str, Any]]:
    """给 CLI/WS 用的清单（不含系统提示词正文）"""
    return [p.to_dict() for p in discover_personas(workdir)]


__all__ = [
    "ALLOWED_NAME",
    "MAX_PERSONA_CHARS",
    "Persona",
    "build_system_prefix",
    "discover_personas",
    "load_persona",
    "parse_persona_file",
    "personas_report",
    "search_dirs",
]
