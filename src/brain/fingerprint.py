"""Context Fingerprint — 语义上下文指纹 (Ported from Onyx V4)

用于检测代码语义内容的实质性变化，过滤掉格式调整、注释修改等非功能性变更。
"""
from __future__ import annotations

import ast
import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

class FingerprintGenerator(ast.NodeVisitor):
    """AST 遍历器，提取关键语义特征"""

    def __init__(self):
        self.features = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # 记录函数名、参数名和返回类型
        args = [arg.arg for arg in node.args.args]
        self.features.append(f"func:{node.name}({','.join(args)})")
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        args = [arg.arg for arg in node.args.args]
        self.features.append(f"async_func:{node.name}({','.join(args)})")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        bases = [ast.unparse(base) for base in node.bases]
        self.features.append(f"class:{node.name}bases:{','.join(bases)}")
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.features.append(f"import:{alias.name}")

    def visit_ImportFrom(self, node: ast.ImportFrom):
        self.features.append(f"from_import:{node.module}")

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            self.features.append(f"call:{node.func.id}")
        elif isinstance(node.func, ast.Attribute):
             self.features.append(f"call_attr:{node.func.attr}")
        self.generic_visit(node)

class ContextFingerprint:
    """语义指纹管理器"""

    @staticmethod
    def generate(file_path: Path | str) -> str:
        """为文件生成语义指纹"""
        path = Path(file_path)
        if not path.exists() or not path.suffix == '.py':
            return ""

        try:
            source = path.read_text(encoding='utf-8', errors='replace')
            tree = ast.parse(source)
            generator = FingerprintGenerator()
            generator.visit(tree)
            
            # 将特征列表排序并哈希
            feature_str = "|".join(sorted(generator.features))
            return hashlib.blake2b(feature_str.encode()).hexdigest()
        except Exception as e:
            logger.debug(f"生成指纹失败 {file_path}: {e}")
            return ""

    @staticmethod
    def compare(old_fp: str, new_fp: str) -> bool:
        """比较指纹是否一致"""
        return old_fp == new_fp and old_fp != ""
