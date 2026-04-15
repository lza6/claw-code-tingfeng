"""Language Ecosystem Engine — 多语言生态感知引擎 (Ported from Codex-OMX)

基于项目 B 的 Registry 逻辑，提供跨语言的工具链识别与诊断能力。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class LangProfile:
    name: str
    pattern: str
    executables: List[str]
    description: str

class LangEngine:
    REGISTRY: Dict[str, LangProfile] = {
        "python": LangProfile(
            name="python",
            pattern=r"python|pip|uv|poetry|pytest",
            executables=["python", "pip", "uv", "poetry", "pytest"],
            description="Python 生态工具链"
        ),
        "rust": LangProfile(
            name="rust",
            pattern=r"cargo|rustc|rustup",
            executables=["cargo", "rustc", "rustup"],
            description="Rust 系统级工具链"
        ),
        "go": LangProfile(
            name="go",
            pattern=r"go\s+(run|build|test|mod)",
            executables=["go"],
            description="Go 语言工具链"
        ),
        "node": LangProfile(
            name="node",
            pattern=r"node|npm|yarn|pnpm|bun",
            executables=["node", "npm", "yarn", "pnpm", "bun"],
            description="JavaScript/TypeScript 运行时"
        )
    }

    @classmethod
    def detect_lang(cls, command: str) -> str | None:
        import re
        for lang, profile in cls.REGISTRY.items():
            if re.search(profile.pattern, command, re.IGNORECASE):
                return lang
        return None
