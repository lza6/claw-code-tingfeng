"""DocNeedsDetector — 文档需求检测器"""
from __future__ import annotations

import ast

from .base import CodeContext, SemanticFeature


class DocNeedsDetector:
    """文档需求检测器

    分析代码中函数和类是否缺失 Docstrings，超过阈值则触发文档专家 Agent。
    """

    @property
    def tag(self) -> str:
        return "#Doc-Needed"

    def detect(self, context: CodeContext) -> SemanticFeature | None:
        """检测文档缺失特征"""
        if not context.source_code:
            return None

        total_items = 0
        missing_docs = 0
        evidence = []

        try:
            tree = ast.parse(context.source_code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    total_items += 1
                    if not ast.get_docstring(node):
                        missing_docs += 1
                        evidence.append(f"{type(node).__name__}: {node.name} (missing docstring)")
        except Exception:
            # 降级: 简单行检查
            pass

        if total_items > 0:
            missing_ratio = missing_docs / total_items
            if missing_ratio > 0.3:  # 超过 30% 缺失则触发
                return SemanticFeature(
                    tag=self.tag,
                    confidence=min(1.0, missing_ratio + 0.2),
                    evidence=evidence[:5],
                    severity="low"
                )

        return None
