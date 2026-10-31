#!/usr/bin/env python
"""从 CHANGELOG.md 抽取某个版本的发布说明（供 `gh release create --notes-file` 使用）。

为什么需要独立脚本：发布流水线里「取不到说明」这件事有两个相反的失败模式，
两边都很糟：
  ① 静默产出空说明 → GitHub Release 变成空标题的空壳（看起来成功，实则信息缺失）；
  ② 直接报错但流水线继续 → 发出去的包没人知道改了什么。
所以本脚本对「版本不存在」显式 exit 2，并把可选项（标题/正文）分别返回，
让调用方自己决定是否降级。

用法：
    python scripts/changelog_notes.py --version 0.90.0
    python scripts/changelog_notes.py --version 0.90.0 --json
    python scripts/changelog_notes.py --version 0.90.0 --out release-notes.md

退出码：0 找到并输出 · 2 CHANGELOG 不存在或该版本不存在 · 3 该版本章节为空
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_CHANGELOG = Path("CHANGELOG.md")

# 匹配 `## [v0.89.1] (2026-10-31) — 标题` / `## [0.89.1]` / `## [Unreleased]`
_HEADING_RE = re.compile(r"^##\s+\[(?P<ver>[^\]]+)\](?P<rest>.*)$")


def normalize_version(text: str) -> str:
    """把 `v0.89.1` / `0.89.1` / `refs/tags/v0.89.1` 归一成 `0.89.1`（不猜其他形式）"""
    v = text.strip()
    if v.startswith("refs/tags/"):
        v = v[len("refs/tags/"):]
    if v[:1] in ("v", "V"):
        v = v[1:]
    return v


def _iter_sections(lines: list[str]) -> list[tuple[str, str, list[str]]]:
    """返回 [(原始版本串, 标题后缀, 正文行)]，按出现顺序"""
    sections: list[tuple[str, str, list[str]]] = []
    current: tuple[str, str, list[str]] | None = None
    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            if current is not None:
                sections.append(current)
            current = (m.group("ver"), m.group("rest").strip(), [])
            continue
        if current is not None:
            current[2].append(line)
    if current is not None:
        sections.append(current)
    return sections


def extract_notes(version: str, changelog: Path = DEFAULT_CHANGELOG) -> dict:
    """抽取版本说明。

    返回 ``{ok, version, title, notes, reason}``：
    ``ok=False`` 时 ``reason`` 说明原因，``notes`` 为空串——调用方必须检查 ``ok``。
    """
    version = normalize_version(version)
    result: dict = {"ok": False, "version": version, "title": "", "notes": "", "reason": ""}

    if not changelog.exists():
        result["reason"] = f"CHANGELOG 不存在: {changelog}"
        return result

    text = changelog.read_text(encoding="utf-8")
    sections = _iter_sections(text.splitlines())

    for raw_ver, rest, body in sections:
        if normalize_version(raw_ver) != version:
            continue
        # 去掉正文首尾空行与结尾的水平分隔线
        lines = [ln.rstrip("\n") for ln in body]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        while lines and set(lines[-1].strip()) <= {"-", "*", "_"}:
            lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()
        notes = "\n".join(lines)
        result["ok"] = True
        # 标题后缀常见形态：` (2026-11-01) — 示例标题` / ` — 示例标题` / 空
        title = re.sub(r"^\([^)]*\)\s*", "", rest).strip()
        title = title.lstrip("—–-:：").strip()
        result["title"] = title or f"v{version}"
        result["notes"] = notes
        if not notes.strip():
            result["ok"] = False
            result["reason"] = f"v{version} 的章节为空（只有标题没有内容）"
        return result

    known = ", ".join(normalize_version(s[0]) for s in sections[:8])
    result["reason"] = f"CHANGELOG 里没有 v{version} 的章节（已识别: {known or '无'}）"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 CHANGELOG.md 抽取版本发布说明")
    parser.add_argument("--version", "-v", required=True, help="版本号，接受 0.90.0 / v0.90.0")
    parser.add_argument("--file", "-f", default=str(DEFAULT_CHANGELOG), help="CHANGELOG 路径")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument("--out", "-o", default=None, help="把说明写到文件（标题 + 正文）")
    args = parser.parse_args(argv)

    info = extract_notes(args.version, Path(args.file))

    if args.out:
        if info["ok"]:
            payload = f"# v{info['version']} — {info['title']}\n\n{info['notes']}\n"
            Path(args.out).write_text(payload, encoding="utf-8")
        elif info["reason"]:
            print(f"[changelog_notes] {info['reason']}", file=sys.stderr)

    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info["ok"] else (3 if "为空" in info["reason"] else 2)

    if not info["ok"]:
        print(f"[changelog_notes] {info['reason']}", file=sys.stderr)
        return 3 if "为空" in info["reason"] else 2

    print(f"# v{info['version']} — {info['title']}")
    print()
    print(info["notes"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
