"""代码变更提取器 — 使用 AST 和更稳健的解析方式

替代原有的正则表达式提取方式，提供更准确的代码变更识别能力。
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CodeBlock:
    """代码块"""
    language: str
    content: str
    file_path: str | None = None
    line_number: int | None = None


@dataclass
class ExtractionResult:
    """提取结果"""
    code_blocks: list[CodeBlock] = field(default_factory=list)
    file_changes: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# 语言到扩展名的映射
LANG_TO_EXT = {
    'python': '.py',
    'javascript': '.js',
    'typescript': '.ts',
    'bash': '.sh',
    'shell': '.sh',
    'json': '.json',
    'yaml': '.yaml',
    'yml': '.yaml',
    'html': '.html',
    'css': '.css',
    'sql': '.sql',
    'rust': '.rs',
    'go': '.go',
    'java': '.java',
    'c': '.c',
    'cpp': '.cpp',
    'ruby': '.rb',
    'php': '.php',
    'swift': '.swift',
    'kotlin': '.kt',
    'scala': '.scala',
    'r': '.r',
    'matlab': '.m',
    'text': '.txt',
}

# 文件路径注释模式
FILE_PATH_PATTERNS = [
    # # file: path/to/file.py
    # # filename: path/to/file.py
    # # path: path/to/file.py
    # # 文件: path/to/file.py
    r'(?:#|//|--|/\*|<!--)\s*(?:file|path|filename|文件|filepath)[:\s]+([\w\./\-]+)',
    # """file: path/to/file.py"""
    r'"""(?:file|path|filename|文件)[:\s]+([\w\./\-]+)"""',
    # '''file: path/to/file.py'''
    r"'''(?:file|path|filename|文件)[:\s]+([\w\./\-]+)'''",
]


def extract_code_blocks(text: str) -> list[CodeBlock]:
    """从文本中提取代码块

    支持多种语言代码块和文件路径标注。

    参数:
        text: 包含代码块的文本

    返回:
        CodeBlock 列表
    """
    code_blocks: list[CodeBlock] = []

    # 匹配代码块: ```language\ncode\n```
    code_block_pattern = re.compile(r'```(\w+)?\s*\n(.*?)(?:\n)?```', re.DOTALL)

    for match in code_block_pattern.finditer(text):
        lang = (match.group(1) or 'text').lower()
        content = match.group(2)

        # 尝试从代码块中提取文件路径
        file_path = _extract_file_path(content)

        code_blocks.append(CodeBlock(
            language=lang,
            content=content,
            file_path=file_path,
        ))

    return code_blocks


def extract_file_changes(text: str, task_metadata: dict[str, Any] | None = None) -> dict[str, str]:
    """从文本中提取文件变更

    使用更稳健的解析方式：
    1. 优先使用代码块中的文件路径标注
    2. 其次使用任务元数据中的文件路径
    3. 最后根据语言推断扩展名

    参数:
        text: 包含代码变更的文本
        task_metadata: 任务元数据（可选）

    返回:
        {file_path: code_content} 字典
    """
    file_changes: dict[str, str] = {}
    code_blocks = extract_code_blocks(text)

    for i, block in enumerate(code_blocks):
        filename = block.file_path

        if not filename:
            # 从任务元数据获取文件路径
            if task_metadata and 'file_path' in task_metadata:
                filename = task_metadata['file_path']

            if not filename:
                # 根据语言推断文件扩展名
                ext = LANG_TO_EXT.get(block.language, '.txt')
                filename = f'generated_block_{i}{ext}'

        file_changes[filename] = block.content

    return file_changes


def validate_python_code(code: str) -> tuple[bool, str]:
    """验证 Python 代码的语法正确性

    参数:
        code: Python 代码字符串

    返回:
        (is_valid, error_message) 元组
    """
    try:
        ast.parse(code)
        return True, ''
    except SyntaxError as e:
        return False, f'语法错误: {e.msg} (行 {e.lineno})'
    except Exception as e:
        return False, f'解析错误: {e!s}'


def _extract_file_path(content: str) -> str | None:
    """从代码内容中提取文件路径"""
    for pattern in FILE_PATH_PATTERNS:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            path_str = match.group(1).strip()
            # [安全加固] 拦截绝对路径和回溯路径
            if Path(path_str).is_absolute() or '..' in path_str.replace('\\', '/').split('/'):
                return None
            return path_str
    return None


def extract_code_changes_from_messages(messages: list[dict[str, str]]) -> dict[str, str]:
    """从消息历史中提取代码变更

    参数:
        messages: 消息列表，每个消息包含 role 和 content

    返回:
        {file_path: code_content} 字典
    """
    code_changes: dict[str, str] = {}

    for msg in messages:
        if msg.get('role') != 'assistant':
            continue

        content = msg.get('content', '')
        blocks = extract_code_blocks(content)

        for block in blocks:
            filename = block.file_path
            if not filename:
                ext = LANG_TO_EXT.get(block.language, '.txt')
                filename = f'generated_code_{len(code_changes)}{ext}'

            code_changes[filename] = block.content

    return code_changes
