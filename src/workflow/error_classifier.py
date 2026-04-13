"""错误分类器 — 自动识别执行错误的类型"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ErrorCategory(Enum):
    """错误分类枚举"""
    SYNTAX = 'syntax'                    # 语法错误 (SyntaxError, IndentationError)
    FILE_NOT_FOUND = 'file_not_found'    # 文件/路径不存在
    PERMISSION = 'permission'            # 权限不足
    IMPORT = 'import'                    # 模块导入错误
    RUNTIME = 'runtime'                  # 运行时错误 (TypeError, ValueError, etc.)
    NETWORK = 'network'                  # 网络错误
    TIMEOUT = 'timeout'                  # 超时错误
    RESOURCE = 'resource'                # 资源不足 (内存、磁盘等)
    UNKNOWN = 'unknown'                  # 未知错误


@dataclass
class ErrorPattern:
    """错误模式定义"""
    pattern_id: str                      # 模式唯一标识
    category: ErrorCategory              # 错误类型
    regex_patterns: list[str]            # 用于匹配的正则列表
    description: str                     # 模式描述
    suggested_fix: str                   # 建议修复方案
    severity: str = 'medium'             # 严重程度: low/medium/high/critical


@dataclass
class ErrorClassification:
    """错误分类结果"""
    category: ErrorCategory              # 错误类型
    pattern: ErrorPattern | None         # 匹配的模式
    original_error: str                  # 原始错误信息
    confidence: float                    # 置信度 (0.0-1.0)
    suggested_fix: str                   # 建议修复方案

    @property
    def is_known_pattern(self) -> bool:
        return self.pattern is not None


# ---------------------------------------------------------------------------
# 内置错误模式
# ---------------------------------------------------------------------------

BUILTIN_ERROR_PATTERNS: list[ErrorPattern] = [
    # --- 语法错误 ---
    ErrorPattern(
        pattern_id='syntax_error',
        category=ErrorCategory.SYNTAX,
        regex_patterns=[
            r'SyntaxError',
            r'invalid syntax',
            r'unexpected indent',
            r'unexpected unindent',
            r'unexpected EOF',
            r'语法错误',
        ],
        description='Python 语法错误',
        suggested_fix='检查语法错误，建议注释掉问题行后重试',
        severity='high',
    ),
    ErrorPattern(
        pattern_id='indentation_error',
        category=ErrorCategory.SYNTAX,
        regex_patterns=[
            r'IndentationError',
            r'expected an indented block',
            r'缩进错误',
        ],
        description='缩进错误',
        suggested_fix='修正代码缩进',
        severity='high',
    ),

    # --- 文件不存在 ---
    ErrorPattern(
        pattern_id='file_not_found',
        category=ErrorCategory.FILE_NOT_FOUND,
        regex_patterns=[
            r'FileNotFoundError',
            r'No such file or directory',
            r'没有那个文件或目录',
            r'文件不存在',
            r'not found',
        ],
        description='文件或目录不存在',
        suggested_fix='检查文件路径是否正确，或跳过该任务',
        severity='medium',
    ),

    # --- 权限错误 ---
    ErrorPattern(
        pattern_id='permission_error',
        category=ErrorCategory.PERMISSION,
        regex_patterns=[
            r'PermissionError',
            r'[Pp]ermission denied',
            r'权限不够',
            r'权限不足',
            r'[Aa]ccess denied',
        ],
        description='权限不足',
        suggested_fix='跳过该任务并记录，需要人工授权',
        severity='medium',
    ),

    # --- 导入错误 ---
    ErrorPattern(
        pattern_id='import_error',
        category=ErrorCategory.IMPORT,
        regex_patterns=[
            r'ImportError',
            r'ModuleNotFoundError',
            r'No module named',
            r'cannot import name',
            r'导入错误',
            r'模块不存在',
        ],
        description='模块导入错误',
        suggested_fix='检查依赖是否已安装，或修改导入语句',
        severity='high',
    ),

    # --- 运行时错误 ---
    ErrorPattern(
        pattern_id='type_error',
        category=ErrorCategory.RUNTIME,
        regex_patterns=[
            r'TypeError',
            r'type.*argument',
            r'类型错误',
        ],
        description='类型错误',
        suggested_fix='检查参数类型，添加类型转换',
        severity='medium',
    ),
    ErrorPattern(
        pattern_id='value_error',
        category=ErrorCategory.RUNTIME,
        regex_patterns=[
            r'ValueError',
            r'invalid literal',
            r'值错误',
        ],
        description='值错误',
        suggested_fix='检查输入值的有效性',
        severity='medium',
    ),
    ErrorPattern(
        pattern_id='attribute_error',
        category=ErrorCategory.RUNTIME,
        regex_patterns=[
            r'AttributeError',
            r'has no attribute',
            r'属性错误',
        ],
        description='属性错误',
        suggested_fix='检查对象是否有该属性',
        severity='medium',
    ),
    ErrorPattern(
        pattern_id='key_error',
        category=ErrorCategory.RUNTIME,
        regex_patterns=[
            r'KeyError',
            r'键错误',
        ],
        description='字典键不存在',
        suggested_fix='检查键是否存在，使用 .get() 方法',
        severity='low',
    ),
    ErrorPattern(
        pattern_id='index_error',
        category=ErrorCategory.RUNTIME,
        regex_patterns=[
            r'IndexError',
            r'list index out of range',
            r'索引错误',
        ],
        description='索引越界',
        suggested_fix='检查索引范围',
        severity='low',
    ),

    # --- 网络错误 ---
    ErrorPattern(
        pattern_id='network_error',
        category=ErrorCategory.NETWORK,
        regex_patterns=[
            r'ConnectionError',
            r'Connection refused',
            r'Network is unreachable',
            r'[Nn]etwork error',
            r'连接失败',
        ],
        description='网络连接错误',
        suggested_fix='检查网络连接，稍后重试',
        severity='medium',
    ),

    # --- 超时错误 ---
    ErrorPattern(
        pattern_id='timeout_error',
        category=ErrorCategory.TIMEOUT,
        regex_patterns=[
            r'TimeoutError',
            r'timed out',
            r'timeout',
            r'超时',
        ],
        description='操作超时',
        suggested_fix='增加超时时间或优化代码性能',
        severity='medium',
    ),

    # --- 资源错误 ---
    ErrorPattern(
        pattern_id='memory_error',
        category=ErrorCategory.RESOURCE,
        regex_patterns=[
            r'MemoryError',
            r'[Mm]emory',
            r'内存不足',
        ],
        description='内存不足',
        suggested_fix='减少数据量或增加内存',
        severity='high',
    ),
]


# ---------------------------------------------------------------------------
# 错误分类器
# ---------------------------------------------------------------------------

class ErrorClassifier:
    """错误分类器 — 自动识别执行错误的类型"""

    def __init__(self, patterns: list[ErrorPattern] | None = None) -> None:
        """初始化错误分类器

        参数:
            patterns: 自定义错误模式列表（会添加到内置模式之前）
        """
        self._patterns = (patterns or []) + BUILTIN_ERROR_PATTERNS

    def classify(self, error: Exception | str) -> ErrorClassification:
        """分类错误

        参数:
            error: 异常对象或错误信息字符串

        返回:
            ErrorClassification 分类结果
        """
        error_str = str(error) if isinstance(error, Exception) else error
        error_type = type(error).__name__ if isinstance(error, Exception) else ''

        # 匹配错误模式
        best_match: ErrorPattern | None = None
        best_score = 0.0

        for pattern in self._patterns:
            score = self._match_pattern(error_str, error_type, pattern)
            if score > best_score:
                best_score = score
                best_match = pattern

        # 生成分类结果
        if best_match:
            return ErrorClassification(
                category=best_match.category,
                pattern=best_match,
                original_error=error_str,
                confidence=min(best_score, 1.0),
                suggested_fix=best_match.suggested_fix,
            )
        else:
            # 未知错误
            return ErrorClassification(
                category=ErrorCategory.UNKNOWN,
                pattern=None,
                original_error=error_str,
                confidence=0.0,
                suggested_fix=f'未知错误: {error_str[:100]}，建议人工审查',
            )

    def match_pattern(
        self,
        error: Exception | str,
        pattern_id: str,
    ) -> bool:
        """检查错误是否匹配指定模式

        参数:
            error: 异常对象或错误信息字符串
            pattern_id: 模式 ID

        返回:
            是否匹配
        """
        error_str = str(error) if isinstance(error, Exception) else error
        error_type = type(error).__name__ if isinstance(error, Exception) else ''

        for pattern in self._patterns:
            if pattern.pattern_id == pattern_id:
                return self._match_pattern(error_str, error_type, pattern) > 0
        return False

    def get_stats(self) -> dict[str, Any]:
        """获取分类器统计"""
        category_counts: dict[str, int] = {}
        for p in self._patterns:
            cat = p.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1
        return {
            'total_patterns': len(self._patterns),
            'categories': category_counts,
        }

    # -- 内部方法 --

    @staticmethod
    def _match_pattern(
        error_str: str,
        error_type: str,
        pattern: ErrorPattern,
    ) -> float:
        """匹配错误模式

        返回:
            匹配分数 (0.0 表示不匹配)
        """
        max_score = 0.0

        for regex in pattern.regex_patterns:
            # 匹配错误类型
            if error_type and re.search(regex, error_type, re.IGNORECASE):
                max_score = max(max_score, 1.0)
            # 匹配错误信息
            if re.search(regex, error_str, re.IGNORECASE):
                max_score = max(max_score, 0.8)

        return max_score
