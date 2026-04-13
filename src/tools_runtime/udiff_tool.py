"""UnifiedDiffTool - 标准 Git Diff 格式编辑工具

支持 LLM 输出标准 unified diff 格式进行代码修改。

用法:
    tool = UnifiedDiffTool()
    result = tool.execute(diff_content=diff_text, target_file='path/to/file.py')

支持的 diff 格式:
    ```diff
    --- a/path/to/file.py
    +++ b/path/to/file.py
    @@ -10,5 +10,5 @@
     context line
    -old line
    +new line
     context line
    ```
"""
from __future__ import annotations

import logging
from pathlib import Path

from .base import BaseTool, ParameterSchema, ToolResult
from .path_utils import resolve_path
from .udiff_parser import (
    SearchTextNotUnique,
    apply_hunks,
    find_diffs,
    hunk_to_before_after,
)

logger = logging.getLogger(__name__)


class UnifiedDiffTool(BaseTool):
    """Unified Diff 编辑工具 — 从 Aider udiff_coder.py 移植

    功能:
    - 解析标准 unified diff 格式
    - 支持多文件多 hunk
    - 智能上下文裁剪（progressive context dropping）
    - SEARCH/REPLACE 策略回退
    """

    name = 'UnifiedDiffTool'
    description = '应用标准 unified diff 格式编辑文件。支持 git diff 输出格式。'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='diff_content',
            param_type='str',
            required=True,
            description='Unified diff 内容（```diff ... ``` 格式）',
            min_length=10,
            max_length=500000,
        ),
        ParameterSchema(
            name='target_file',
            param_type='str',
            required=False,
            description='目标文件路径（如果 diff 中未指定文件名）',
            max_length=500,
        ),
        ParameterSchema(
            name='dry_run',
            param_type='bool',
            required=False,
            description='仅预览，不实际写入',
            default=False,
        ),
    )

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or Path.cwd()

    def validate(self, **kwargs) -> tuple[bool, str]:
        diff_content = kwargs.get('diff_content', '')

        if not diff_content:
            return False, 'diff_content 不能为空'

        if '@@' not in diff_content:
            return False, 'diff_content 必须包含 @@ hunk 标记'

        return True, ''

    def execute(self, **kwargs) -> ToolResult:
        diff_content = kwargs.get('diff_content', '')
        target_file = kwargs.get('target_file', '')
        dry_run = kwargs.get('dry_run', False)

        is_valid, error_msg = self.validate(diff_content=diff_content)
        if not is_valid:
            return ToolResult(success=False, output='', error=error_msg, exit_code=1)

        # 解析 diff
        try:
            hunks = list(find_diffs(diff_content))
        except Exception as e:
            return ToolResult(
                success=False,
                output='',
                error=f'diff 解析失败: {e}',
                exit_code=1,
            )

        if not hunks:
            return ToolResult(
                success=False,
                output='',
                error='未找到有效的 diff hunk',
                exit_code=1,
            )

        # 按文件分组
        files_hunks: dict[str, list[tuple[str, list[str]]]] = {}
        for fname, hunk in hunks:
            actual_fname = fname or target_file
            if not actual_fname:
                return ToolResult(
                    success=False,
                    output='',
                    error='diff 未指定文件名且未提供 target_file',
                    exit_code=1,
                )
            if actual_fname not in files_hunks:
                files_hunks[actual_fname] = []
            files_hunks[actual_fname].append((fname or '', hunk))

        # 应用每个文件的 hunks
        results: list[str] = []
        errors: list[str] = []

        for fname, file_hunks in files_hunks.items():
            path = resolve_path(fname, self.base_path)
            if path is None:
                errors.append(f'路径遍历被拒绝: {fname}')
                continue

            if not path.is_relative_to(self.base_path.resolve()):
                errors.append(f'文件路径超出允许范围: {path}')
                continue

            if not path.exists():
                # 新文件 — 检查是否所有 hunk 都是新增
                before, _after = hunk_to_before_after(file_hunks[0][1])
                if before.strip():
                    errors.append(f'文件不存在且 diff 包含删除内容: {fname}')
                    continue
                content = ''
            else:
                content = path.read_text(encoding='utf-8', errors='replace')

            try:
                new_content = apply_hunks(content, file_hunks, fname)

                if dry_run:
                    results.append(f'[DRY-RUN] 将写入 {path} ({len(new_content)} 字符)')
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(new_content, encoding='utf-8')
                    results.append(f'已应用 {len(file_hunks)} 个 hunk 到 {path}')

            except SearchTextNotUnique as e:
                errors.append(f'{fname}: 搜索文本不唯一 — {e}')
            except ValueError as e:
                errors.append(f'{fname}: {e}')
            except Exception as e:
                errors.append(f'{fname}: 应用失败 — {e}')

        # 返回结果
        if errors:
            error_text = '\n'.join(errors)
            if results:
                return ToolResult(
                    success=False,
                    output='\n'.join(results) + f'\n\n部分失败:\n{error_text}',
                    error=error_text,
                    exit_code=1,
                )
            return ToolResult(success=False, output='', error=error_text, exit_code=1)

        return ToolResult(
            success=True,
            output='\n'.join(results),
            error='',
            exit_code=0,
        )
