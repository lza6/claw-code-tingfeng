"""Specialized Expert Tools - 企业级专项领域工具集

包含:
1. DocGenTool: 结构化 Docstring 注入
2. SQLAuditTool: 静态 SQL 质量审计
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


class DocGenTool:
    """自动化文档生成工具 (AST 驱动)"""

    def generate_docstring(self, file_path: str, function_name: str, docstring: str) -> bool:
        """为指定的函数注入或更新 Docstring"""
        p = Path(file_path)
        if not p.exists():
            return False

        source = p.read_text(encoding="utf-8")
        tree = ast.parse(source)

        class DocUpdater(ast.NodeTransformer):
            def visit_FunctionDef(self, node):
                if node.name == function_name:
                    new_doc = ast.Expr(value=ast.Constant(value=docstring))
                    if (node.body and isinstance(node.body[0], ast.Expr) and
                        isinstance(node.body[0].value, ast.Constant)):
                        node.body[0] = new_doc
                    else:
                        node.body.insert(0, new_doc)
                return node

        updated_tree = DocUpdater().visit(tree)
        p.write_text(ast.unparse(updated_tree), encoding="utf-8")
        return True

class SQLAuditTool:
    """静态 SQL 审计工具"""

    def audit_sql(self, sql_query: str) -> dict[str, Any]:
        """识别 SQL 中的潜在性能瓶颈"""
        bottlenecks = []

        # 1. 检查 SELECT *
        if re.search(r"SELECT\s+\*", sql_query, re.IGNORECASE):
            bottlenecks.append("SELECT_STAR: 建议明确列名以减少 IO 对象。")

        # 2. 检查缺失 WHERE
        if "select" in sql_query.lower() and "where" not in sql_query.lower():
            bottlenecks.append("MISSING_WHERE: 全表扫描风险。")

        # 3. 检查硬编码 ID
        if re.search(r"WHERE\s+\w+\s*=\s*\d+", sql_query, re.IGNORECASE):
            bottlenecks.append("HARDCODED_ID: 建议使用参数化查询以支持索引缓存。")

        return {
            "passed": len(bottlenecks) == 0,
            "issues": bottlenecks
        }
