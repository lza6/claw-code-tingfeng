"""Output Compressor 策略处理函数

从 output_compressor.py 拆分出来
包含: 所有过滤策略的具体实现
"""
from __future__ import annotations

import re
from typing import Any


class StrategyHandlers:
    """策略处理函数集合"""

    @staticmethod
    def strip_ansi(text: str) -> str:
        """移除 ANSI 转义序列"""
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    @staticmethod
    def strip_progress(text: str) -> str:
        """移除进度条和正在进行的提示"""
        lines = text.split('\n')
        new_lines = []
        progress_chars = set('█░▒▓█')
        for line in lines:
            if line.strip() and sum(1 for c in line if c in progress_chars) / len(line) > 0.3:
                continue
            line = re.sub(r'\[[=#>-]+\] \d+%', '', line)
            line = re.sub(r'\d+%\s+.*\[.*\]', '', line)
            if line.strip():
                new_lines.append(line)
        return '\n'.join(new_lines)

    @staticmethod
    def truncate_string(s: str, max_width: int) -> str:
        """Unicode 安全截断"""
        if len(s) <= max_width:
            return s
        return s[:max_width-3] + "..."

    def _truncate(self, output: str, params: dict[str, Any]) -> str:
        """简单截断策略"""
        max_lines = params.get('max_lines', 500)
        max_chars = params.get('max_chars', 20000)

        lines = output.split('\n')
        if len(lines) > max_lines:
            keep_head = int(max_lines * 0.8)
            keep_tail = max_lines - keep_head
            output = '\n'.join([*lines[:keep_head], f'... [{len(lines) - max_lines} lines omitted] ...', *lines[-keep_tail:]])

        if len(output) > max_chars:
            output = output[:max_chars] + f'\n\n... [truncated, {len(output) - max_chars} chars omitted] ...'

        return output

    def _error_only(self, output: str, params: dict[str, Any]) -> str:
        """仅保留错误行策略"""
        lines = output.split('\n')
        error_patterns = [
            r'(?i)error\b', r'(?i)^fail', r'(?i)^warning\b',
            r'(?i)traceback', r'(?i)exception', r'(?i)failed\b',
            r'(?i)cannot\b', r'(?i)unable\b',
        ]
        error_lines = [
            line for line in lines
            if any(re.search(p, line) for p in error_patterns)
        ]

        if not error_lines:
            return '(no errors or warnings)'

        if params.get('group_by_file'):
            return self._group_errors_by_file(error_lines)

        return '\n'.join(error_lines)

    def _stats_extraction(self, output: str, params: dict[str, Any]) -> str:
        """统计提取策略"""
        fmt = params.get('format', 'generic')
        if fmt == 'git_status_summary':
            return self._git_status_summary(output)
        elif fmt == 'git_log_condensed':
            return self._git_log_condensed(output, params)
        lines = output.split('\n')
        stat_lines = [line for line in lines if re.search(r'\d+', line) and len(line) < 200]
        return '\n'.join(stat_lines[:params.get('max_lines', 20)]) or output[:500]

    def _grouping(self, output: str, params: dict[str, Any]) -> str:
        """按模式分组策略"""
        lines = output.split('\n')
        groups: dict[str, list[str]] = {}
        pattern = params.get('group_pattern', r'^(\w+)')
        for line in lines:
            m = re.match(pattern, line)
            key = m.group(1) if m else 'other'
            groups.setdefault(key, []).append(line)
        parts = []
        for key, group_lines in groups.items():
            parts.append(f'  [{key}] ({len(group_lines)} lines)')
            if len(group_lines) <= 3:
                parts.extend(f'    {l}' for l in group_lines)
            else:
                parts.append(f'    {group_lines[0]}')
                parts.append(f'    ... +{len(group_lines) - 1} more')
        return '\n'.join(parts)

    def _deduplication(self, output: str, params: dict[str, Any]) -> str:
        """去重策略: 移除连续重复行"""
        lines = output.split('\n')
        if not lines:
            return ""
        result = [lines[0]]
        skip_count = 0
        for line in lines[1:]:
            if line == result[-1]:
                skip_count += 1
            else:
                if skip_count > 0:
                    result.append(f'  [repeated {skip_count + 1} times]')
                    skip_count = 0
                result.append(line)
        if skip_count > 0:
            result.append(f'  [repeated {skip_count + 1} times]')
        return '\n'.join(result)

    def _structure_only(self, output: str, params: dict[str, Any]) -> str:
        """仅保留结构策略"""
        lines = output.split('\n')
        result = []
        for line in lines:
            if re.match(r'^[=\-#*]+', line):
                result.append(line[:100])
            elif line.strip() == '':
                result.append('')
            elif re.match(r'^(total|summary|stats|results|passed|failed)', line, re.IGNORECASE):
                result.append(line)
        return '\n'.join(result) if result else output[:500]

    def _code_filtering(self, output: str, params: dict[str, Any]) -> str:
        """代码过滤策略"""
        lines = output.split('\n')
        if params.get('format') == 'git_log_condensed':
            return self._git_log_condensed(output, params)
        return '\n'.join(lines[:params.get('max_lines', 50)])

    def _failure_focus(self, output: str, params: dict[str, Any]) -> str:
        """失败聚焦策略"""
        return self._error_only(output, params)

    def _tree_compression(self, output: str, params: dict[str, Any]) -> str:
        """树压缩策略"""
        max_depth = params.get('max_depth', 3)
        lines = output.split('\n')
        result = []
        for line in lines:
            depth = len(line) - len(line.lstrip())
            if depth // 4 <= max_depth:
                result.append(line)
        return '\n'.join(result) if result else output

    def _progress_filter(self, output: str, params: dict[str, Any]) -> str:
        """进度条过滤策略"""
        return self.strip_progress(output)

    def _dual_mode(self, output: str, params: dict[str, Any]) -> str:
        """JSON/文本双模式策略"""
        if output.strip().startswith('{'):
            return output  # JSON 保持原样
        return self._truncate(output, params)

    def _state_machine(self, output: str, params: dict[str, Any]) -> str:
        """状态机解析策略"""
        lines = output.split('\n')
        header = []
        body = []
        footer = []
        section = 'header'

        for line in lines:
            if line.startswith('---') or line.startswith('==='):
                if section == 'header':
                    section = 'body'
                elif section == 'body':
                    section = 'footer'
                continue

            if section == 'header':
                header.append(line)
            elif section == 'body':
                body.append(line)
            else:
                footer.append(line)

        result = []
        if header:
            result.append('[Header]')
            result.extend(header[:10])
        if body:
            result.append(f'[Body] ({len(body)} lines)')
            result.extend(body[:20])
        if footer:
            result.append('[Footer]')
            result.extend(footer[:5])

        return '\n'.join(result)

    def _identity(self, output: str, params: dict[str, Any]) -> str:
        """透传策略（不压缩）"""
        return output

    def _truncate(self, output: str, params: dict[str, Any]) -> str:
        """截断策略（包装静态方法）"""
        return StrategyHandlers._truncate_impl(output, params)

    @staticmethod
    def _truncate_impl(output: str, params: dict[str, Any]) -> str:
        max_lines = params.get('max_lines', 500)
        max_chars = params.get('max_chars', 20000)

        lines = output.split('\n')
        if len(lines) > max_lines:
            keep_head = int(max_lines * 0.8)
            keep_tail = max_lines - keep_head
            output = '\n'.join([*lines[:keep_head], f'... [{len(lines) - max_lines} lines omitted] ...', *lines[-keep_tail:]])

        if len(output) > max_chars:
            output = output[:max_chars] + f'\n\n... [truncated, {len(output) - max_chars} chars omitted] ...'

        return output

    def _group_errors_by_file(self, error_lines: list[str]) -> str:
        """按文件分组错误"""
        groups: dict[str, list[str]] = {}
        for line in error_lines:
            m = re.search(r'(\S+\.py):(\d+)', line)
            key = m.group(1) if m else 'unknown'
            groups.setdefault(key, []).append(line)

        parts = []
        for file, lines in groups.items():
            parts.append(f'\n{file}:')
            parts.extend(f'  {l}' for l in lines[:5])
            if len(lines) > 5:
                parts.append(f'  ... +{len(lines) - 5} more')

        return '\n'.join(parts)

    def _git_status_summary(self, output: str) -> str:
        """Git status 摘要"""
        branch_match = re.search(r'On branch (\S+)', output)
        branch = branch_match.group(1) if branch_match else 'unknown'

        changed_files = len(re.findall(r'^\s*(?:modified|new file|deleted):\s+', output, re.MULTILINE))

        if changed_files == 0:
            return f'ok (clean, branch: {branch})'
        return f'ok ({changed_files} files changed, branch: {branch})'

    def _git_log_condensed(self, output: str, params: dict[str, Any]) -> str:
        """Git log 压缩"""
        max_lines = params.get('max_lines', 30)
        lines = output.split('\n')
        result = []

        for line in lines:
            if re.match(r'^commit [0-9a-f]+', line):
                result.append(line[:14])
            elif re.match(r'^Author:', line):
                author = re.search(r'<([^>]+)>', line)
                if author:
                    result.append(f'  by {author.group(1)}')
            elif re.match(r'^Date:', line):
                result.append(f'  {line.strip()}')
            elif line.strip() and not line.startswith(' ') and not line.startswith(('commit', 'Author:', 'Date:')):
                # 捕获 commit 消息行
                result.append(f'    {line.strip()[:80]}')
            elif line.startswith('    ') and line.strip():
                # commit 消息（缩进格式）
                result.append(f'    {line.strip()[:80]}')

            if len(result) >= max_lines:
                break

        return '\n'.join(result)
