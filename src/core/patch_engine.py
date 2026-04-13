"""
ClawGod-style 声明式补丁引擎

灵感来源: ClawGod patch.js - 正则模式匹配的 AST-less 补丁系统

设计原则:
- 声明式补丁 DSL (领域特定语言)
- 补丁修饰符系统 (unique, optional, select_index, validate)
- 上下文指纹验证
- 多模式运行 (dry-run / verify / apply / revert)
- 非破坏性备份策略

使用示例:
    # 定义补丁
    patches = [
        PatchDefinition(
            name="optimize_system_prompt",
            pattern=r'function (\\w+)\\(\\)\\{return"external"\\}',
            replacer=lambda m, fn: f'function {fn}(){{return"ant"}}',
            unique=True,
        ),
    ]

    # 运行补丁引擎
    engine = PatchEngine(target_file="path/to/file.py")
    result = engine.apply_patches(patches, dry_run=False)
    print(f"Applied: {result.applied}, Skipped: {result.skipped}, Failed: {result.failed}")
"""

from __future__ import annotations

import inspect
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


@dataclass
class PatchResult:
    """补丁执行结果"""
    applied: int = 0
    skipped: int = 0
    failed: int = 0
    details: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0

    @property
    def total(self) -> int:
        return self.applied + self.skipped + self.failed

    def summary(self) -> str:
        return f"Result: {self.applied} applied, {self.skipped} skipped, {self.failed} failed"

    def __repr__(self) -> str:
        return f"PatchResult(applied={self.applied}, skipped={self.skipped}, failed={self.failed})"


@dataclass
class PatchDefinition:
    """
    声明式补丁定义

    属性:
        name: 补丁名称（用于日志和报告）
        pattern: 正则表达式模式
        replacer: 替换函数，签名为 (match: re.Match, *groups) -> str
        unique: 是否必须精确匹配 1 次（默认 False）
        optional: 是否可选补丁，某些版本可能不存在（默认 False）
        select_index: 选择第 N 个匹配（从 0 开始），None 表示全部匹配
        validate: 自定义验证函数，签名为 (match_str: str, full_code: str) -> bool
        description: 补丁描述（可选）
    """
    name: str
    pattern: str
    replacer: Callable[..., str]
    unique: bool = False
    optional: bool = False
    select_index: int | None = None
    validate: Callable[[str, str], bool] | None = None
    description: str = ""

    def compile_pattern(self) -> re.Pattern:
        """编译正则表达式"""
        return re.compile(self.pattern)


# 使用增强版 ContextValidator（从 utils 导入，消除重复）
from ..utils.context_validator import ContextValidator as _EnhancedContextValidator
from .telemetry import get_language, parse_code


# 向后兼容：创建一个简化版 wrapper，保持原有接口
class ContextValidator(_EnhancedContextValidator):
    """
    上下文指纹验证器 — 简化接口

    继承增强版 ContextValidator，提供向后兼容的简化方法。
    灵感来源: ClawGod 的 validate 函数
    """

    def validate_keywords(self, context: str, keywords: list[str]) -> bool:
        """向后兼容: 验证上下文中是否包含关键字"""
        return any(kw in context for kw in keywords)

    def validate_regex(self, context: str, pattern: str) -> bool:
        """向后兼容: 验证上下文是否匹配正则表达式"""
        import re as _re
        return bool(_re.search(pattern, context))


class PatchEngine:
    """
    声明式补丁引擎

    支持多模式运行:
    - dry_run: 只预览不写入
    - verify: 验证补丁是否已应用（不写入）
    - apply: 应用补丁
    - revert: 从备份还原
    """

    def __init__(
        self,
        target_file: str | Path,
        backup_suffix: str = ".bak",
        context_window: int = 500,
    ):
        """
        Args:
            target_file: 目标文件路径
            backup_suffix: 备份文件后缀
            context_window: 上下文窗口大小
        """
        self.target_file = Path(target_file)
        self.backup_file = Path(str(target_file) + backup_suffix)
        self.context_validator = ContextValidator(context_window)

    # ─── replacer 签名兼容层 ───────────────────────────────────

    @staticmethod
    @lru_cache(maxsize=64)
    def _replacer_accepts_groups(replacer: Callable) -> bool:
        """检查 replacer 是否接受捕获组参数。

        兼容两种签名: (m) 和 (m, *groups)。
        使用 lru_cache 避免对同一函数重复反射。
        """
        try:
            sig = inspect.signature(replacer)
            return len(sig.parameters) > 1
        except (ValueError, TypeError):
            return False  # 无法检查时假设不接受 groups

    @staticmethod
    def _apply_replacer(patch: PatchDefinition, match: re.Match) -> str:
        """调用 replacer，自动适配签名。"""
        groups = match.groups()
        if PatchEngine._replacer_accepts_groups(patch.replacer) and groups:
            return patch.replacer(match, *groups)
        return patch.replacer(match)

    def _read_code(self) -> str:
        """读取目标文件内容"""
        if not self.target_file.exists():
            raise FileNotFoundError(f"Target file not found: {self.target_file}")
        return self.target_file.read_text(encoding="utf-8")

    def _write_code(self, code: str) -> None:
        """写入目标文件内容"""
        self.target_file.write_text(code, encoding="utf-8")

    def _create_backup(self) -> None:
        """创建备份文件"""
        if not self.backup_file.exists():
            shutil.copy2(self.target_file, self.backup_file)

    def _revert_from_backup(self) -> str:
        """从备份还原"""
        if not self.backup_file.exists():
            raise FileNotFoundError(f"No backup found: {self.backup_file}")
        return self.backup_file.read_text(encoding="utf-8")

    def _process_patch(
        self,
        patch: PatchDefinition,
        code: str,
        dry_run: bool = False,
        verify: bool = False,
    ) -> tuple[str, str, bool]:
        """
        处理单个补丁

        Returns:
            (status_message, new_code, success)
        """
        pattern = patch.compile_pattern()
        matches = list(pattern.finditer(code))

        if not matches:
            if patch.optional:
                return (f"  ⏭  {patch.name} (not present in this version)", code, True)
            else:
                return (f"  ✅ {patch.name} (already applied)", code, True)

        # 应用自定义验证
        if patch.validate:
            relevant = [m for m in matches if patch.validate(m.group(), code)]
        else:
            relevant = matches

        # 选择特定索引的匹配
        if patch.select_index is not None:
            if patch.select_index < len(relevant):
                relevant = [relevant[patch.select_index]]
            else:
                relevant = []

        # 唯一性检查
        if patch.unique and len(relevant) != 1:
            if verify:
                return (f"  ❓ {patch.name} — {len(relevant)} matches (need exactly 1)", code, False)
            else:
                return (f"  ⚠️  {patch.name} — {len(relevant)} matches, skipping (need 1)", code, False)

        if not relevant:
            if patch.optional:
                return (f"  ⏭  {patch.name} (not present in this version)", code, True)
            else:
                return (f"  ✅ {patch.name} (already applied)", code, True)

        if verify:
            return (f"  ⬚  {patch.name} — {len(relevant)} match(es), not yet applied", code, True)

        # 应用补丁
        count = 0
        new_code = code
        for m in relevant:
            replacement = self._apply_replacer(patch, m)
            if replacement != m.group():
                if not dry_run:
                    new_code = new_code.replace(m.group(), replacement, 1)
                count += 1

        if count > 0:
            replacement_word = "replacement" if count == 1 else "replacements"
            return (f"  ✅ {patch.name} ({count} {replacement_word})", new_code, True)
        else:
            return (f"  ⏭  {patch.name} (no change needed)", code, True)

    def apply_patches(
        self,
        patches: list[PatchDefinition],
        dry_run: bool = False,
        verify: bool = False,
        revert: bool = False,
        validate_syntax: bool = True,
    ) -> PatchResult:
        """
        应用补丁列表

        Args:
            patches: 补丁定义列表
            dry_run: 只预览不写入
            verify: 验证模式（不写入）
            revert: 还原模式（从备份还原）
            validate_syntax: 是否进行语法校验（默认 True）

        Returns:
            PatchResult 包含执行结果统计
        """
        result = PatchResult()

        # 还原模式
        if revert:
            try:
                original_code = self._revert_from_backup()
                if not dry_run:
                    self._write_code(original_code)
                result.details.append(f"  ✅ Reverted from backup ({self.backup_file})")
                result.applied = 1
            except FileNotFoundError as e:
                result.details.append(f"  ❌ {e}")
                result.failed = 1
            return result

        # 读取代码
        code = self._read_code()
        orig_size = len(code)

        # 提取版本信息（如果存在）
        version = "unknown"
        ver_match = re.search(r'Version:\s*([\d.]+)', code)
        if ver_match:
            version = ver_match.group(1)

        # 打印头部
        result.details.append("")
        result.details.append(f"{'═' * 55}")
        result.details.append("  ClawGod Patch Engine (Python Port)")
        result.details.append(f"  Target: {self.target_file.name} (v{version})")
        mode_str = "DRY RUN" if dry_run else "VERIFY" if verify else "APPLY"
        result.details.append(f"  Mode: {mode_str}")
        result.details.append(f"{'═' * 55}")
        result.details.append("")

        # 处理每个补丁
        new_code = code
        for patch in patches:
            status_msg, new_code, success = self._process_patch(
                patch, new_code, dry_run=dry_run, verify=verify
            )
            result.details.append(status_msg)

            if success:
                if "already applied" in status_msg:
                    # 与 ClawGod 一致：already applied 计为 applied（幂等安装）
                    result.applied += 1
                elif "not present" in status_msg or "no change" in status_msg:
                    result.skipped += 1
                else:
                    result.applied += 1
            else:
                result.failed += 1

        # 语法校验
        if not dry_run and not verify and result.applied > 0 and validate_syntax:
            language = get_language(str(self.target_file))
            if language:
                tree = parse_code(new_code, language)
                if tree is None or (hasattr(tree.tree, "root_node") and tree.tree.root_node.has_error):
                    result.details.append("  ❌ Syntax Error detected! Rolling back.")
                    result.failed = result.applied
                    result.applied = 0
                    return result

        # 打印结果
        result.details.append("")
        result.details.append(f"{'─' * 55}")
        result.details.append(result.summary())

        # 写入文件
        if not dry_run and not verify and result.applied > 0:
            self._create_backup()
            self._write_code(new_code)
            diff = len(new_code) - orig_size
            diff_str = f"+{diff}" if diff >= 0 else str(diff)
            result.details.append(f"  📝 Written: {self.target_file.name} ({diff_str} bytes)")
            result.details.append(f"  📦 Backup: {self.backup_file}")

        result.details.append(f"{'═' * 55}")
        result.details.append("")

        return result

    def verify_patches(
        self,
        patches: list[PatchDefinition],
    ) -> PatchResult:
        """验证补丁是否已应用"""
        return self.apply_patches(patches, verify=True)

    def dry_run_patches(
        self,
        patches: list[PatchDefinition],
    ) -> PatchResult:
        """预览补丁效果（不写入）"""
        return self.apply_patches(patches, dry_run=True)

    def revert_patches(self) -> PatchResult:
        """还原所有补丁（从备份）"""
        return self.apply_patches([], revert=True)

    @staticmethod
    def apply_string(
        patches: list[PatchDefinition],
        code: str,
        dry_run: bool = False,
    ) -> tuple[str, PatchResult]:
        """内存模式：直接对字符串应用补丁，不涉及文件 I/O。

        灵感来源: ClawGod 的 patch.js 可对任意文本执行正则替换，
        无需依赖文件系统。本方法为 PromptOptimizer 等内存场景提供
        高效的补丁执行路径。

        Args:
            patches: 补丁定义列表
            code: 待处理的文本
            dry_run: 只预览不修改

        Returns:
            (处理后的文本, PatchResult)
        """
        if not patches:
            return code, PatchResult()

        result = PatchResult()
        new_code = code

        for patch in patches:
            pattern = patch.compile_pattern()
            matches = list(pattern.finditer(new_code))

            if not matches:
                if patch.optional:
                    result.details.append(f"  ⏭  {patch.name} (not present)")
                    result.skipped += 1
                else:
                    result.details.append(f"  ✅ {patch.name} (already applied)")
                    result.applied += 1
                continue

            # 应用自定义验证
            if patch.validate:
                relevant = [m for m in matches if patch.validate(m.group(), new_code)]
            else:
                relevant = matches

            if patch.select_index is not None:
                if patch.select_index < len(relevant):
                    relevant = [relevant[patch.select_index]]
                else:
                    relevant = []

            if patch.unique and len(relevant) != 1:
                result.details.append(
                    f"  ⚠️  {patch.name} — {len(relevant)} matches, skipping (need 1)"
                )
                result.failed += 1
                continue

            if not relevant:
                if patch.optional:
                    result.details.append(f"  ⏭  {patch.name} (not present)")
                    result.skipped += 1
                else:
                    result.details.append(f"  ✅ {patch.name} (already applied)")
                    result.applied += 1
                continue

            count = 0
            for m in relevant:
                replacement = PatchEngine._apply_replacer(patch, m)
                if replacement != m.group():
                    if not dry_run:
                        new_code = new_code.replace(m.group(), replacement, 1)
                    count += 1

            if count > 0:
                word = "replacement" if count == 1 else "replacements"
                result.details.append(f"  ✅ {patch.name} ({count} {word})")
                result.applied += 1
            else:
                result.details.append(f"  ⏭  {patch.name} (no change needed)")
                result.skipped += 1

        return new_code, result


# ─── 便捷函数 ─────────────────────────────────────────────────────────

def create_patch(
    name: str,
    pattern: str,
    replacer: Callable[..., str],
    unique: bool = False,
    optional: bool = False,
    select_index: int | None = None,
    validate: Callable[[str, str], bool] | None = None,
    description: str = "",
) -> PatchDefinition:
    """
    便捷函数：创建补丁定义

    使用示例:
        patch = create_patch(
            name="optimize_prompt",
            pattern=r'function (\\w+)\\(\\)',
            replacer=lambda m, fn: f'function {fn}_optimized()',
            unique=True,
        )
    """
    return PatchDefinition(
        name=name,
        pattern=pattern,
        replacer=replacer,
        unique=unique,
        optional=optional,
        select_index=select_index,
        validate=validate,
        description=description,
    )


def validate_context_keywords(keywords: list[str], context_window: int = 500) -> Callable[[str, str], bool]:
    """
    创建上下文关键字验证器

    使用示例:
        patch = create_patch(
            name="growthbook_override",
            pattern=r'function (\\w+)\\(\\)',
            replacer=...,
            validate=validate_context_keywords(['growthBook', 'GrowthBook']),
        )
    """
    validator = ContextValidator(context_window)

    def _validate(match_str: str, full_code: str) -> bool:
        pos = full_code.find(match_str)
        if pos == -1:
            return False
        context = validator.get_context(full_code, pos)
        return validator.validate_keywords(context, keywords)

    return _validate


def validate_context_regex(pattern: str, context_window: int = 500) -> Callable[[str, str], bool]:
    """
    创建上下文正则验证器

    使用示例:
        patch = create_patch(
            name="growthbook_override",
            pattern=r'function (\\w+)\\(\\)',
            replacer=...,
            validate=validate_context_regex(r'growthBook|GrowthBook'),
        )
    """
    validator = ContextValidator(context_window)

    def _validate(match_str: str, full_code: str) -> bool:
        pos = full_code.find(match_str)
        if pos == -1:
            return False
        context = validator.get_context(full_code, pos)
        return validator.validate_regex(context, pattern)

    return _validate
