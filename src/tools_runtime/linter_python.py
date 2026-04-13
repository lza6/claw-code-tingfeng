"""Python 语法错误检查模块

使用 compile() 进行 Python 语法检查，捕获语法错误并提取行号。
"""
from __future__ import annotations

import sys
import traceback

from .linter_types import LintResult


def lint_python_compile(code: str) -> LintResult:
    """Python 语法错误检查

    使用 compile() 捕获语法错误，从 traceback 中提取
    精确的行号范围。

    参数:
        code: Python 代码字符串

    返回:
        LintResult 对象，无错误时返回空结果
    """
    try:
        compile(code, '<string>', 'exec', dont_inherit=True)
        return LintResult()
    except SyntaxError:
        # 从 traceback 提取错误信息和行号
        exc_info = sys.exc_info()
        if exc_info[1] is None:
            return LintResult()

        error = exc_info[1]
        error_text = str(error)

        # 提取行号
        lines: list[int] = []
        if error.lineno is not None:
            # SyntaxError.lineno 是 1-indexed
            lines.append(error.lineno - 1)

        # 尝试从 traceback 提取更多行号
        tb_lines = _extract_lines_from_traceback()
        for line in tb_lines:
            if line not in lines:
                lines.append(line)

        return LintResult(text=error_text, lines=lines)
    except Exception:
        # 其他异常不作为语法错误
        return LintResult()


def _extract_lines_from_traceback() -> list[int]:
    """从当前 traceback 中提取行号

    辅助函数，用于从异常 traceback 中获取更多
    受影响的行号信息。

    返回:
        0-indexed 行号列表
    """
    lines: list[int] = []

    # 获取当前异常的 traceback
    exc_tb = sys.exc_info()[2]
    if exc_tb is None:
        return lines

    try:
        tb_list = traceback.extract_tb(exc_tb)
        for frame in tb_list:
            if frame.lineno is not None and frame.filename == '<string>':
                # 转换为 0-indexed
                lines.append(frame.lineno - 1)
    except Exception:
        pass

    return lines
