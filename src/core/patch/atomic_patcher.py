from __future__ import annotations

import logging
from pathlib import Path

from .models import AtomicChange, PatchOperation, PatchResult

# from ...rag.tree_sitter_syntax import parse_all  # 移除不存在的导入

logger = logging.getLogger(__name__)

class AtomicPatcher:
    """原子化补丁执行器

    负责将一系列 AtomicChange 应用到磁盘文件，
    并确保过程中的原子性与语法正确性。
    """

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or Path.cwd()
        self._backups: dict[Path, str] = {}  # 事务备份

    async def begin_transaction(self, paths: list[Path]) -> None:
        """开始事务，对受影响文件进行内存备份"""
        for p in paths:
            full_path = self.base_path / p
            if full_path.exists():
                self._backups[p] = full_path.read_text(encoding="utf-8")

    def rollback(self) -> None:
        """回滚所有已备份的文件"""
        for path, content in self._backups.items():
            (self.base_path / path).write_text(content, encoding="utf-8")
        self._backups.clear()

    def commit(self) -> None:
        """提交事务，清除备份"""
        self._backups.clear()

    def _apply_diff_hunks(self, lines: list[str], diff_lines: list[str]) -> list[str]:
        """应用统一 Diff 块 (简单实现)"""
        import difflib
        import re

        result = list(lines)
        # 这是一个极简实现，主要处理由 HeuristicToolParser 产生的 diff
        # 如果 diff 包含上下文，我们尝试匹配上下文
        # 如果是简单的 + / - 格式
        current_pos = 0
        hunk_header = re.compile(r'^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@')

        # 如果没有 hunk header，假设是全文替换或简单的逐行 diff
        if not any(hunk_header.match(l) for l in diff_lines):
            # 尝试使用 difflib.unified_diff 的逆向过程
            # 这里的 diff_lines 可能是原始 diff 格式
            # 为简单起见，如果是非结构化 diff，回退到 difflib
            return list(difflib.restore(diff_lines, 2)) # 1 为原始，2 为新

        # 处理带 @@ 的标准 diff
        # 注意: 这里的实现非常基础，生产环境应使用更完善的 patch 库
        # 鉴于 Aider 也有自己的 diff 应用逻辑，我们以后可以移植它
        return list(difflib.restore(diff_lines, 2))

    async def apply_changes(self, changes: list[AtomicChange], use_transaction: bool = True) -> list[PatchResult]:
        """按序应用多个原子变更"""
        if use_transaction:
            paths = list({c.path for c in changes})
            await self.begin_transaction(paths)

        results = []
        try:
            for change in changes:
                res = await self.apply_single_change(change)
                results.append(res)
                if not res.success:
                    if use_transaction:
                        self.rollback()
                        logger.error(f"事务回滚: {res.path} 失败 - {res.error_message}")
                    return results
            if use_transaction:
                self.commit()
            return results
        except Exception as e:
            if use_transaction: self.rollback()
            raise e

    async def apply_single_change(self, change: AtomicChange) -> PatchResult:
        """应用单个原子变更"""
        full_path = self.base_path / change.path
        if not full_path.exists() and change.op not in [PatchOperation.INSERT, PatchOperation.SEARCH_REPLACE]:
            return PatchResult(success=False, path=change.path, error_message="文件不存在")

        try:
            content = ""
            if full_path.exists():
                content = full_path.read_text(encoding="utf-8")

            # 处理 SEARCH_REPLACE 块 (借鉴 Aider)
            if change.op == PatchOperation.SEARCH_REPLACE:
                from ...tools_runtime.code_edit.fuzzy_matcher import replace_most_similar_chunk

                # 预处理：content 可能包含 SEARCH 和 REPLACE 的分界线
                # 这里假设 change.content 包含 SEARCH 块，change.old_content (如果有) 是 REPLACE 块
                # 或者 content 本身就是解析好的。
                # 按照 Aider 逻辑，如果 content 是 "SEARCH\n=======\nREPLACE" 格式
                if "=======" in change.content:
                    parts = change.content.split("=======")
                    search_part = parts[0].strip()
                    replace_part = parts[1].strip()
                else:
                    search_part = change.old_content or ""
                    replace_part = change.content

                new_content, match_type = replace_most_similar_chunk(content, search_part, replace_part)
                if not new_content:
                    return PatchResult(success=False, path=change.path, error_message=f"无法匹配搜索块 (match_type: {match_type})")

                # 更新 content 供后续校验
                new_lines = new_content.splitlines(keepends=True)
                lines = new_lines
            else:
                lines = content.splitlines(keepends=True)

                if change.op == PatchOperation.INSERT:
                    # 默认追加到末尾，或者在指定行插入
                    if change.line_start is not None:
                        lines.insert(change.line_start, change.content)
                    else:
                        lines.append(change.content)

                elif change.op == PatchOperation.REPLACE:
                    if change.line_start is None or change.line_end is None:
                        return PatchResult(success=False, path=change.path, error_message="REPLACE 操作缺少行号范围")
                    # 简单的行替换逻辑
                    lines[change.line_start:change.line_end] = [change.content]

                elif change.op == PatchOperation.DELETE:
                    if change.line_start is None or change.line_end is None:
                        return PatchResult(success=False, path=change.path, error_message="DELETE 操作缺少行号范围")
                    del lines[change.line_start:change.line_end]

                elif change.op == PatchOperation.DIFF:
                    # 使用 difflib 应用统一 diff 格式
                    diff_lines = change.content.splitlines(keepends=True)
                    # 移除可能存在的 diff 头部
                    if diff_lines and (diff_lines[0].startswith('---') or diff_lines[0].startswith('+++')):
                        diff_lines = diff_lines[2:]

                    # patch 逻辑实现 (简单实现: 尝试将 diff 应用到 content)
                    # 实际上标准库没有 patch 模块，我们手动实现一个简单的 hunk 应用
                    try:
                        new_lines = self._apply_diff_hunks(lines, diff_lines)
                        lines = new_lines
                    except Exception as e:
                        return PatchResult(success=False, path=change.path, error_message=f"Diff 应用失败: {e}")

            new_content = "".join(lines)

            # 语法校验 (可选)
            if full_path.suffix == ".py":
                try:
                    compile(new_content, str(full_path), "exec")
                except SyntaxError as e:
                    return PatchResult(success=False, path=change.path, error_message=f"语法错误: {e}")

            # 写入磁盘
            full_path.write_text(new_content, encoding="utf-8")
            return PatchResult(success=True, path=change.path, applied_changes=1)

        except Exception as e:
            return PatchResult(success=False, path=change.path, error_message=str(e))
