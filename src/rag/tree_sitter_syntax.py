"""Tree-sitter Syntax — 语法分析集成

借鉴 Aider 的 tree-sitter-language-pack，提供:
1. 语法树解析
2. 代码结构提取
3. 函数/类/变量定位

用法:
    from src.rag.tree_sitter_syntax import parse_file, extract_functions

    tree = parse_file("test.py")
    functions = extract_functions(tree)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..utils import get_logger

logger = get_logger(__name__)

# Tree-sitter 可用性检测
TREE_SITTER_AVAILABLE = False
try:
    from tree_sitter import Parser
    TREE_SITTER_AVAILABLE = True
except ImportError:
    Parser = None
    logger.debug("tree-sitter not installed, using fallback parser")


# 语言映射
LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".cs": "csharp",
    ".vue": "vue",
    ".svelte": "svelte",
}


class SyntaxTree:
    """语法树封装"""

    def __init__(self, tree: Any, source: str, language: str):
        self.tree = tree
        self.source = source
        self.language = language

    def __repr__(self) -> str:
        return f"<SyntaxTree {self.language} at {id(self.tree):#x}>"


def get_language(file_path: str) -> str | None:
    """根据文件扩展名获取语言

    参数:
        file_path: 文件路径

    Returns:
        语言标识符或 None
    """
    ext = Path(file_path).suffix
    return LANGUAGE_MAP.get(ext.lower())


def parse_code(code: str, language: str) -> SyntaxTree | None:
    """解析代码为语法树

    参数:
        code: 源代码
        language: 语言标识符

    Returns:
        SyntaxTree 或 None
    """
    if not TREE_SITTER_AVAILABLE:
        return None

    try:
        # 简化实现：使用基础 parser
        parser = Parser()
        tree = parser.parse(bytes(code, "utf8"))
        return SyntaxTree(tree, code, language)
    except Exception as e:
        logger.warning(f"Parse failed for {language}: {e}")
        return None


def parse_file(file_path: str) -> SyntaxTree | None:
    """解析文件为语法树

    参数:
        file_path: 文件路径

    Returns:
        SyntaxTree 或 None
    """
    if not os.path.exists(file_path):
        return None

    language = get_language(file_path)
    if not language:
        return None

    try:
        with open(file_path, encoding="utf-8") as f:
            code = f.read()
        return parse_code(code, language)
    except Exception as e:
        logger.warning(f"Failed to read {file_path}: {e}")
        return None


def extract_functions(tree: SyntaxTree) -> list[dict[str, Any]]:
    """从语法树提取函数定义

    参数:
        tree: SyntaxTree

    Returns:
        函数列表
    """
    if not tree:
        return []

    # 简化实现：使用正则表达式回退
    functions = []

    # 根据语言查找函数定义模式 (汲取自 Project B 的高阶模式)
    patterns = {
        "python": r"def\s+(\w+)\s*\(",
        "javascript": r"function\s+(\w+)\s*\(|(\w+)\s*[:=]\s*\(?.*?\)?\s*=>",
        "typescript": r"function\s+(\w+)\s*\(|(\w+)\s*\([^)]*\)\s*{|interface\s+(\w+)\s*{",
        "go": r"func\s+(\w+)\s*\(|func\s+\(\w+\s+\*?\w+\)\s+(\w+)\s*\(",
        "rust": r"fn\s+(\w+)\s*\(|impl\s+\w+\s+{\s*fn\s+(\w+)",
        "ruby": r"def\s+([\w\.]+\w+)",
        "java": r"(?:public|private|protected|static|\s) +[\w\<\>\[\]]+\s+(\w+) *\([^\)]*\) *(?:throws [\w\.]+(?:, [\w\.]+)*)? *\{",
        "swift": r"func\s+(\w+)\s*\(",
    }

    pattern = patterns.get(tree.language, r"def\s+(\w+)\s*\(")

    import re
    for match in re.finditer(pattern, tree.source):
        name = match.group(1) or match.group(2)
        if name:
            functions.append({
                "name": name,
                "line": tree.source[:match.start()].count("\n") + 1,
                "start": match.start(),
                "end": match.end(),
            })

    return functions


def extract_classes(tree: SyntaxTree) -> list[dict[str, Any]]:
    """从语法树提取类定义

    参数:
        tree: SyntaxTree

    Returns:
        类列表
    """
    if not tree:
        return []

    classes = []

    patterns = {
        "python": r"class\s+(\w+)",
        "javascript": r"class\s+(\w+)",
        "java": r"class\s+(\w+)",
        "go": r"type\s+(\w+)\s+struct",
        "rust": r"struct\s+(\w+)",
    }

    pattern = patterns.get(tree.language, r"class\s+(\w+)")

    import re
    for match in re.finditer(pattern, tree.source):
        classes.append({
            "name": match.group(1),
            "line": tree.source[:match.start()].count("\n") + 1,
            "start": match.start(),
            "end": match.end(),
        })

    return classes


def extract_imports(tree: SyntaxTree) -> list[str]:
    """从语法树提取导入语句

    参数:
        tree: SyntaxTree

    Returns:
        导入列表
    """
    if not tree:
        return []

    imports = []

    patterns = {
        "python": r"^import\s+(\S+)|^from\s+(\S+)\s+import",
        "javascript": r"^import\s+.*\s+from\s+['\"]([^'\"]+)['\"]|^require\(['\"]([^'\"]+)['\"]\)",
    }

    pattern = patterns.get(tree.language)

    if not pattern:
        return []

    import re
    for match in re.finditer(pattern, tree.source, re.MULTILINE):
        groups = [g for g in match.groups() if g]
        if groups:
            imports.append(groups[0])

    return imports


def get_code_structure(file_path: str) -> dict[str, Any]:
    """获取代码文件的结构信息

    参数:
        file_path: 文件路径

    Returns:
        结构字典
    """
    tree = parse_file(file_path)
    if not tree:
        return {
            "language": None,
            "functions": [],
            "classes": [],
            "imports": [],
        }

    return {
        "language": tree.language,
        "functions": extract_functions(tree),
        "classes": extract_classes(tree),
        "imports": extract_imports(tree),
    }


def extract_code_blocks(tree: SyntaxTree) -> list[dict[str, Any]]:
    """提取具有语义意义的代码块 (类、函数等)"""
    if not tree:
        return []

    # 包含类和函数
    blocks = []
    classes = extract_classes(tree)
    functions = extract_functions(tree)

    for c in classes:
        blocks.append({
            "type": "class",
            "name": c["name"],
            "line": c["line"],
            "content": _get_block_content(tree.source, c["start"], tree.language)
        })

    for f in functions:
        blocks.append({
            "type": "function",
            "name": f["name"],
            "line": f["line"],
            "content": _get_block_content(tree.source, f["start"], tree.language)
        })

    return sorted(blocks, key=lambda x: x["line"])


def _get_block_content(source: str, start_index: int, language: str) -> str:
    """提取代码块的完整内容 (启发式或使用 tree-sitter)"""
    # 启发式实现：寻找匹配的大括号或缩进块
    if language == "python":
        lines = source[start_index:].splitlines()
        if not lines:
            return ""
        first_line = lines[0]
        indent = len(first_line) - len(first_line.lstrip())
        block_lines = [first_line]
        for line in lines[1:]:
            if not line.strip():
                block_lines.append(line)
                continue
            curr_indent = len(line) - len(line.lstrip())
            if curr_indent <= indent:
                break
            block_lines.append(line)
        return "\n".join(block_lines)
    else:
        # C-style languages: look for matching braces
        content = source[start_index:]
        brace_start = content.find("{")
        if brace_start == -1:
            return content.splitlines()[0] if content else ""

        stack = 0
        end_index = -1
        for i in range(brace_start, len(content)):
            if content[i] == "{":
                stack += 1
            elif content[i] == "}":
                stack -= 1
                if stack == 0:
                    end_index = i
                    break

        if end_index != -1:
            return content[:end_index + 1]
        return content.splitlines()[0]



# ==================== 便捷函数 ====================

def is_tree_sitter_available() -> bool:
    """检查 tree-sitter 是否可用"""
    return TREE_SITTER_AVAILABLE


def get_supported_languages() -> list[str]:
    """获取支持的语言列表"""
    return list(set(LANGUAGE_MAP.values()))


def count_lines_of_code(file_path: str) -> int:
    """计算代码行数（排除空行和注释）

    参数:
        file_path: 文件路径

    Returns:
        代码行数
    """
    if not os.path.exists(file_path):
        return 0

    try:
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()

        code_lines = 0
        in_block_comment = False

        for line in lines:
            stripped = line.strip()

            # 跳过空行
            if not stripped:
                continue

            # 检查块注释
            if '"""' in stripped or "'''" in stripped:
                in_block_comment = not in_block_comment
                continue

            if in_block_comment:
                continue

            # 跳过单行注释
            if stripped.startswith("#") or stripped.startswith("//"):
                continue

            code_lines += 1

        return code_lines
    except Exception:
        return 0


# 导出
__all__ = [
    "SyntaxTree",
    "count_lines_of_code",
    "extract_classes",
    "extract_code_blocks",
    "extract_functions",
    "extract_imports",
    "get_code_structure",
    "get_language",
    "get_supported_languages",
    "is_tree_sitter_available",
    "parse_code",
    "parse_file",
]
