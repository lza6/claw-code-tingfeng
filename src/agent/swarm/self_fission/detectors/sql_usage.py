"""SQLUsageDetector — SQL 使用检测器"""
from __future__ import annotations

import re

from .base import CodeContext, SemanticFeature


class SQLUsageDetector:
    """SQL 使用检测器

    识别代码中的 SQL 语句、数据库驱动导入等，触发 SQL 优化专家 Agent。
    """

    @property
    def tag(self) -> str:
        return "#SQL-Heavy"

    def detect(self, context: CodeContext) -> SemanticFeature | None:
        """检测 SQL 使用特征"""
        confidence = 0.0
        evidence = []

        # 1. 检查导入
        db_libraries = {'sqlite3', 'psycopg2', 'sqlalchemy', 'mysql', 'pymongo', 'redis'}
        for imp in context.imports:
            if any(libs in imp for libs in db_libraries):
                confidence += 0.4
                evidence.append(f"DB Import: {imp}")

        # 2. 检查 SQL 关键词
        sql_keywords = [
            r'\bSELECT\b.*\bFROM\b',
            r'\bINSERT\b.*\bINTO\b',
            r'\bUPDATE\b.*\bSET\b',
            r'\bDELETE\b.*\bFROM\b',
            r'\bCREATE\b.*\bTABLE\b',
            r'\bJOIN\b.*\bON\b'
        ]

        source_upper = context.source_code.upper()
        for pattern in sql_keywords:
            if re.search(pattern, source_upper):
                confidence += 0.3
                evidence.append(f"SQL Pattern matched: {pattern}")

        if confidence > 0:
            return SemanticFeature(
                tag=self.tag,
                confidence=min(1.0, confidence),
                evidence=list(set(evidence))[:5],
                severity="medium"
            )

        return None
