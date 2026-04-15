"""
Keyword Registry - 关键词注册表

从 oh-my-codex-main/src/hooks/keyword-registry.ts 转换。
提供技能关键词的注册、查询和模式匹配能力。
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class KeywordPriority(Enum):
    """关键词优先级"""
    LOW = 1
    MEDIUM = 5
    HIGH = 10
    CRITICAL = 20


@dataclass
class KeywordEntry:
    """关键词条目"""
    keyword: str
    skill: str
    priority: int = KeywordPriority.MEDIUM.value
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    requires_context: bool = False


class KeywordRegistry:
    """关键词注册表

    支持:
    - 关键词注册与别名
    - 优先级匹配
    - 模式缓存
    - 动态更新
    """

    def __init__(self):
        self._entries: dict[str, KeywordEntry] = {}
        self._pattern_cache: dict[str, re.Pattern] = {}
        self._initialized = False

    def register(self, entry: KeywordEntry) -> None:
        """注册关键词"""
        self._entries[entry.keyword.lower()] = entry
        # 注册别名
        for alias in entry.aliases:
            self._entries[alias.lower()] = entry
        # 清除模式缓存
        self._pattern_cache.clear()

    def register_batch(self, entries: list[KeywordEntry]) -> None:
        """批量注册"""
        for entry in entries:
            self.register(entry)

    def lookup(self, keyword: str) -> Optional[KeywordEntry]:
        """查找关键词"""
        return self._entries.get(keyword.lower())

    def find_skill(self, text: str) -> Optional[tuple[str, KeywordEntry]]:
        """在文本中查找匹配的技能

        返回: (keyword, entry) 或 None
        """
        text_lower = text.lower()

        # 按优先级排序搜索
        sorted_entries = sorted(
            self._entries.values(),
            key=lambda e: e.priority,
            reverse=True
        )

        for entry in sorted_entries:
            pattern = self._get_pattern(entry.keyword)
            if pattern.search(text_lower):
                return (entry.keyword, entry)

            # 检查别名
            for alias in entry.aliases:
                pattern = self._get_pattern(alias)
                if pattern.search(text_lower):
                    return (alias, entry)

        return None

    def _get_pattern(self, keyword: str) -> re.Pattern:
        """获取或创建关键词模式"""
        if keyword in self._pattern_cache:
            return self._pattern_cache[keyword]

        # 转义并构建词边界模式
        escaped = re.escape(keyword)
        # 如果关键词以字母数字开头，添加词边界
        if keyword and keyword[0].isalnum():
            escaped = r'\b' + escaped
        if keyword and keyword[-1].isalnum():
            escaped = escaped + r'\b'

        pattern = re.compile(escaped, re.IGNORECASE)
        self._pattern_cache[keyword] = pattern
        return pattern

    def get_all_skills(self) -> set[str]:
        """获取所有已注册的技能"""
        # 去重（通过别名注册的只返回主技能）
        skills = set()
        for entry in self._entries.values():
            if entry.keyword not in [e.keyword for e in self._entries.values() if e.aliases]:
                skills.add(entry.skill)
        return skills

    def get_skill_keywords(self, skill: str) -> list[str]:
        """获取技能的所有关键词"""
        keywords = []
        for entry in self._entries.values():
            if entry.skill == skill:
                keywords.append(entry.keyword)
        return keywords


# ===== 默认注册表 =====
DEFAULT_KEYWORD_ENTRIES = [
    KeywordEntry(
        keyword="deepsearch",
        skill="deepsearch",
        priority=KeywordPriority.HIGH.value,
        description="Deep web search for research tasks"
    ),
    KeywordEntry(
        keyword="deep interview",
        skill="deep-interview",
        priority=KeywordPriority.HIGH.value,
        description="Deep conversation to clarify requirements"
    ),
    KeywordEntry(
        keyword="analyze",
        skill="analyze",
        priority=KeywordPriority.MEDIUM.value,
        description="Analyze codebase or requirements"
    ),
    KeywordEntry(
        keyword="plan",
        skill="plan",
        priority=KeywordPriority.MEDIUM.value,
        description="Create implementation plan"
    ),
    KeywordEntry(
        keyword="build",
        skill="build-fix",
        priority=KeywordPriority.MEDIUM.value,
        description="Build or fix code"
    ),
    KeywordEntry(
        keyword="fix",
        skill="build-fix",
        priority=KeywordPriority.MEDIUM.value,
        description="Fix bugs or issues"
    ),
    KeywordEntry(
        keyword="review",
        skill="code-review",
        priority=KeywordPriority.MEDIUM.value,
        description="Code review"
    ),
    KeywordEntry(
        keyword="security",
        skill="security-review",
        priority=KeywordPriority.HIGH.value,
        description="Security review"
    ),
    KeywordEntry(
        keyword="test",
        skill="tdd",
        priority=KeywordPriority.MEDIUM.value,
        description="Test-driven development"
    ),
    KeywordEntry(
        keyword="team",
        skill="team",
        priority=KeywordPriority.CRITICAL.value,
        aliases=["swarm", "multi-agent"],
        description="Multi-agent team execution"
    ),
    KeywordEntry(
        keyword="ralph",
        skill="ralph",
        priority=KeywordPriority.CRITICAL.value,
        description="Persistent verification loop"
    ),
    KeywordEntry(
        keyword="ralplan",
        skill="ralplan",
        priority=KeywordPriority.HIGH.value,
        description="Planning phase for ralph"
    ),
    KeywordEntry(
        keyword="doctor",
        skill="doctor",
        priority=KeywordPriority.LOW.value,
        description="Environment diagnostics"
    ),
    KeywordEntry(
        keyword="help",
        skill="help",
        priority=KeywordPriority.LOW.value,
        description="Show help information"
    ),
    KeywordEntry(
        keyword="cancel",
        skill="cancel",
        priority=KeywordPriority.CRITICAL.value,
        description="Cancel ongoing operation"
    ),
    KeywordEntry(
        keyword="autopilot",
        skill="autopilot",
        priority=KeywordPriority.CRITICAL.value,
        description="Autonomous execution mode"
    ),
    KeywordEntry(
        keyword="ultrawork",
        skill="ultrawork",
        priority=KeywordPriority.CRITICAL.value,
        description="Heavy workload mode"
    ),
    KeywordEntry(
        keyword="visual",
        skill="visual-verdict",
        priority=KeywordPriority.MEDIUM.value,
        description="Visual verification"
    ),
    KeywordEntry(
        keyword="web clone",
        skill="web-clone",
        priority=KeywordPriority.MEDIUM.value,
        description="Clone website"
    ),
    # 从 oh-my-codex-main 汲取的额外关键词
    KeywordEntry(
        keyword="autoresearch",
        skill="autoresearch",
        priority=KeywordPriority.CRITICAL.value,
        description="Autonomous research mode"
    ),
    KeywordEntry(
        keyword="deep interview",
        skill="deep-interview",
        priority=KeywordPriority.HIGH.value,
        description="Deep conversation to clarify requirements"
    ),
    KeywordEntry(
        keyword="skill",
        skill="skill",
        priority=KeywordPriority.MEDIUM.value,
        description="Create or manage skills"
    ),
    KeywordEntry(
        keyword="worker",
        skill="worker",
        priority=KeywordPriority.MEDIUM.value,
        description="Background worker agent"
    ),
    KeywordEntry(
        keyword="ultraqa",
        skill="ultraqa",
        priority=KeywordPriority.CRITICAL.value,
        description="Ultra quality assurance"
    ),
    KeywordEntry(
        keyword="web-clone",
        skill="web-clone",
        priority=KeywordPriority.MEDIUM.value,
        description="Clone website content"
    ),
    KeywordEntry(
        keyword="note",
        skill="note",
        priority=KeywordPriority.LOW.value,
        description="Take notes"
    ),
    KeywordEntry(
        keyword="trace",
        skill="trace",
        priority=KeywordPriority.MEDIUM.value,
        description="Trace execution flow"
    ),
    KeywordEntry(
        keyword="configure-notifications",
        skill="configure-notifications",
        priority=KeywordPriority.LOW.value,
        description="Configure notifications"
    ),
    KeywordEntry(
        keyword="ai-slop",
        skill="ai-slop-cleaner",
        priority=KeywordPriority.MEDIUM.value,
        description="Clean AI-generated code"
    ),
    KeywordEntry(
        keyword="swarm",
        skill="team",
        priority=KeywordPriority.CRITICAL.value,
        description="Multi-agent swarm mode"
    ),
    KeywordEntry(
        keyword="hud",
        skill="hud",
        priority=KeywordPriority.LOW.value,
        description="Heads-up display"
    ),
    KeywordEntry(
        keyword="git-master",
        skill="git-master",
        priority=KeywordPriority.MEDIUM.value,
        description="Git operations"
    ),
]


def create_default_registry() -> KeywordRegistry:
    """创建默认注册表"""
    registry = KeywordRegistry()
    registry.register_batch(DEFAULT_KEYWORD_ENTRIES)
    return registry


# 全局默认注册表
default_registry = create_default_registry()


# ===== 导出 =====
__all__ = [
    "KeywordPriority",
    "KeywordEntry",
    "KeywordRegistry",
    "DEFAULT_KEYWORD_ENTRIES",
    "create_default_registry",
    "default_registry",
]
