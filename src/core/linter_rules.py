"""Linter 规则引擎 — 从 Aider linter.py 抽取的规则定义

本模块提供各语言 lint 命令的规则定义，与 Linter 类配合使用。
可扩展的语言包括：Python, JavaScript, TypeScript, Go, Rust, Ruby, PHP, Shell 等。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LinterRule:
    """Linter 规则定义

    属性:
        language: 语言名称（如 'python', 'javascript'）
        name: 规则名称
        command: lint 命令模板，使用 {fname} 作为文件名占位符
        fatal_only: 是否仅检查致命错误（不检查风格问题）
        timeout: 命令超时时间（秒）
    """
    language: str
    name: str
    command: str
    fatal_only: bool = True
    timeout: int = 30


# Python 规则
PYTHON_RULES: list[LinterRule] = [
    LinterRule(
        language='python',
        name='compile',
        command='python -m py_compile {fname}',
        fatal_only=False,
        timeout=10,
    ),
    LinterRule(
        language='python',
        name='flake8_fatal',
        command='python -m flake8 --select=E9,F821,F823,F831,F406,F407,F701,F702,F704,F706 --show-source --isolated {fname}',
        fatal_only=True,
        timeout=30,
    ),
    LinterRule(
        language='python',
        name='ruff',
        command='ruff check {fname}',
        fatal_only=False,
        timeout=30,
    ),
    LinterRule(
        language='python',
        name='pylint',
        command='pylint --errors-only {fname}',
        fatal_only=True,
        timeout=60,
    ),
]

# JavaScript/TypeScript 规则
JS_RULES: list[LinterRule] = [
    LinterRule(
        language='javascript',
        name='node_check',
        command='node --check {fname}',
        fatal_only=False,
        timeout=10,
    ),
    LinterRule(
        language='javascript',
        name='eslint',
        command='eslint --no-eslintrc --env es2021 --parser-options=ecmaVersion:2021 {fname}',
        fatal_only=True,
        timeout=30,
    ),
]

TS_RULES: list[LinterRule] = [
    LinterRule(
        language='typescript',
        name='tsc_noEmit',
        command='tsc --noEmit {fname}',
        fatal_only=False,
        timeout=30,
    ),
    LinterRule(
        language='typescript',
        name='eslint',
        command='eslint --no-eslintrc --env es2021 --parser-options=ecmaVersion:2021,sourceType:module {fname}',
        fatal_only=True,
        timeout=30,
    ),
]

# Go 规则
GO_RULES: list[LinterRule] = [
    LinterRule(
        language='go',
        name='gofmt',
        command='gofmt -e {fname}',
        fatal_only=False,
        timeout=10,
    ),
    LinterRule(
        language='go',
        name='go_vet',
        command='go vet {fname}',
        fatal_only=True,
        timeout=30,
    ),
]

# Rust 规则
RUST_RULES: list[LinterRule] = [
    LinterRule(
        language='rust',
        name='rustfmt_check',
        command='rustfmt --check {fname}',
        fatal_only=False,
        timeout=10,
    ),
    LinterRule(
        language='rust',
        name='clippy',
        command='clippy -- -D warnings {fname}',
        fatal_only=True,
        timeout=60,
    ),
]

# Ruby 规则
RUBY_RULES: list[LinterRule] = [
    LinterRule(
        language='ruby',
        name='ruby_check',
        command='ruby -c {fname}',
        fatal_only=False,
        timeout=10,
    ),
]

# PHP 规则
PHP_RULES: list[LinterRule] = [
    LinterRule(
        language='php',
        name='php_lint',
        command='php -l {fname}',
        fatal_only=False,
        timeout=10,
    ),
]

# Shell 规则
SHELL_RULES: list[LinterRule] = [
    LinterRule(
        language='shell',
        name='bash_n',
        command='bash -n {fname}',
        fatal_only=False,
        timeout=10,
    ),
    LinterRule(
        language='shell',
        name='shellcheck',
        command='shellcheck -S error {fname}',
        fatal_only=True,
        timeout=30,
    ),
]

# 所有规则汇总
ALL_RULES: dict[str, list[LinterRule]] = {
    'python': PYTHON_RULES,
    'javascript': JS_RULES,
    'typescript': TS_RULES,
    'go': GO_RULES,
    'rust': RUST_RULES,
    'ruby': RUBY_RULES,
    'php': PHP_RULES,
    'shell': SHELL_RULES,
}


def get_rules_for_language(lang: str) -> list[LinterRule]:
    """获取指定语言的所有规则

    参数:
        lang: 语言名称

    返回:
        LinterRule 列表
    """
    return ALL_RULES.get(lang, [])


def get_default_command(lang: str) -> str | None:
    """获取指定语言的默认 lint 命令

    参数:
        lang: 语言名称

    返回:
        命令模板字符串，或 None
    """
    rules = get_rules_for_language(lang)
    if rules:
        return rules[0].command
    return None


# 扩展语言映射
LANGUAGE_TO_LINTER: dict[str, str] = {
    'py': 'python',
    'js': 'javascript',
    'jsx': 'javascript',
    'ts': 'typescript',
    'tsx': 'typescript',
    'go': 'go',
    'rs': 'rust',
    'rb': 'ruby',
    'php': 'php',
    'sh': 'shell',
    'bash': 'shell',
    'zsh': 'shell',
}


__all__ = [
    'ALL_RULES',
    'GO_RULES',
    'JS_RULES',
    'LANGUAGE_TO_LINTER',
    'PHP_RULES',
    'PYTHON_RULES',
    'RUBY_RULES',
    'RUST_RULES',
    'SHELL_RULES',
    'TS_RULES',
    'LinterRule',
    'get_default_command',
    'get_rules_for_language',
]
