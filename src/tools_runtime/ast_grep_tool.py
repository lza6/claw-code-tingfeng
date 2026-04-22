"""AST Grep Tool - 基于 ast-grep (sg) 的结构化代码搜索工具
借鉴自 oh-my-codex-main (项目 B) 的优点。
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from .base import BaseTool, ParameterSchema, ToolResult

logger = logging.getLogger(__name__)

class ASTGrepTool(BaseTool):
    """基于 ast-grep 的结构化代码搜索工具"""

    name = 'ASTGrepTool'
    description = '使用 ast-grep (sg) 进行结构化代码搜索和模式匹配。相比正则搜索，它能更好地理解代码结构。'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='pattern',
            param_type='str',
            required=True,
            description='ast-grep 搜索模式（例如: "while ($A) { $$$ }"）',
        ),
        ParameterSchema(
            name='rewrite',
            param_type='str',
            required=False,
            description='用于重写的模式（可选，执行代码重构时使用）',
        ),
        ParameterSchema(
            name='lang',
            param_type='str',
            required=False,
            description='指定编程语言 (如: py, js, ts, go, rust)',
            default='py',
        ),
        ParameterSchema(
            name='selector',
            param_type='str',
            required=False,
            description='树搜索选择器（可选）',
        ),
    )

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or Path.cwd()

    def validate(self, **kwargs) -> tuple[bool, str]:
        if not kwargs.get('pattern'):
            return False, '必须提供 pattern'
        return True, ''

    def _find_sg_binary(self) -> str:
        """[汲取 Project B] 动态发现 ast-grep 二进制文件"""
        for bin_name in ['sg', 'ast-grep']:
            try:
                subprocess.run([bin_name, '--version'], capture_output=True, check=True)
                return bin_name
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue

        # 尝试使用 npx 回退
        try:
            subprocess.run(['npx', '--version'], capture_output=True, check=True)
            return "npx @ast-grep/cli"
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

        return 'sg' # 默认

    def execute(self, **kwargs) -> ToolResult:
        pattern = kwargs.get('pattern', '')
        rewrite = kwargs.get('rewrite')
        lang = kwargs.get('lang', 'py')
        selector = kwargs.get('selector')
        dry_run = kwargs.get('dry_run', True)

        sg_bin = self._find_sg_binary()

        # 基础命令构建
        if sg_bin.startswith("npx"):
            cmd = sg_bin.split() + ['run', '--pattern', pattern, '--lang', lang]
        else:
            cmd = [sg_bin, 'run', '--pattern', pattern, '--lang', lang]

        if rewrite:
            cmd.extend(['--rewrite', rewrite])
            if not dry_run:
                cmd.append('--update-all')
        else:
            cmd.append('--json')

        if selector:
            cmd.extend(['--selector', selector])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.base_path))

            if result.returncode != 0 and not result.stdout:
                return ToolResult(
                    success=False,
                    output='',
                    error=f'ast-grep 执行失败: {result.stderr}',
                    exit_code=result.returncode
                )

            if not result.stdout.strip():
                return ToolResult(success=True, output='未找到匹配内容')

            if rewrite and not dry_run:
                return ToolResult(success=True, output=f'重写操作已完成。{result.stdout}')

            try:
                matches = json.loads(result.stdout)
                if not isinstance(matches, list):
                    return ToolResult(success=True, output=result.stdout)

                output_lines = [f'找到 {len(matches)} 个匹配项:', '']
                for match in matches:
                    file_path = match.get('file', 'unknown')
                    range_info = match.get('range', {})
                    start = range_info.get('start', {})
                    line = start.get('line', 0) + 1
                    text = match.get('text', '').strip()
                    replacement = match.get('replacement', '')

                    line_summary = f'{file_path}:{line}: {text[:100]}...'
                    if replacement:
                        line_summary += f'\n   -> 建议重写为: {replacement[:100]}...'
                    output_lines.append(line_summary)

                return ToolResult(success=True, output='\n'.join(output_lines))
            except json.JSONDecodeError:
                return ToolResult(success=True, output=result.stdout)

        except Exception as e:
            return ToolResult(success=False, output='', error=f'发生未知错误: {e!s}', exit_code=1)
