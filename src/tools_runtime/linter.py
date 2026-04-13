"""多策略代码检查模块 — 从 Aider linter.py 增强移植

提供多语言语法错误检测能力。

核心设计原则:
- Python 文件：使用 compile() + tree-sitter + flake8 三重检查
- 其他语言：通过 set_linter() 配置可选的外部 lint 命令
- tree-sitter 通用 AST 语法错误检测（支持所有 tree-sitter 语言）
- 仅检查致命错误（语法错误、未定义名称等），不检查代码风格
- 容错设计：无法检查的文件返回空的 LintResult

示例:
    >>> linter = Linter(root='/path/to/project')
    >>> result = linter.lint('example.py')
    >>> if result.text:
    ...     print(format_lint_result(result, 'example.py', code))

向后兼容: 所有导出保持不变，从子模块重新导出。
"""
from __future__ import annotations

# 从子模块重新导出，保持向后兼容
from .linter_linter import Linter, basic_lint, lint_file
from .linter_python import lint_python_compile
from .linter_tree_sitter import tree_sitter_lint
from .linter_types import LANGUAGE_EXTENSIONS, LintResult
from .linter_utils import format_lint_result

# 保持 __all__ 导出
__all__ = [
    'LANGUAGE_EXTENSIONS',
    'LintResult',
    'Linter',
    'basic_lint',
    'format_lint_result',
    'lint_file',
    'lint_python_compile',
    'tree_sitter_lint',
]
