"""Output Compressor — 借鉴 RTK 的 12 种过滤策略（重构版 - 模块化）

设计原则:
- 数据模型独立 (compressor_models.py)
- 策略处理函数独立 (compressor_strategies.py)
- 主引擎保持精简
- 向后兼容所有 API
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# 从拆分模块导入
# 向后兼容：从compressor_models重新导出
from .compressor_models import (
    DEFAULT_FILTER,
    FilterRule,
    FilterStrategy,
    MatchOutputRule,
    ReplaceRule,
    load_builtin_filters,
)
from .compressor_strategies import StrategyHandlers


def _load_builtin_filters() -> list[FilterRule]:
    """加载所有内置过滤器"""
    return load_builtin_filters()


# ---------------------------------------------------------------------------
# 压缩引擎
# ---------------------------------------------------------------------------

class OutputCompressor:
    """输出压缩引擎 — 借鉴 RTK 的过滤策略

    流水线阶段:
    1. strip_ansi           — 移除 ANSI 转义码
    2. replace              — 正则替换 (逐行)
    3. match_output         — 全文匹配短路 (命中则直接返回消息)
    4. strip/keep_lines     — 行过滤
    5. truncate_lines_at    — 每行长度限制
    6. head/tail_lines      — 头部/尾部保留
    7. max_lines            — 总行数限制
    8. on_empty             — 结果为空时的提示
    """

    def __init__(self) -> None:
        self._rules: list[FilterRule] = []
        self._handlers = StrategyHandlers()
        self.load_builtin_filters()

    def load_builtin_filters(self) -> None:
        """加载内置过滤器 (硬编码 + JSON 文件)"""
        self._rules = _load_builtin_filters()

        # 自动加载 src/core/filters/*.json
        try:
            filters_dir = Path(__file__).parent / 'filters'
            if filters_dir.exists():
                for json_file in filters_dir.glob('*.json'):
                    self.load_rules_from_file(json_file)
        except Exception as e:
            print(f"Error auto-loading filters: {e}")

    def add_rule(self, rule: FilterRule) -> None:
        """添加自定义过滤规则"""
        self._rules.insert(0, rule)  # 自定义规则优先

    def load_rules_from_file(self, path: Path | str) -> int:
        """从 JSON 文件加载规则 (增强版)"""
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            rules_data = data.get('rules', [])
            count = 0
            for rd in reversed(rules_data):
                try:
                    strategy = FilterStrategy(rd.get('strategy', 'identity'))

                    # 处理 match_output
                    match_output = [
                        MatchOutputRule(**m) if isinstance(m, dict) else m
                        for m in rd.get('match_output', [])
                    ]
                    # 处理 replace
                    replace = [
                        ReplaceRule(**r) if isinstance(r, dict) else r
                        for r in rd.get('replace', [])
                    ]

                    rule = FilterRule(
                        name=rd['name'],
                        command_pattern=rd['command_pattern'],
                        strategy=strategy,
                        description=rd.get('description', ''),
                        params=rd.get('params', {}),
                        strip_ansi=rd.get('strip_ansi', False),
                        replace=replace,
                        match_output=match_output,
                        strip_lines_matching=rd.get('strip_lines_matching', []),
                        keep_lines_matching=rd.get('keep_lines_matching', []),
                        truncate_lines_at=rd.get('truncate_lines_at'),
                        head_lines=rd.get('head_lines'),
                        tail_lines=rd.get('tail_lines'),
                        max_lines=rd.get('max_lines'),
                        on_empty=rd.get('on_empty'),
                    )
                    self._rules.insert(0, rule)
                    count += 1
                except (KeyError, ValueError) as e:
                    print(f"Error loading rule {rd.get('name')}: {e}")
                    continue
            return count
        except Exception as e:
            print(f"Error loading filters from {path}: {e}")
            return 0

    def match_rule(self, command: str) -> FilterRule:
        """根据命令匹配过滤规则"""
        for rule in self._rules:
            if re.search(rule.command_pattern, command):
                return rule
        return DEFAULT_FILTER

    def estimate_savings(self, command: str, output: str) -> dict[str, Any]:
        """估算压缩后的 token 节省量"""
        compressed = self.compress(command, output)
        return {
            'original_chars': len(output),
            'compressed_chars': len(compressed),
            'original_tokens': self._estimate_tokens(output),
            'compressed_tokens': self._estimate_tokens(compressed),
            'savings_pct': round(
                100.0 * (1 - len(compressed) / max(len(output), 1)), 1
            ),
            'strategy': self.match_rule(command).strategy.value,
        }

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """估算 token 数量"""
        return max(1, len(text) // 3)

    def compress(self, command: str, output: str) -> str:
        """压缩命令输出 (流水线版)"""
        if not output:
            return output

        rule = self.match_rule(command)

        # --- 兼容性检测: 如果定义了旧策略但没有新流水线，使用旧 handler ---
        any([
            rule.strip_ansi, rule.replace, rule.match_output,
            rule.strip_lines_matching, rule.keep_lines_matching,
            rule.truncate_lines_at, rule.head_lines, rule.tail_lines,
            rule.max_lines, rule.on_empty
        ])

        original_output = output

        try:
            # 1. strip_ansi
            if rule.strip_ansi:
                output = self._strip_ansi(output)

            # 2. replace (每行应用)
            if rule.replace:
                lines = output.split('\n')
                new_lines = []
                for line in lines:
                    for r in rule.replace:
                        line = re.sub(r.pattern, r.replacement, line)
                    new_lines.append(line)
                output = '\n'.join(new_lines)

            # 3. match_output (全量匹配短路)
            if rule.match_output:
                for mo in rule.match_output:
                    if re.search(mo.pattern, output):
                        if mo.unless and re.search(mo.unless, output):
                            continue
                        return mo.message

            # 3.5 Progress Bar Stripping (Ported from Project B)
            if rule.strategy != FilterStrategy.IDENTITY:
                output = self._strip_progress(output)

            # 4. 旧 handler 执行 (中间件模式)
            if rule.strategy != FilterStrategy.IDENTITY:
                handler = self._handlers.get(rule.strategy, self._identity)
                output = handler(output, rule.params)

            # 5. strip/keep lines
            if rule.strip_lines_matching or rule.keep_lines_matching:
                lines = output.split('\n')
                if rule.strip_lines_matching:
                    pattern = r'|'.join(f'(?:{p})' for p in rule.strip_lines_matching)
                    output = '\n'.join([l for l in lines if not re.search(pattern, l)])
                elif rule.keep_lines_matching:
                    pattern = r'|'.join(f'(?:{p})' for p in rule.keep_lines_matching)
                    output = '\n'.join([l for l in lines if re.search(pattern, l)])

            # 6. truncate_lines_at
            if rule.truncate_lines_at:
                lines = output.split('\n')
                output = '\n'.join([self._truncate_string(l, rule.truncate_lines_at) for l in lines])

            # 7. head/tail
            if rule.head_lines is not None or rule.tail_lines is not None:
                lines = output.split('\n')
                total = len(lines)
                head = rule.head_lines
                tail = rule.tail_lines

                if head is not None and tail is not None:
                    if total > head + tail:
                        output = '\n'.join([*lines[:head], f'... ({total - head - tail} lines omitted)', *lines[-tail:]])
                elif head is not None:
                    if total > head:
                        output = '\n'.join([*lines[:head], f'... ({total - head} lines omitted)'])
                elif tail is not None and total > tail:
                    output = '\n'.join([f'... ({total - tail} lines omitted)', *lines[-tail:]])

            # 8. max_lines
            if rule.max_lines is not None:
                lines = output.split('\n')
                if len(lines) > rule.max_lines:
                    output = '\n'.join([*lines[:rule.max_lines], f'... ({len(lines) - rule.max_lines} lines truncated)'])

            # 9. on_empty
            if not output.strip() and rule.on_empty:
                return rule.on_empty

        except Exception:
            # Fallback to original
            return original_output

        # 10. 保存完整输出到临时文件 (如果发生了显著截断) (借鉴 Project B)
        # 仅在启用 tee 模式且输出显著截断时执行
        from ..config.settings import get_settings
        settings = get_settings()

        is_significant = len(original_output) > 25000 and len(output) < len(original_output) * 0.5

        if settings.enable_tee_mode and is_significant:
            try:
                import tempfile
                import uuid

                from src.utils.file_ops import atomic_write

                tmp_dir = Path(tempfile.gettempdir()) / "claw_code_outputs"
                tmp_dir.mkdir(parents=True, exist_ok=True)

                safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', command[:30])
                file_name = f"{safe_name}_{uuid.uuid4().hex[:8]}.txt"
                full_path = tmp_dir / file_name

                atomic_write(full_path, original_output)

                # 在输出中追加提示
                header = (
                    f"\n\n---\n"
                    f"⚠️  Output was significantly truncated to save context.\n"
                    f"Full output saved to: {full_path}\n"
                    f"---\n"
                )
                output = header + output
            except Exception:
                # 即使保存失败，也不影响主流程
                pass

        return output

    # --- 委托给策略模块 ---

    @staticmethod
    def _strip_ansi(text: str) -> str:
        return StrategyHandlers.strip_ansi(text)

    @staticmethod
    def _strip_progress(text: str) -> str:
        return StrategyHandlers.strip_progress(text)

    @staticmethod
    def _truncate_string(s: str, max_width: int) -> str:
        return StrategyHandlers.truncate_string(s, max_width)

    def _truncate(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._truncate(output, params)

    def _error_only(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._error_only(output, params)

    def _stats_extraction(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._stats_extraction(output, params)

    def _grouping(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._grouping(output, params)

    def _deduplication(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._deduplication(output, params)

    def _structure_only(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._structure_only(output, params)

    def _code_filtering(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._code_filtering(output, params)

    def _failure_focus(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._failure_focus(output, params)

    def _tree_compression(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._tree_compression(output, params)

    def _progress_filter(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._progress_filter(output, params)

    def _dual_mode(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._dual_mode(output, params)

    def _state_machine(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._state_machine(output, params)

    def _identity(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._identity(output, params)

    def _group_errors_by_file(self, error_lines: list[str]) -> str:
        return self._handlers._group_errors_by_file(error_lines)

    def _git_status_summary(self, output: str) -> str:
        return self._handlers._git_status_summary(output)

    def _git_log_condensed(self, output: str, params: dict[str, Any]) -> str:
        return self._handlers._git_log_condensed(output, params)

    def _json_summary(self, data: Any) -> str:
        """JSON 摘要处理（向后兼容）"""
        if isinstance(data, dict):
            return json.dumps(data, indent=2, ensure_ascii=False) if len(data) <= 10 else f'{{... {len(data)} keys ...}}'
        elif isinstance(data, list):
            return json.dumps(data, indent=2, ensure_ascii=False) if len(data) <= 10 else f'[{len(data)} items]'
        return json.dumps(data, ensure_ascii=False)[:500]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """估算 token 数量"""
        return max(1, len(text) // 3)

