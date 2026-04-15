"""SemanticCodeAnalyzer — 语义代码分析器

扫描目标代码（文件或代码字符串），通过特征检测器集合识别语义特征。

用法:
    analyzer = SemanticCodeAnalyzer()

    # 分析代码字符串
    features = await analyzer.analyze_code_string(code)

    # 分析文件
    features = await analyzer.analyze_file("src/auth/jwt.py")

    # 分析工作目录中的多个相关文件
    features = await analyzer.analyze(goal, workdir)
"""
from __future__ import annotations

import ast
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .detectors.base import CodeContext, FeatureDetector, SemanticFeature
from .detectors.crypto import CryptoDetector
from .detectors.css_tui import CSSTUIDetector
from .detectors.doc_needs import DocNeedsDetector
from .detectors.performance import PerformanceDetector
from .detectors.security import SecurityDetector
from .detectors.sql_usage import SQLUsageDetector

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """分析结果汇总"""
    features: list[SemanticFeature] = field(default_factory=list)
    files_analyzed: list[str] = field(default_factory=list)
    total_lines: int = 0

    @property
    def tags(self) -> list[str]:
        """返回所有检测到的标签"""
        return [f.tag for f in self.features]

    @property
    def highest_severity(self) -> str:
        """返回最高严重程度"""
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        max_sev = "low"
        for f in self.features:
            if severity_order.get(f.severity, 0) > severity_order.get(max_sev, 0):
                max_sev = f.severity
        return max_sev


class SemanticCodeAnalyzer:
    """语义代码分析器

    通过运行一组特征检测器，分析代码的语义特征。

    用法:
        analyzer = SemanticCodeAnalyzer(threshold=0.5)
        features = analyzer.analyze_code_string("import hashlib; ...")
    """

    def __init__(
        self,
        threshold: float = 0.5,
        detectors: Sequence[FeatureDetector] | None = None,
    ) -> None:
        """初始化分析器

        参数:
            threshold: 置信度阈值 (0.0 ~ 1.0)，低于此值的特征将被过滤
            detectors: 自定义检测器列表（为 None 时使用默认检测器）
        """
        self.threshold = threshold
        self.detectors = detectors or self._default_detectors()

    def _default_detectors(self) -> list[FeatureDetector]:
        """创建默认检测器集合"""
        return [
            CryptoDetector(),
            SecurityDetector(),
            PerformanceDetector(),
            CSSTUIDetector(),
            DocNeedsDetector(),
            SQLUsageDetector(),
        ]

    def _parse_code(self, source: str) -> dict:
        """解析代码，提取上下文信息

        返回:
            包含 imports, functions, classes, keywords 的字典
        """
        imports: list[str] = []
        functions: list[str] = []
        classes: list[str] = []
        keywords: list[str] = []

        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(node.name)
                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
                elif isinstance(node, ast.Name):
                    keywords.append(node.id)
                elif isinstance(node, ast.Attribute):
                    # 提取属性访问链，如 hashlib.sha256
                    parts = []
                    current = node
                    while isinstance(current, ast.Attribute):
                        parts.append(current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        parts.append(current.id)
                    if parts:
                        keywords.append('.'.join(reversed(parts)))
        except SyntaxError:
            logger.debug("AST 解析失败，使用基本提取")
            # 降级: 基本字符串提取
            for line in source.split('\n'):
                line = line.strip()
                if line.startswith('import ') or line.startswith('from '):
                    parts = line.replace('import ', '').replace('from ', '').split()
                    if parts:
                        imports.append(parts[0])

        return {
            'imports': list(set(imports)),
            'functions': functions,
            'classes': classes,
            'keywords': list(set(keywords)),
        }

    def analyze_code_string(self, source: str, file_path: str = "") -> AnalysisResult:
        """分析代码字符串

        参数:
            source: 源代码字符串
            file_path: 可选的文件路径（用于证据追踪）

        返回:
            AnalysisResult 对象
        """
        if not source.strip():
            return AnalysisResult()

        # 解析代码
        parsed = self._parse_code(source)

        # 构建上下文
        context = CodeContext(
            source_code=source,
            file_path=file_path,
            language='python',
            imports=parsed['imports'],
            functions=parsed['functions'],
            classes=parsed['classes'],
            keywords=parsed['keywords'],
        )

        # 运行检测器
        features = self._run_detectors(context)

        return AnalysisResult(
            features=features,
            files_analyzed=[file_path] if file_path else [],
            total_lines=len(source.split('\n')),
        )

    async def analyze_file(self, file_path: str | Path) -> AnalysisResult:
        """分析单个文件

        参数:
            file_path: 文件路径

        返回:
            AnalysisResult 对象
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"文件不存在: {file_path}")
            return AnalysisResult()

        try:
            source = path.read_text(encoding='utf-8', errors='replace')
            return self.analyze_code_string(source, file_path=str(path))
        except Exception as e:
            logger.error(f"分析文件失败 {file_path}: {e}")
            return AnalysisResult()

    async def analyze(
        self,
        goal: str,
        workdir: Path,
        file_patterns: list[str] | None = None,
    ) -> AnalysisResult:
        """分析工作目录中的代码

        参数:
            goal: 任务目标（用于识别相关文件）
            workdir: 工作目录
            file_patterns: 文件匹配模式（如 ['**/*.py']），为 None 时自动推断

        返回:
            AnalysisResult 对象
        """
        # 确定要分析的文件
        if file_patterns is None:
            file_patterns = ['**/*.py']

        all_features: list[SemanticFeature] = []
        files_analyzed: list[str] = []
        total_lines = 0

        for pattern in file_patterns:
            for fpath in workdir.glob(pattern):
                # 跳过虚拟环境和缓存目录
                if any(p in ('.venv', 'venv', '__pycache__', '.git', 'node_modules') for p in fpath.parts):
                    continue

                result = await self.analyze_file(fpath)
                if result.features:
                    all_features.extend(result.features)
                    files_analyzed.extend(result.files_analyzed)
                    total_lines += result.total_lines

        # [NEW Phase 4] 集成经验感知：检查目标任务是否触碰历史失败模式
        try:
            from .rl_experience import RLExperienceHub
            hub = RLExperienceHub()
            warnings = hub.get_failure_warnings(goal)
            if warnings:
                # 针对高频失败，自动合成安全加固/一致性特征
                all_features.append(SemanticFeature(
                    tag="#Consistency",
                    confidence=0.8,
                    evidence=[f"History Warning: {w.pattern}" for w in warnings],
                    severity="high"
                ))
                logger.info("检测到历史雷区，已自动注入协作一致性特征标签")
        except Exception as e:
            logger.debug(f"经验感知检测跳过: {e}")

        # 去重合并特征
        merged_features = self._merge_features(all_features)

        return AnalysisResult(
            features=merged_features,
            files_analyzed=files_analyzed,
            total_lines=total_lines,
        )

    def _run_detectors(self, context: CodeContext) -> list[SemanticFeature]:
        """运行所有检测器

        参数:
            context: 代码上下文

        返回:
            检测到的特征列表（已过滤低于阈值的）
        """
        features = []
        for detector in self.detectors:
            try:
                feature = detector.detect(context)
                if feature and feature.confidence >= self.threshold:
                    features.append(feature)
            except Exception as e:
                logger.debug(f"检测器 {detector.tag} 执行失败: {e}")
        return features

    def _merge_features(self, features: list[SemanticFeature]) -> list[SemanticFeature]:
        """合并来自多个文件的特征

        对于相同标签的特征，合并证据并取最高置信度。
        """
        tag_map: dict[str, SemanticFeature] = {}

        for feature in features:
            if feature.tag in tag_map:
                existing = tag_map[feature.tag]
                # 取最高置信度
                if feature.confidence > existing.confidence:
                    existing.confidence = feature.confidence
                # 合并证据（去重）
                for ev in feature.evidence:
                    if ev not in existing.evidence:
                        existing.evidence.append(ev)
                # 取最高严重程度
                severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
                if severity_order.get(feature.severity, 0) > severity_order.get(existing.severity, 0):
                    existing.severity = feature.severity
            else:
                tag_map[feature.tag] = SemanticFeature(
                    tag=feature.tag,
                    confidence=feature.confidence,
                    evidence=list(feature.evidence),
                    severity=feature.severity,
                )

        return list(tag_map.values())
