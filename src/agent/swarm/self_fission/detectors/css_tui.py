"""CSSTUIDetector — CSS/TUI 界面检测

检测代码中的 UI/CSS/TUI 相关逻辑，如 Textual 组件、样式定义等。
触发标签: #Aesthetic-UX
"""
from __future__ import annotations

from .base import CodeContext, FeatureDetector, SemanticFeature

# UI/TUI 相关库
UI_IMPORTS: set[str] = {
    'textual', 'rich', 'tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    'wx', 'kivy', 'customtkinter', 'ttkbootstrap',
    'css', 'style', 'tailwind', 'bootstrap', 'material',
}

# UI 相关关键词
UI_KEYWORDS: set[str] = {
    'widget', 'component', 'button', 'label', 'input', 'dialog',
    'modal', 'popup', 'menu', 'toolbar', 'statusbar',
    'color', 'background', 'foreground', 'border', 'padding', 'margin',
    'font', 'size', 'style', 'theme', 'layout', 'grid', 'flex',
    'render', 'draw', 'paint', 'display', 'show', 'hide',
    'click', 'hover', 'focus', 'blur', 'scroll',
    'animate', 'transition', 'animation', 'fade', 'slide',
}

# 颜色/样式模式
COLOR_PATTERNS = [
    'color:', 'background:', 'border:', 'padding:', 'margin:',
    'font-size:', 'font-weight:', 'text-align:', 'display:',
    '#', 'rgb(', 'rgba(', 'hsl(',
]


class CSSTUIDetector(FeatureDetector):
    """CSS/TUI 界面检测器

    检测代码中的 UI 组件和样式逻辑。
    """

    @property
    def tag(self) -> str:
        return "#Aesthetic-UX"

    def detect(self, context: CodeContext) -> SemanticFeature | None:
        """检测 UI/CSS 相关特征

        评分规则:
        - 导入 UI 库: +0.3 per import (max 0.6)
        - UI 关键词: +0.05 per keyword (max 0.3)
        - 颜色/样式模式: +0.05 per pattern (max 0.2)
        """
        score = 0.0
        evidence: list[str] = []

        source_lower = context.source_code.lower()
        source_lines = context.source_code.split('\n')

        # 检查导入
        for imp in context.imports:
            for ui_imp in UI_IMPORTS:
                if ui_imp in imp or imp in ui_imp:
                    score += 0.3
                    evidence.append(f"import: {imp}")
                    break

        import_score = min(0.6, score)
        score = import_score

        # 检查 UI 关键词
        ui_keywords_found: set[str] = set()
        for keyword in UI_KEYWORDS:
            if keyword.lower() in source_lower:
                ui_keywords_found.add(keyword)

        keyword_score = min(0.3, len(ui_keywords_found) * 0.05)
        score += keyword_score

        for kw in list(ui_keywords_found)[:5]:
            for i, line in enumerate(source_lines, 1):
                if kw.lower() in line.lower():
                    evidence.append(f"UI line {i}: {line.strip()[:80]}")
                    break

        # 检查颜色/样式模式
        style_count = 0
        for pattern in COLOR_PATTERNS:
            if pattern.lower() in source_lower:
                style_count += 1

        style_score = min(0.2, style_count * 0.05)
        score += style_score

        confidence = min(1.0, score)

        if confidence >= 0.3:
            return SemanticFeature(
                tag=self.tag,
                confidence=confidence,
                evidence=evidence[:10],
                severity="low",
            )

        return None
