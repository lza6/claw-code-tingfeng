"""FeatureDetector — 特征检测器协议

定义所有特征检测器必须遵循的接口 Protocol。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class CodeContext:
    """代码上下文 — 提供给检测器的分析数据"""
    source_code: str = ""                           # 源代码文本
    file_path: str = ""                             # 文件相对路径
    language: str = "python"                        # 编程语言
    imports: list[str] = field(default_factory=list)  # 导入模块列表
    functions: list[str] = field(default_factory=list)  # 函数名列表
    classes: list[str] = field(default_factory=list)    # 类名列表
    keywords: list[str] = field(default_factory=list)   # 关键词（变量名、方法调用等）


@dataclass
class SemanticFeature:
    """语义特征 — 检测器识别的代码特征"""
    tag: str                    # 标签名，如 "#Crypto", "#Security", "#Performance"
    confidence: float           # 置信度 0.0 ~ 1.0
    evidence: list[str] = field(default_factory=list)  # 证据（触发特征的代码片段/模块路径）
    severity: str = "medium"    # 严重程度: low, medium, high, critical

    def __post_init__(self):
        """验证字段范围"""
        self.confidence = max(0.0, min(1.0, self.confidence))
        if self.severity not in ("low", "medium", "high", "critical"):
            self.severity = "medium"


class FeatureDetector(Protocol):
    """特征检测器协议

    所有检测器必须实现此 Protocol，以便被 SemanticCodeAnalyzer 统一调用。

    用法:
        class MyDetector:
            @property
            def tag(self) -> str:
                return "#MyTag"

            def detect(self, context: CodeContext) -> SemanticFeature | None:
                # 分析代码，返回特征或 None
                ...
    """

    @property
    def tag(self) -> str:
        """返回此检测器负责的标签名

        例如: "#Crypto", "#Security", "#Performance"
        """
        ...

    def detect(self, context: CodeContext) -> SemanticFeature | None:
        """检测代码中的特征

        参数:
            context: 代码上下文（文件内容、AST 解析结果等）

        返回:
            如果检测到特征，返回 SemanticFeature；否则返回 None
        """
        ...
