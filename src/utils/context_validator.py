"""
上下文指纹验证工具

灵感来源: ClawGod patch.js 中的 validate 函数

设计思想:
- 通过检查匹配位置附近的代码上下文来确认这是正确的匹配位置
- 局部上下文指纹验证技术
- 防止误匹配，提高代码修改准确率

使用示例:
    # 基础用法
    validator = ContextValidator(context_window=500)
    if validator.validate_by_keywords(code, match_str, ['growthBook', 'GrowthBook']):
        print("Context validated!")

    # 创建可复用验证器
    validate = create_keyword_validator(['growthBook', 'GrowthBook'])
    if validate(match_str, full_code):
        print("Valid!")

    # 正则验证
    validate = create_regex_validator(r'growthBook|GrowthBook|FeatureValue')
    if validate(match_str, full_code):
        print("Valid!")
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    context: str = ""
    matched_keywords: list[str] = None
    matched_patterns: list[str] = None
    reason: str = ""

    def __post_init__(self):
        if self.matched_keywords is None:
            self.matched_keywords = []
        if self.matched_patterns is None:
            self.matched_patterns = []


class ContextValidator:
    """
    上下文指纹验证器

    通过分析匹配位置附近的代码上下文，确认这是正确的匹配位置。
    这是一种"局部上下文指纹验证"技术。
    """

    def __init__(self, context_window: int = 500):
        """
        Args:
            context_window: 上下文窗口大小（字符数，前后各此大小）
        """
        self.context_window = context_window

    def get_context(self, code: str, match_str_or_pos: str | int) -> str:
        """
        获取匹配位置附近的代码上下文

        Args:
            code: 完整代码
            match_str_or_pos: 匹配的字符串或位置索引

        Returns:
            匹配位置附近的代码上下文
        """
        if isinstance(match_str_or_pos, int):
            pos = match_str_or_pos
        else:
            pos = code.find(match_str_or_pos)
            if pos == -1:
                return ""

        start = max(0, pos - self.context_window)
        end = min(len(code), pos + len(match_str_or_pos) if isinstance(match_str_or_pos, str) else pos + self.context_window)
        return code[start:end]

    def get_context_at(self, code: str, match_pos: int) -> str:
        """
        获取指定位置的代码上下文

        Args:
            code: 完整代码
            match_pos: 匹配位置索引

        Returns:
            匹配位置附近的代码上下文
        """
        start = max(0, match_pos - self.context_window)
        end = min(len(code), match_pos + self.context_window)
        return code[start:end]

    def validate_by_keywords(
        self,
        code: str,
        match_str: str,
        keywords: list[str],
        require_all: bool = False,
    ) -> ValidationResult:
        """
        通过关键字验证上下文

        Args:
            code: 完整代码
            match_str: 匹配的字符串
            keywords: 需要匹配的关键字列表
            require_all: 是否需要匹配所有关键字（默认 False，匹配任一即可）

        Returns:
            ValidationResult 包含验证结果和上下文信息
        """
        context = self.get_context(code, match_str)
        if not context:
            return ValidationResult(
                is_valid=False,
                reason="Match string not found in code"
            )

        matched = [kw for kw in keywords if kw in context]

        if require_all:
            is_valid = len(matched) == len(keywords)
        else:
            is_valid = len(matched) > 0

        return ValidationResult(
            is_valid=is_valid,
            context=context,
            matched_keywords=matched,
            reason=f"Found {len(matched)}/{len(keywords)} keywords" if is_valid else "No keywords found in context"
        )

    def validate_by_regex(
        self,
        code: str,
        match_str: str,
        pattern: str,
        flags: int = 0,
    ) -> ValidationResult:
        """
        通过正则表达式验证上下文

        Args:
            code: 完整代码
            match_str: 匹配的字符串
            pattern: 正则表达式模式
            flags: 正则表达式标志

        Returns:
            ValidationResult 包含验证结果和匹配的模式
        """
        context = self.get_context(code, match_str)
        if not context:
            return ValidationResult(
                is_valid=False,
                reason="Match string not found in code"
            )

        matches = re.findall(pattern, context, flags)
        is_valid = len(matches) > 0

        return ValidationResult(
            is_valid=is_valid,
            context=context,
            matched_patterns=[str(m) for m in matches[:5]],  # 最多返回 5 个匹配
            reason=f"Found {len(matches)} pattern matches" if is_valid else "No patterns found in context"
        )

    def validate_by_structure(
        self,
        code: str,
        match_str: str,
        expected_before: str | None = None,
        expected_after: str | None = None,
        max_distance: int = 200,
    ) -> ValidationResult:
        """
        通过代码结构验证上下文

        Args:
            code: 完整代码
            match_str: 匹配的字符串
            expected_before: 匹配前应该出现的字符串
            expected_after: 匹配后应该出现的字符串
            max_distance: 最大搜索距离（字符数）

        Returns:
            ValidationResult 包含验证结果
        """
        pos = code.find(match_str)
        if pos == -1:
            return ValidationResult(
                is_valid=False,
                reason="Match string not found in code"
            )

        # 检查前面的内容
        before_ok = True
        if expected_before:
            search_start = max(0, pos - max_distance)
            before_content = code[search_start:pos]
            before_ok = expected_before in before_content

        # 检查后面的内容
        after_ok = True
        if expected_after:
            search_end = min(len(code), pos + len(match_str) + max_distance)
            after_content = code[pos + len(match_str):search_end]
            after_ok = expected_after in after_content

        is_valid = before_ok and after_ok

        reasons = []
        if expected_before and not before_ok:
            reasons.append(f"'{expected_before}' not found before match")
        if expected_after and not after_ok:
            reasons.append(f"'{expected_after}' not found after match")

        return ValidationResult(
            is_valid=is_valid,
            context=self.get_context(code, match_str),
            reason="; ".join(reasons) if reasons else "Structure validated successfully"
        )

    def find_all_with_context(
        self,
        code: str,
        pattern: str,
        flags: int = re.MULTILINE,
    ) -> list[tuple[str, str, int]]:
        """
        查找所有匹配并返回上下文

        Args:
            code: 完整代码
            pattern: 正则表达式模式
            flags: 正则表达式标志

        Returns:
            列表，每个元素为 (match_str, context, position)
        """
        results = []
        for match in re.finditer(pattern, code, flags):
            context = self.get_context_at(code, match.start())
            results.append((match.group(), context, match.start()))
        return results


# ─── 便捷函数 ─────────────────────────────────────────────────────────

def create_keyword_validator(
    keywords: list[str],
    require_all: bool = False,
    context_window: int = 500,
) -> Callable[[str, str], bool]:
    """
    创建关键字验证器

    Args:
        keywords: 需要匹配的关键字列表
        require_all: 是否需要匹配所有关键字
        context_window: 上下文窗口大小

    Returns:
        验证函数，签名为 (match_str: str, full_code: str) -> bool

    使用示例:
        validate = create_keyword_validator(['growthBook', 'GrowthBook'])
        if validate(match_str, full_code):
            print("Valid!")
    """
    validator = ContextValidator(context_window)

    def _validate(match_str: str, full_code: str) -> bool:
        result = validator.validate_by_keywords(full_code, match_str, keywords, require_all)
        return result.is_valid

    return _validate


def create_regex_validator(
    pattern: str,
    context_window: int = 500,
    flags: int = 0,
) -> Callable[[str, str], bool]:
    """
    创建正则验证器

    Args:
        pattern: 正则表达式模式
        context_window: 上下文窗口大小
        flags: 正则表达式标志

    Returns:
        验证函数，签名为 (match_str: str, full_code: str) -> bool

    使用示例:
        validate = create_regex_validator(r'growthBook|GrowthBook|FeatureValue')
        if validate(match_str, full_code):
            print("Valid!")
    """
    validator = ContextValidator(context_window)

    def _validate(match_str: str, full_code: str) -> bool:
        result = validator.validate_by_regex(full_code, match_str, pattern, flags)
        return result.is_valid

    return _validate


def create_structure_validator(
    expected_before: str | None = None,
    expected_after: str | None = None,
    max_distance: int = 200,
    context_window: int = 500,
) -> Callable[[str, str], bool]:
    """
    创建结构验证器

    Args:
        expected_before: 匹配前应该出现的字符串
        expected_after: 匹配后应该出现的字符串
        max_distance: 最大搜索距离
        context_window: 上下文窗口大小

    Returns:
        验证函数，签名为 (match_str: str, full_code: str) -> bool

    使用示例:
        validate = create_structure_validator(
            expected_before='function',
            expected_after='return',
        )
        if validate(match_str, full_code):
            print("Valid!")
    """
    validator = ContextValidator(context_window)

    def _validate(match_str: str, full_code: str) -> bool:
        result = validator.validate_by_structure(
            full_code, match_str, expected_before, expected_after, max_distance
        )
        return result.is_valid

    return _validate


def validate_match_context(
    code: str,
    match_str: str,
    keywords: list[str] | None = None,
    regex_pattern: str | None = None,
    expected_before: str | None = None,
    expected_after: str | None = None,
    context_window: int = 500,
) -> ValidationResult:
    """
    一站式验证函数

    Args:
        code: 完整代码
        match_str: 匹配的字符串
        keywords: 关键字列表（可选）
        regex_pattern: 正则表达式模式（可选）
        expected_before: 匹配前应该出现的字符串（可选）
        expected_after: 匹配后应该出现的字符串（可选）
        context_window: 上下文窗口大小

    Returns:
        ValidationResult 包含完整验证结果

    使用示例:
        result = validate_match_context(
            code=full_code,
            match_str=matched_string,
            keywords=['growthBook'],
            regex_pattern=r'FeatureValue|GrowthBook',
        )
        if result.is_valid:
            print(f"Valid! Context: {result.context}")
    """
    validator = ContextValidator(context_window)

    # 检查匹配是否存在
    if match_str not in code:
        return ValidationResult(
            is_valid=False,
            reason="Match string not found in code"
        )

    # 关键字验证
    if keywords:
        kw_result = validator.validate_by_keywords(code, match_str, keywords)
        if not kw_result.is_valid:
            return ValidationResult(
                is_valid=False,
                context=kw_result.context,
                reason=f"Keywords not found: {kw_result.reason}"
            )

    # 正则验证
    if regex_pattern:
        re_result = validator.validate_by_regex(code, match_str, regex_pattern)
        if not re_result.is_valid:
            return ValidationResult(
                is_valid=False,
                context=re_result.context,
                reason=f"Pattern not matched: {re_result.reason}"
            )

    # 结构验证
    if expected_before or expected_after:
        struct_result = validator.validate_by_structure(
            code, match_str, expected_before, expected_after
        )
        if not struct_result.is_valid:
            return ValidationResult(
                is_valid=False,
                context=struct_result.context,
                reason=f"Structure not matched: {struct_result.reason}"
            )

    return ValidationResult(
        is_valid=True,
        context=validator.get_context(code, match_str),
        reason="Context validated successfully"
    )
