"""Lint 结果数据类型定义"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LintResult:
    """代码检查结果

    属性:
        text: 错误消息文本，空字符串表示无错误
        lines: 受影响的 0-indexed 行号列表
    """
    text: str = ''
    lines: list[int] = field(default_factory=list)

    def __bool__(self) -> bool:
        """有错误时返回 True"""
        return bool(self.text)


# 语言扩展名到语言名称的映射
LANGUAGE_EXTENSIONS: dict[str, str] = {
    '.py': 'python',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    '.go': 'go',
    '.rs': 'rust',
    '.java': 'java',
    '.c': 'c',
    '.cpp': 'cpp',
    '.h': 'c',
    '.hpp': 'cpp',
    '.rb': 'ruby',
    '.php': 'php',
    '.sh': 'shell',
    '.bash': 'shell',
    '.zsh': 'shell',
}
