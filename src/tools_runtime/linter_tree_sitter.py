"""Tree-sitter AST 语法错误检查

从 Aider linter.py 移植，提供通用的 AST 语法错误检测，
支持所有 tree-sitter 语言。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .linter_types import LintResult

# 语言名到 tree-sitter 语言名的映射
_TREE_SITTER_LANG_MAP: dict[str, str] = {
    '.py': 'python',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'tsx',
    '.go': 'go',
    '.rs': 'rust',
    '.java': 'java',
    '.c': 'c',
    '.cpp': 'cpp',
    '.h': 'c',
    '.hpp': 'cpp',
    '.rb': 'ruby',
    '.php': 'php',
    '.sh': 'bash',
    '.bash': 'bash',
    '.zsh': 'bash',
    '.html': 'html',
    '.css': 'css',
    '.json': 'json',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.toml': 'toml',
    '.md': 'markdown',
    '.sql': 'sql',
    '.r': 'r',
    '.lua': 'lua',
    '.zig': 'zig',
    '.swift': 'swift',
    '.kt': 'kotlin',
    '.scala': 'scala',
}

# tree-sitter parser 缓存
_ts_parser_cache: dict[str, Any] = {}


def _get_ts_parser(lang: str) -> Any:
    """获取 tree-sitter parser（带缓存）

    参数:
        lang: tree-sitter 语言名

    返回:
        parser 对象，或 None（不支持）
    """
    if lang in _ts_parser_cache:
        return _ts_parser_cache[lang]

    try:
        import tree_sitter_languages as tsl
        parser = tsl.get_parser(lang)
        _ts_parser_cache[lang] = parser
        return parser
    except ImportError:
        return None
    except Exception:
        return None


def tree_sitter_lint(fname: str, code: str) -> LintResult:
    """使用 tree-sitter 进行 AST 语法错误检测

    检测语法错误（ERROR 和 MISSING 节点），适用于所有 tree-sitter 支持的语言。

    参数:
        fname: 文件名
        code: 文件内容

    返回:
        LintResult 对象，无错误时返回空结果
    """
    ext = Path(fname).suffix.lower()
    lang = _TREE_SITTER_LANG_MAP.get(ext)

    if not lang:
        return LintResult()

    # TypeScript 暂不支持（tree-sitter 有已知问题）
    if lang == 'typescript' or lang == 'tsx':
        return LintResult()

    parser = _get_ts_parser(lang)
    if parser is None:
        return LintResult()

    try:
        tree = parser.parse(bytes(code, 'utf-8'))
        errors = _traverse_tree(tree.root_node)
        if errors:
            return LintResult(text='AST syntax errors detected', lines=errors)
    except RecursionError:
        pass
    except Exception:
        pass

    return LintResult()


def _traverse_tree(node: Any) -> list[int]:
    """遍历 tree-sitter AST 查找 ERROR 和 MISSING 节点

    参数:
        node: tree-sitter 节点

    返回:
        0-indexed 错误行号列表
    """
    errors: list[int] = []
    if node.type == 'ERROR' or node.is_missing:
        errors.append(node.start_point[0])

    for child in node.children:
        errors.extend(_traverse_tree(child))

    return errors
