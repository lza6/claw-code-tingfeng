"""Semantic Entropy Analyzer — 语义熵分析器

Phase 1 (IDENTIFY): 不仅扫描代码问题，还计算代码库的"语义熵"，
预测哪些模块最容易产生潜在 Bug。

语义熵衡量代码的"混乱度"和"不确定性"：
- 高熵 = 高度复杂、难以理解、容易出错
- 低熵 = 清晰、简洁、稳定
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .models import EntropyReport

# 熵计算权重
WEIGHT_COMPLEXITY = 0.25     # 圈复杂度
WEIGHT_LENGTH = 0.15         # 代码长度
WEIGHT_NESTING = 0.20        # 嵌套深度
WEIGHT_IMPORTS = 0.10        # 依赖数量
WEIGHT_FUNCTIONS = 0.15      # 函数密度
WEIGHT_CLASSES = 0.15        # 类密度


class SemanticEntropyAnalyzer:
    """语义熵分析器

    计算代码文件的语义熵分数，识别高风险模块。
    """

    def analyze_file(self, file_path: Path) -> EntropyReport:
        """分析单个文件的语义熵

        参数:
            file_path: Python 文件路径

        返回:
            EntropyReport 对象
        """
        try:
            source = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return EntropyReport(
                file_path=str(file_path),
                entropy_score=0.0,
                risk_level="low",
                contributing_factors=[f"无法读取文件: {e}"],
            )

        # 解析 AST
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as e:
            return EntropyReport(
                file_path=str(file_path),
                entropy_score=1.0,  # 语法错误 = 最高熵
                risk_level="critical",
                contributing_factors=[f"语法错误: {e}"],
                hotspots=[f"Line {e.lineno}"],
                recommendations=["修复语法错误"],
            )

        metrics = self._extract_metrics(tree, source)
        entropy = self._calculate_entropy(metrics)
        risk_level = self._classify_risk(entropy)
        factors = self._identify_factors(metrics)
        hotspots = self._find_hotspots(tree, source)
        recommendations = self._generate_recommendations(metrics, entropy)

        return EntropyReport(
            file_path=str(file_path),
            entropy_score=round(entropy, 4),
            risk_level=risk_level,
            contributing_factors=factors,
            hotspots=hotspots,
            recommendations=recommendations,
        )

    def analyze_directory(
        self,
        root_dir: Path,
        pattern: str = "**/*.py",
        threshold: float = 0.5,
    ) -> list[EntropyReport]:
        """分析目录中所有 Python 文件

        参数:
            root_dir: 根目录
            pattern: 文件匹配模式
            threshold: 高熵阈值

        返回:
            熵报告列表 (按熵降序)
        """
        reports: list[EntropyReport] = []
        for file_path in sorted(root_dir.glob(pattern)):
            if file_path.is_file():
                report = self.analyze_file(file_path)
                reports.append(report)

        reports.sort(key=lambda r: r.entropy_score, reverse=True)
        return reports

    def _extract_metrics(self, tree: ast.Module, source: str) -> dict[str, Any]:
        """提取代码度量指标"""
        lines = source.splitlines()
        metrics: dict[str, Any] = {
            "total_lines": len(lines),
            "blank_lines": sum(1 for line in lines if not line.strip()),
            "comment_lines": sum(1 for line in lines if line.strip().startswith("#")),
            "num_functions": 0,
            "num_classes": 0,
            "num_imports": 0,
            "max_nesting_depth": 0,
            "total_complexity": 0,
            "function_complexities": [],
            "function_lengths": [],
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                metrics["num_functions"] += 1
                complexity = self._calculate_function_complexity(node)
                metrics["function_complexities"].append(complexity)
                metrics["total_complexity"] += complexity
                # 函数长度
                func_lines = node.end_lineno - node.lineno + 1 if hasattr(node, "end_lineno") else 10
                metrics["function_lengths"].append(func_lines)

            elif isinstance(node, ast.ClassDef):
                metrics["num_classes"] += 1

            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                metrics["num_imports"] += 1

        # 计算平均嵌套深度
        metrics["avg_nesting_depth"] = self._calc_avg_nesting_depth(tree)

        return metrics

    def _calculate_function_complexity(self, node: ast.FunctionDef) -> int:
        """计算函数圈复杂度"""
        complexity = 1  # 基础复杂度
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.Try,
                                  ast.ExceptHandler, ast.With)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity

    def _calc_avg_nesting_depth(self, tree: ast.Module) -> float:
        """计算平均嵌套深度"""
        depths = []

        def _visit(node: ast.AST, depth: int) -> None:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef,
                                 ast.If, ast.For, ast.While, ast.With,
                                 ast.Try)):
                depths.append(depth)
            for child in ast.iter_child_nodes(node):
                _visit(child, depth + 1)

        for node in ast.iter_child_nodes(tree):
            _visit(node, 0)

        return sum(depths) / len(depths) if depths else 0.0

    def _calculate_entropy(self, metrics: dict[str, Any]) -> float:
        """计算综合熵分数 (0.0 ~ 1.0)

        使用归一化加权平均。
        """
        scores: dict[str, float] = {}

        # 1. 圈复杂度分数 (归一化到 0-1)
        avg_complexity = (
            sum(metrics["function_complexities"]) /
            len(metrics["function_complexities"])
            if metrics["function_complexities"] else 0
        )
        scores["complexity"] = min(1.0, avg_complexity / 15.0)  # 15 为高复杂度阈值

        # 2. 代码长度分数
        loc = metrics["total_lines"] - metrics["blank_lines"] - metrics["comment_lines"]
        scores["length"] = min(1.0, loc / 500.0)  # 500 行为大文件阈值

        # 3. 嵌套深度分数
        scores["nesting"] = min(1.0, metrics["avg_nesting_depth"] / 5.0)

        # 4. 依赖数量分数
        scores["imports"] = min(1.0, metrics["num_imports"] / 30.0)

        # 5. 函数密度分数
        func_density = metrics["num_functions"] / max(1, metrics["total_lines"] / 100)
        scores["functions"] = min(1.0, func_density / 20.0)

        # 6. 类密度分数
        class_density = metrics["num_classes"] / max(1, metrics["total_lines"] / 100)
        scores["classes"] = min(1.0, class_density / 10.0)

        # 加权综合熵
        entropy = (
            scores["complexity"] * WEIGHT_COMPLEXITY +
            scores["length"] * WEIGHT_LENGTH +
            scores["nesting"] * WEIGHT_NESTING +
            scores["imports"] * WEIGHT_IMPORTS +
            scores["functions"] * WEIGHT_FUNCTIONS +
            scores["classes"] * WEIGHT_CLASSES
        )

        return min(1.0, max(0.0, entropy))

    def _classify_risk(self, entropy: float) -> str:
        """根据熵分数分类风险等级"""
        if entropy >= 0.8:
            return "critical"
        elif entropy >= 0.6:
            return "high"
        elif entropy >= 0.35:
            return "medium"
        else:
            return "low"

    def _identify_factors(self, metrics: dict[str, Any]) -> list[str]:
        """识别贡献熵的主要因素"""
        factors: list[str] = []

        if metrics["function_complexities"]:
            max_c = max(metrics["function_complexities"])
            if max_c > 10:
                factors.append(f"高圈复杂度函数 (最大 {max_c})")

        if metrics["total_lines"] > 300:
            factors.append(f"文件过长 ({metrics['total_lines']} 行)")

        if metrics["avg_nesting_depth"] > 4:
            factors.append(f"嵌套过深 (平均 {metrics['avg_nesting_depth']:.1f} 层)")

        if metrics["num_imports"] > 20:
            factors.append(f"依赖过多 ({metrics['num_imports']} 个 import)")

        if metrics["function_lengths"]:
            max_len = max(metrics["function_lengths"])
            if max_len > 50:
                factors.append(f"过长函数 (最大 {max_len} 行)")

        if not factors:
            factors.append("代码结构健康")

        return factors

    def _find_hotspots(
        self, tree: ast.Module, source: str
    ) -> list[str]:
        """识别代码热点 (高风险函数/类)"""
        hotspots: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                complexity = self._calculate_function_complexity(node)
                if complexity > 8:
                    hotspots.append(
                        f"{node.name}() (复杂度 {complexity})"
                    )

            elif isinstance(node, ast.ClassDef):
                methods = sum(
                    1 for n in node.body
                    if isinstance(n, ast.FunctionDef)
                )
                if methods > 10:
                    hotspots.append(
                        f"class {node.name} ({methods} 个方法)"
                    )

        return hotspots[:10]  # 最多返回 10 个热点

    def _generate_recommendations(
        self, metrics: dict[str, Any], entropy: float
    ) -> list[str]:
        """生成优化建议"""
        recommendations: list[str] = []

        if entropy < 0.35:
            return ["代码结构良好，无需优化"]

        if metrics["function_complexities"]:
            max_c = max(metrics["function_complexities"])
            if max_c > 10:
                recommendations.append(
                    "拆分高复杂度函数，使用提取方法模式"
                )

        if metrics["total_lines"] > 300:
            recommendations.append(
                "考虑将文件拆分为多个模块"
            )

        if metrics["avg_nesting_depth"] > 4:
            recommendations.append(
                "减少嵌套深度，使用提前返回或卫语句"
            )

        if metrics["num_imports"] > 20:
            recommendations.append(
                "考虑合并相关导入或使用模块分组"
            )

        if metrics["function_lengths"]:
            max_len = max(metrics["function_lengths"])
            if max_len > 50:
                recommendations.append(
                    "缩短过长函数，提取子逻辑为独立函数"
                )

        if not recommendations:
            recommendations.append("监控代码变化，防止熵增")

        return recommendations
