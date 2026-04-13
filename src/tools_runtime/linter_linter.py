"""多策略代码检查器主类

从 Aider linter.py 增强移植，支持多语言语法错误检测。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from .linter_python import lint_python_compile
from .linter_tree_sitter import tree_sitter_lint
from .linter_types import LANGUAGE_EXTENSIONS, LintResult
from .linter_utils import (
    _find_linenums_in_output,
    _merge_lint_results,
    _merge_multiple_results,
)


class Linter:
    """多策略代码检查器

    支持多种语言的语法错误检测，通过以下策略:
    1. Python 文件使用内置 compile() 检查
    2. 其他语言通过配置外部 lint 命令检查
    3. 无法检查的文件返回空结果

    属性:
        root: 项目根目录路径
        linters: 语言到 lint 命令的映射字典
    """

    # 默认的 lint 命令模板
    DEFAULT_LINTERS: dict[str, str] = {
        'python': 'python -m py_compile {fname}',
        'javascript': 'node --check {fname}',
        'typescript': 'tsc --noEmit {fname}',
        'go': 'gofmt -e {fname}',
        'rust': 'rustfmt --check {fname}',
        'ruby': 'ruby -c {fname}',
        'php': 'php -l {fname}',
        'shell': 'bash -n {fname}',
    }

    def __init__(self, root: str | None = None) -> None:
        """初始化代码检查器

        参数:
            root: 项目根目录路径，用于解析相对路径
        """
        self.root = Path(root) if root else None
        self.linters: dict[str, str] = dict(self.DEFAULT_LINTERS)

    def set_linter(self, lang: str, cmd: str) -> None:
        """配置特定语言的 lint 命令

        参数:
            lang: 语言名称（如 'python', 'javascript'）
            cmd: lint 命令模板，使用 {fname} 作为文件名占位符

        示例:
            >>> linter = Linter()
            >>> linter.set_linter('python', 'ruff check {fname}')
        """
        self.linters[lang] = cmd

    def lint(self, fname: str, content: str | None = None) -> LintResult:
        """检查文件的语法错误

        主入口点：读取文件（或使用提供的内容），找到合适的
        lint 命令，执行检查并返回结果。

        参数:
            fname: 文件路径
            content: 可选的文件内容，如果提供则不读取文件

        返回:
            LintResult 对象，包含错误消息和受影响的行号
        """
        # 解析文件路径
        file_path = Path(fname)
        if not file_path.is_absolute() and self.root:
            file_path = self.root / file_path

        # 检查文件是否存在
        if not file_path.exists():
            return LintResult()

        # 获取文件扩展名和语言
        ext = file_path.suffix.lower()
        lang = LANGUAGE_EXTENSIONS.get(ext)

        # 读取文件内容（如果未提供）
        if content is None:
            try:
                content = file_path.read_text(encoding='utf-8', errors='replace')
            except (OSError, UnicodeDecodeError):
                return LintResult()

        # Python 文件使用三重检查
        if lang == 'python':
            return self._lint_python(str(file_path), content)

        # 其他语言：先尝试 tree-sitter AST 检查
        ts_result = tree_sitter_lint(fname, content)
        if ts_result:
            # 如果有外部 lint 命令，合并结果
            if lang and lang in self.linters:
                ext_result = self._run_external_linter(lang, str(file_path), content)
                return _merge_lint_results(ts_result, ext_result)
            return ts_result

        # 其他语言使用外部 lint 命令
        if lang and lang in self.linters:
            return self._run_external_linter(lang, str(file_path), content)

        # 无法检查的文件类型
        return LintResult()

    def _lint_python(self, fname: str, code: str) -> LintResult:
        """Python 三重检查: compile + tree-sitter + flake8"""
        results: list[LintResult] = []

        # 1. compile() 检查
        compile_result = lint_python_compile(code)
        if compile_result:
            results.append(compile_result)

        # 2. tree-sitter AST 检查
        ts_result = tree_sitter_lint(fname, code)
        if ts_result:
            results.append(ts_result)

        # 3. flake8 检查
        flake_result = self._flake8_lint(fname)
        if flake_result:
            results.append(flake_result)

        return _merge_multiple_results(results)

    def _flake8_lint(self, rel_fname: str) -> LintResult | None:
        """运行 flake8 检查 Python 文件（仅检查致命错误）

        参数:
            rel_fname: 相对于 root 的文件路径

        返回:
            LintResult 或 None
        """
        # 仅检查致命错误
        fatal = 'E9,F821,F823,F831,F406,F407,F701,F702,F704,F706'
        flake8_cmd = [
            sys.executable,
            '-m',
            'flake8',
            f'--select={fatal}',
            '--show-source',
            '--isolated',
            rel_fname,
        ]

        try:
            result = subprocess.run(
                flake8_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                cwd=str(self.root) if self.root else None,
            )
            errors = result.stdout + result.stderr
            if not errors:
                return None

            text = f'## Running: {" ".join(flake8_cmd)}\n\n{errors}'
            lines = _find_linenums_in_output(errors, [rel_fname])
            return LintResult(text=text, lines=lines)
        except (subprocess.SubprocessError, OSError, FileNotFoundError):
            return None

    def _run_external_linter(self, lang: str, fname: str, content: str) -> LintResult:
        """运行外部 lint 命令

        参数:
            lang: 语言名称
            fname: 文件路径
            content: 文件内容（用于某些需要 stdin 的 linter）

        返回:
            LintResult 对象
        """
        cmd_template = self.linters.get(lang)
        if not cmd_template:
            return LintResult()

        # 构建命令
        cmd = cmd_template.format(fname=fname)

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.root) if self.root else None,
            )

            # 合并 stdout 和 stderr
            output = result.stdout + result.stderr
            if not output.strip():
                return LintResult()

            # 解析错误消息和行号
            lines = self._extract_line_numbers(output, lang)
            return LintResult(text=output.strip(), lines=lines)

        except subprocess.TimeoutExpired:
            return LintResult(text='Lint 命令执行超时', lines=[])
        except (subprocess.SubprocessError, OSError):
            return LintResult()

    def _extract_line_numbers(self, output: str, lang: str) -> list[int]:
        """从 lint 输出中提取行号

        参数:
            output: lint 命令的输出
            lang: 语言名称

        返回:
            0-indexed 行号列表
        """
        lines: list[int] = []
        seen: set[int] = set()

        # 通用行号模式: line X, :X:, (line X), [X]
        patterns = [
            r'line[:\s]+(\d+)',      # line 42, line:42
            r':(\d+):',              # file.py:42:
            r'\((\d+)\)',            # (42)
            r'\[(\d+)\]',            # [42]
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, output, re.IGNORECASE):
                line_num = int(match.group(1)) - 1  # 转换为 0-indexed
                if line_num >= 0 and line_num not in seen:
                    lines.append(line_num)
                    seen.add(line_num)

        return lines

    # ===== Aider 风格自动修复 =====

    def lint_and_fix(self, fname: str) -> tuple[LintResult, bool]:
        """Lint 并尝试自动修复

        借鉴 Aider 的 linter.py 的 save 功能。
        仅支持特定的 linter（如 ruff, eslint --fix）。

        参数:
            fname: 文件路径

        返回:
            (LintResult, 是否成功修复) 元组
        """
        file_path = Path(fname)
        if not file_path.is_absolute() and self.root:
            file_path = self.root / file_path

        if not file_path.exists():
            return LintResult(), False

        ext = file_path.suffix.lower()
        lang = LANGUAGE_EXTENSIONS.get(ext)

        if not lang:
            return LintResult(), False

        # 先 lint
        lint_result = self.lint(fname)
        if not lint_result:
            return LintResult(), True  # 无错误，无需修复

        # 尝试自动修复
        fixed = self._auto_fix(lang, str(file_path))
        if fixed:
            # 重新 lint 确认
            lint_result = self.lint(fname)

        return lint_result, fixed

    def _auto_fix(self, lang: str, fname: str) -> bool:
        """尝试自动修复

        参数:
            lang: 语言名称
            fname: 文件路径

        返回:
            是否成功修复
        """
        # 支持自动修复的 linter 映射
        auto_fix_commands: dict[str, str] = {
            'python': 'ruff check {fname} --fix',
            'javascript': 'eslint {fname} --fix',
            'typescript': 'eslint {fname} --fix',
            'go': 'gofmt -w {fname}',
            'rust': 'rustfmt {fname}',
        }

        cmd_template = auto_fix_commands.get(lang)
        if not cmd_template:
            return False

        cmd = cmd_template.format(fname=fname)

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.root) if self.root else None,
            )
            return result.returncode == 0
        except Exception:
            return False


def basic_lint(fname: str, code: str) -> LintResult:
    """通用语法错误检测

    对 Python 文件使用 compile() 进行语法检查，
    对其他语言尝试 tree-sitter AST 检查。

    参数:
        fname: 文件名（用于判断文件类型）
        code: 文件内容

    返回:
        LintResult 对象，包含错误消息和行号
    """
    ext = Path(fname).suffix.lower()

    # Python 文件使用 compile 检查
    if ext == '.py':
        return lint_python_compile(code)

    # 其他语言尝试 tree-sitter
    return tree_sitter_lint(fname, code)


# 便捷函数
def lint_file(
    fname: str,
    content: str | None = None,
    root: str | None = None,
) -> LintResult:
    """检查单个文件的语法错误（便捷函数）

    参数:
        fname: 文��路径
        content: 可选的文件内容
        root: 项目根目录

    返回:
        LintResult 对象
    """
    linter = Linter(root=root)
    return linter.lint(fname, content=content)
