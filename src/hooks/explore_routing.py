"""
Explore Routing - 探索路由

从 oh-my-codex-main/src/hooks/explore-routing.ts 转换而来。
提供代码探索路由功能。
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ExploreRoute:
    """探索路由"""
    target: str
    route_type: str  # 'file' | 'symbol' | 'pattern' | 'directory'
    confidence: float


# 路由模式
ROUTE_PATTERNS = {
    "file": [
        r"find\s+(?:the\s+)?file\s+(\S+)",
        r"where\s+is\s+(\S+)",
        r"locate\s+(\S+)",
        r"which\s+file\s+contains\s+(\S+)",
    ],
    "symbol": [
        r"(?:find|search|lookup)\s+(?:the\s+)?symbol\s+(\S+)",
        r"where\s+(?:is|defined)\s+(\S+)",
        r"definition\s+of\s+(\S+)",
    ],
    "pattern": [
        r"search\s+(?:for\s+)?(?:the\s+)?pattern\s+(\S+)",
        r"find\s+(?:all\s+)?(?:occurrences?\s+of\s+)?(\S+)",
    ],
    "directory": [
        r"explore\s+(?:the\s+)?directory\s+(\S+)",
        r"list\s+(?:the\s+)?(\S+)\s+directory",
    ],
}


def parse_explore_route(query: str) -> Optional[ExploreRoute]:
    """解析探索路由查询"""
    import re

    query_lower = query.lower()

    # 文件路由
    for pattern in ROUTE_PATTERNS["file"]:
        match = re.search(pattern, query_lower)
        if match:
            return ExploreRoute(
                target=match.group(1),
                route_type="file",
                confidence=0.9,
            )

    # 符号路由
    for pattern in ROUTE_PATTERNS["symbol"]:
        match = re.search(pattern, query_lower)
        if match:
            return ExploreRoute(
                target=match.group(1),
                route_type="symbol",
                confidence=0.85,
            )

    # 模式路由
    for pattern in ROUTE_PATTERNS["pattern"]:
        match = re.search(pattern, query_lower)
        if match:
            return ExploreRoute(
                target=match.group(1),
                route_type="pattern",
                confidence=0.8,
            )

    # 目录路由
    for pattern in ROUTE_PATTERNS["directory"]:
        match = re.search(pattern, query_lower)
        if match:
            return ExploreRoute(
                target=match.group(1),
                route_type="directory",
                confidence=0.75,
            )

    return None


def suggest_routing_strategy(query: str) -> str:
    """建议路由策略"""
    route = parse_explore_route(query)
    if not route:
        return "default"

    route_strategies = {
        "file": "file_search",
        "symbol": "symbol_search",
        "pattern": "grep_search",
        "directory": "directory_explore",
    }
    return route_strategies.get(route.route_type, "default")


# ===== 导出 =====
__all__ = [
    "ExploreRoute",
    "parse_explore_route",
    "suggest_routing_strategy",
]
