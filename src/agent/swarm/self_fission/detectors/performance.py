"""PerformanceDetector — 性能瓶颈检测

检测代码中潜在的性能问题，如嵌套循环、大数据集处理等。
触发标签: #Performance
"""
from __future__ import annotations

import re

from .base import CodeContext, FeatureDetector, SemanticFeature

# 性能相关关键词
PERF_KEYWORDS: set[str] = {
    'for', 'while', 'loop', 'iterate',
    'list', 'dict', 'set', 'array', 'DataFrame',
    'sort', 'sorted', 'reverse', 'search', 'find',
    'cache', 'lru_cache', 'memoize', 'memoization',
    'async', 'await', 'concurrent', 'thread', 'process', 'pool',
    'generator', 'yield', 'iterator',
    'batch', 'chunk', 'stream', 'buffer',
    'optimize', 'performance', 'slow', 'bottleneck',
}

# 嵌套循环模式
NESTED_LOOP_PATTERN = re.compile(r'for\s+\w+\s+in\s+.+:\n(\s+)*for\s+')

# 大数据处理模式
BIG_DATA_PATTERNS = [
    re.compile(r'(read_csv|read_excel|load_data|fetch_all)\s*\('),
    re.compile(r'(pd\.|pandas\.|DataFrame|np\.|numpy\.)'),
    re.compile(r'(range\s*\(\s*\d{5,})'),  # range(10000+)
]


class PerformanceDetector(FeatureDetector):
    """性能瓶颈检测器

    检测代码中潜在的性能问题。
    """

    @property
    def tag(self) -> str:
        return "#Performance"

    def detect(self, context: CodeContext) -> SemanticFeature | None:
        """检测性能相关特征

        评分规则:
        - 嵌套循环: +0.4
        - 大数据处理模式: +0.2 per pattern (max 0.4)
        - 性能关键词: +0.05 per keyword (max 0.3)
        """
        score = 0.0
        evidence: list[str] = []

        source_lines = context.source_code.split('\n')
        source_lower = context.source_code.lower()

        # 检查嵌套循环
        if NESTED_LOOP_PATTERN.search(context.source_code):
            score += 0.4
            evidence.append("NESTED_LOOP: 检测到嵌套循环")

        # 检查大数据处理模式
        big_data_count = 0
        for pattern in BIG_DATA_PATTERNS:
            if pattern.search(context.source_code):
                big_data_count += 1
                for i, line in enumerate(source_lines, 1):
                    if pattern.search(line):
                        evidence.append(f"DATA line {i}: {line.strip()[:80]}")
                        break

        score += min(0.4, big_data_count * 0.2)

        # 检查性能关键词
        perf_keywords_found = set()
        for keyword in PERF_KEYWORDS:
            if keyword.lower() in source_lower:
                perf_keywords_found.add(keyword)

        keyword_score = min(0.3, len(perf_keywords_found) * 0.05)
        score += keyword_score

        confidence = min(1.0, score)

        # 确定严重程度
        severity = "low"
        if score > 0.6:
            severity = "high"
        elif score > 0.3:
            severity = "medium"

        if confidence >= 0.3:
            return SemanticFeature(
                tag=self.tag,
                confidence=confidence,
                evidence=evidence[:10],
                severity=severity,
            )

        return None
