"""错误分类器 — 对错误进行分类并匹配已知模式"""
from __future__ import annotations

import copy
import re

from .models import ErrorCategory, ErrorPattern, HealingStrategyType

# 预定义错误模式
BUILTIN_PATTERNS: list[ErrorPattern] = [
    # --- Syntax ---
    ErrorPattern(
        id='syntax-001',
        category=ErrorCategory.SYNTAX,
        signature=r'(SyntaxError|invalid syntax|unexpected EOF)',
        description='Python 语法错误',
        strategy=HealingStrategyType.CODE_PATCH,
        fix_prompt='请检查以下代码的语法错误并修复：\n\n{code}\n\n错误信息：{error}\n\n请输出修复后的完整代码。',
        confidence=0.9,
    ),
    ErrorPattern(
        id='syntax-002',
        category=ErrorCategory.SYNTAX,
        signature=r'(IndentationError|expected an indented block)',
        description='缩进错误',
        strategy=HealingStrategyType.CODE_PATCH,
        fix_prompt='请修复以下代码的缩进错误：\n\n{code}\n\n错误信息：{error}',
        confidence=0.95,
    ),
    # --- Import ---
    ErrorPattern(
        id='import-001',
        category=ErrorCategory.IMPORT,
        signature=r'ModuleNotFoundError|No module named',
        description='模块未找到',
        strategy=HealingStrategyType.CONFIG_FIX,
        fix_prompt='以下代码导入了一个不存在的模块：\n\n{code}\n\n错误信息：{error}\n\n请提供替代方案或修复导入。',
        confidence=0.8,
    ),
    ErrorPattern(
        id='import-002',
        category=ErrorCategory.IMPORT,
        signature=r'ImportError|cannot import name',
        description='导入名称不存在',
        strategy=HealingStrategyType.CODE_PATCH,
        fix_prompt='以下代码导入了一个不存在的名称：\n\n{code}\n\n错误信息：{error}\n\n请修复导入语句。',
        confidence=0.85,
    ),
    # --- Runtime ---
    ErrorPattern(
        id='runtime-001',
        category=ErrorCategory.RUNTIME,
        signature=r'FileNotFoundError|No such file or directory',
        description='文件不存在',
        strategy=HealingStrategyType.WORKAROUND,
        fix_prompt='以下代码尝试访问一个不存在的文件：\n\n{code}\n\n错误信息：{error}\n\n请添加文件检查或修复路径。',
        confidence=0.8,
    ),
    ErrorPattern(
        id='runtime-002',
        category=ErrorCategory.RUNTIME,
        signature=r'PermissionError|Permission denied',
        description='权限不足',
        strategy=HealingStrategyType.SKIP_AND_LOG,
        fix_prompt='权限不足，跳过该操作并记录。',
        confidence=0.9,
    ),
    ErrorPattern(
        id='runtime-003',
        category=ErrorCategory.RUNTIME,
        signature=r'(KeyError|IndexError|AttributeError|TypeError|ValueError)',
        description='运行时类型/值错误',
        strategy=HealingStrategyType.CODE_PATCH,
        fix_prompt='以下代码存在运行时错误：\n\n{code}\n\n错误信息：{error}\n\n请修复该错误。',
        confidence=0.7,
    ),
    # --- LLM ---
    ErrorPattern(
        id='llm-001',
        category=ErrorCategory.LLM,
        signature=r'(rate.limit|too many requests|429)',
        description='LLM API 速率限制',
        strategy=HealingStrategyType.WORKAROUND,
        fix_prompt='LLM API 触发速率限制，等待后重试。',
        confidence=0.9,
    ),
    ErrorPattern(
        id='llm-002',
        category=ErrorCategory.LLM,
        signature=r'(context.length|token|maximum context)',
        description='LLM 上下文长度超限',
        strategy=HealingStrategyType.CODE_PATCH,
        fix_prompt='LLM 上下文长度超限。请截断或压缩以下输入：\n\n{code}',
        confidence=0.75,
    ),
    # --- Security ---
    ErrorPattern(
        id='security-001',
        category=ErrorCategory.SECURITY,
        signature=r'(eval|exec|pickle)\s*\(.*unsafe|insecure',
        description='不安全代码检测',
        strategy=HealingStrategyType.CODE_PATCH,
        fix_prompt='以下代码存在安全风险：\n\n{code}\n\n请使用安全替代方案修复。',
        confidence=0.85,
    ),
    # --- Timeout ---
    ErrorPattern(
        id='timeout-001',
        category=ErrorCategory.TIMEOUT,
        signature=r'(timeout|timed out|TimeoutError)',
        description='操作超时',
        strategy=HealingStrategyType.WORKAROUND,
        fix_prompt='操作超时，请重试或优化性能。',
        confidence=0.7,
    ),
]


class ErrorClassifier:
    """错误分类器

    职责:
    - 根据错误消息分类错误类型
    - 匹配已知错误模式
    """

    def __init__(self, patterns: list[ErrorPattern] | None = None) -> None:
        # Deep copy to avoid cross-instance state contamination
        self.patterns = patterns or [copy.deepcopy(p) for p in BUILTIN_PATTERNS]

    def classify(self, error: str) -> ErrorCategory:
        """分类错误类型

        参数:
            error: 错误消息

        返回:
            ErrorCategory 枚举值
        """
        error_lower = error.lower()

        # Syntax
        if any(kw in error_lower for kw in ['syntaxerror', 'indentationerror', 'invalid syntax']):
            return ErrorCategory.SYNTAX

        # Import
        if any(kw in error_lower for kw in ['modulenotfounderror', 'importerror', 'no module', 'cannot import', 'import error']):
            return ErrorCategory.IMPORT

        # Runtime
        if any(kw in error_lower for kw in [
            'filenotfounderror', 'permissionerror', 'keyerror', 'indexerror',
            'attributeerror', 'typeerror', 'valueerror', 'runtimeerror',
        ]):
            return ErrorCategory.RUNTIME

        # LLM
        if any(kw in error_lower for kw in ['rate limit', '429', 'context', 'token', 'maximum']):
            return ErrorCategory.LLM

        # Security
        if any(kw in error_lower for kw in ['unsafe', 'insecure', 'security']):
            return ErrorCategory.SECURITY

        # Timeout
        if any(kw in error_lower for kw in ['timeout', 'timed out']):
            return ErrorCategory.TIMEOUT

        return ErrorCategory.UNKNOWN

    def match_pattern(self, error: str) -> ErrorPattern | None:
        """匹配已知错误模式

        参数:
            error: 错误消息

        返回:
            匹配的 ErrorPattern，或 None
        """
        # 按置信度降序匹配
        sorted_patterns = sorted(self.patterns, key=lambda p: -p.confidence)

        for pattern in sorted_patterns:
            if re.search(pattern.signature, error, re.IGNORECASE):
                return pattern

        return None

    def add_pattern(self, pattern: ErrorPattern) -> None:
        """添加自定义错误模式"""
        self.patterns.append(pattern)
