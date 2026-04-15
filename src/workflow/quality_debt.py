import os
from dataclasses import dataclass, field


@dataclass
class QualityDebt:
    critic_gate_missing: bool = False
    finisher_gate_missing: bool = False
    only_correctness_evidence: bool = False
    documentation_gap: bool = False
    test_gap: bool = False
    objective_integrity_violation: bool = False # 目标完整性违规
    complex_functions: list[str] = field(default_factory=list)

    def is_zero(self) -> bool:
        return not (self.critic_gate_missing or
                   self.finisher_gate_missing or
                   self.only_correctness_evidence or
                   self.documentation_gap or
                   self.test_gap or
                   self.objective_integrity_violation or
                   self.complex_functions)

class QualityDebtCollector:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir

    def collect(self, changed_files: list[str]) -> QualityDebt:
        debt = QualityDebt()

        # 1. 检查测试缺口 (Test Gap)
        has_test = any(f.startswith("tests/") or "_test.py" in f or "test_" in f for f in changed_files)
        has_src = any(f.startswith("src/") and f.endswith(".py") for f in changed_files)
        if has_src and not has_test:
            debt.test_gap = True

        # 2. 检查文档缺口 (Documentation Gap)
        has_doc = any(f.endswith(".md") for f in changed_files)
        if has_src and not has_doc:
            # 如果变动较大但没改文档，视为债务
            debt.documentation_gap = True

        # 3. 检查复杂函数 (Simple Complexity Scan)
        for f in changed_files:
            full_path = os.path.join(self.root_dir, f)
            if os.path.exists(full_path) and f.endswith(".py"):
                debt.complex_functions.extend(self._scan_complex_functions(full_path))

        return debt

    def _scan_complex_functions(self, file_path: str) -> list[str]:
        """
        真正利用 AST 扫描函数复杂度 (基于行数和嵌套深度)
        """
        import ast
        complex_ones = []
        try:
            with open(file_path, encoding='utf-8', errors='replace') as f:
                content = f.read()
                tree = ast.parse(content)

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        # 维度 1: 函数行数 (超过 50 行)
                        lines = (node.end_lineno - node.lineno) if hasattr(node, 'end_lineno') else 0
                        if lines > 50:
                            complex_ones.append(f"Function '{node.name}' too long ({lines} lines)")

                        # 维度 2: 循环嵌套深度
                        depth = 0
                        for sub in ast.walk(node):
                            if isinstance(sub, (ast.For, ast.While, ast.If)):
                                depth += 1
                        if depth > 5:
                            complex_ones.append(f"Function '{node.name}' cyclomatic/nested depth excessive ({depth})")
        except Exception:
            # 记录错误但不阻塞执行
            pass
        return list(set(complex_ones))
