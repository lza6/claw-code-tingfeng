from __future__ import annotations

import logging
import re
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
            if p in self._backups:
                continue
            full_path = self.base_path / p
            if full_path.exists():
                try:
                    # 性能优化：对于频繁的小 Patch，如果已经在事务中且未改变，跳过读取
                    self._backups[p] = full_path.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning(f"备份文件失败 {p}: {e}")

    async def apply_batch(self, changes: list[AtomicChange]) -> list[PatchResult]:
        """批量应用变更，合并同一文件的多次修改以减少 I/O 次数"""
        from collections import defaultdict

        # 1. 事务保护
        paths = list({c.path for c in changes})
        await self.begin_transaction(paths)

        # 2. 按路径分组
        file_changes = defaultdict(list)
        for c in changes:
            file_changes[c.path].append(c)

        results = []
        try:
            for path, path_changes in file_changes.items():
                # 3. 内存中合并同一文件的所有 Patch
                full_path = self.base_path / path
                content = self._backups.get(path, "")

                current_lines = content.splitlines(keepends=True)

                for change in path_changes:
                    # 复用 apply_single_change 的逻辑，但在内存中操作
                    # 这里简化演示，实际实现中应将逻辑从 apply_single_change 提取到 _apply_to_lines
                    res = await self._apply_to_lines(path, current_lines, change)
                    if not res.success:
                        self.rollback()
                        return [res]

                # 4. 一次性写入
                new_content = "".join(current_lines)
                if new_content != content:
                    full_path.write_text(new_content, encoding="utf-8")

                results.append(PatchResult(success=True, path=path, applied_changes=len(path_changes)))

            self.commit()
            return results
        except Exception as e:
            self.rollback()
            raise e

    async def _apply_to_lines(self, path: Path, lines: list[str], change: AtomicChange) -> PatchResult:
        """内部辅助函数：在行列表上应用单个变更"""
        try:
            if change.op == PatchOperation.SEARCH_REPLACE:
                from ...tools_runtime.code_edit.fuzzy_matcher import replace_most_similar_chunk
                content = "".join(lines)
                if "=======" in change.content:
                    parts = change.content.split("=======")
                    search_part = parts[0].strip()
                    replace_part = parts[1].strip()
                else:
                    search_part = change.old_content or ""
                    replace_part = change.content

                new_content, match_type = replace_most_similar_chunk(content, search_part, replace_part)
                if not new_content:
                    return PatchResult(success=False, path=path, error_message=f"无法匹配搜索块 (match_type: {match_type})")

                # 更新 lines 原位
                lines[:] = new_content.splitlines(keepends=True)

            elif change.op == PatchOperation.INSERT:
                if change.line_start is not None:
                    lines.insert(change.line_start, change.content)
                else:
                    lines.append(change.content)

            elif change.op == PatchOperation.REPLACE:
                if change.line_start is not None and change.line_end is not None:
                    lines[change.line_start:change.line_end] = [change.content]

            elif change.op == PatchOperation.DELETE:
                if change.line_start is not None and change.line_end is not None:
                    del lines[change.line_start:change.line_end]

            return PatchResult(success=True, path=path)
        except Exception as e:
            return PatchResult(success=False, path=path, error_message=str(e))

    def commit(self) -> None:
        """提交事务：丢弃备份，使已写入的变更成为最终状态。

        与 rollback() 配对使用。调用后 _backups 清空，
        后续的 rollback() 将无从恢复（这是预期行为——事务已结束）。
        """
        self._backups.clear()

    def rollback(self) -> None:
        """回滚事务：把所有被备份的文件恢复到事务开始时的内容。

        只恢复 begin_transaction 记录过的文件。事务期间**新建**的文件
        不会被删除——删除用户文件的风险高于留下一个多余文件，且
        调用方可通过 PatchResult 感知失败。

        恢复失败的单个文件只记录警告，不中断其余文件的恢复：
        尽可能把系统还原到一致状态，比在第一个错误处停下更有价值。
        """
        for rel_path, original in self._backups.items():
            full_path = self.base_path / rel_path
            try:
                full_path.write_text(original, encoding="utf-8")
            except Exception as e:
                logger.error(f"回滚文件失败 {rel_path}: {e}")
        self._backups.clear()

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
            if use_transaction:
                self.rollback()
            raise e

    # ------------------------------------------------------------------
    # Unified diff 支持
    #
    # 说明: 这里的实现服务于自愈引擎的 apply_patch() 与 DIFF 操作。
    # 设计取舍是"宁可失败也不要写错" —— 上下文行不匹配时直接抛错，
    # 而不是尽力猜测位置，因为猜错会把文件改坏且难以察觉。
    # ------------------------------------------------------------------

    # @@ -oldStart[,oldCount] +newStart[,newCount] @@
    _DIFF_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    @staticmethod
    def _strip_diff_header(diff_lines: list[str]) -> list[str]:
        """去掉 `--- a/x` / `+++ b/x` / `diff --git` 等文件级头部"""
        out: list[str] = []
        for line in diff_lines:
            if line.startswith(("--- ", "+++ ", "diff --git ", "index ", "new file mode ", "deleted file mode ")):
                continue
            out.append(line)
        return out

    @classmethod
    def _parse_hunks(cls, diff_lines: list[str]) -> list[tuple[int, list[str]]]:
        """解析 unified diff 为 [(old_start_1based, hunk_body_lines), ...]"""
        hunks: list[tuple[int, list[str]]] = []
        current_start: int | None = None
        current_body: list[str] = []

        for raw in diff_lines:
            probe = raw.rstrip("\r\n")
            m = cls._DIFF_HUNK_RE.match(probe)
            if m:
                if current_start is not None:
                    hunks.append((current_start, current_body))
                current_start = int(m.group(1))
                current_body = []
                continue
            if current_start is None:
                continue  # 尚未进入任何 hunk
            if probe.startswith(("+", "-", " ")):
                current_body.append(raw)
            # "\ No newline at end of file" 之类的元信息直接忽略

        if current_start is not None:
            hunks.append((current_start, current_body))
        return hunks

    @classmethod
    def _apply_diff_hunks(cls, lines: list[str], diff_lines: list[str]) -> list[str]:
        """把 unified diff 应用到行列表，返回新的行列表。

        Args:
            lines: 目标文件内容，`splitlines(keepends=True)` 的结果
            diff_lines: unified diff 文本的行列表

        Raises:
            ValueError: hunk 头部缺失，或上下文/删除行在目标文件中匹配不上。
                抛出而非静默跳过，避免"补丁没生效但看起来成功"。
        """
        hunks = cls._parse_hunks(diff_lines)
        if not hunks:
            raise ValueError("diff 中未找到任何 @@ hunk 头部")

        result = list(lines)

        # 从后往前应用：前面的 hunk 不会影响后面 hunk 的行号
        for old_start, body in reversed(hunks):
            old_lines: list[str] = []
            new_lines: list[str] = []
            for raw in body:
                tag, text = raw[0], raw[1:]
                if tag == " ":
                    old_lines.append(text)
                    new_lines.append(text)
                elif tag == "-":
                    old_lines.append(text)
                else:  # '+'
                    new_lines.append(text)

            # 定位：先用 diff 声明的行号，不匹配则在其邻近双向搜索
            pos = cls._locate_hunk(result, old_lines, old_start - 1)
            if pos is None:
                preview = "".join(old_lines).strip()[:60].replace("\n", "\\n")
                raise ValueError(f"hunk @@ -{old_start} 的上下文在目标文件中找不到: {preview!r}")

            result[pos:pos + len(old_lines)] = new_lines

        return result

    @staticmethod
    def _locate_hunk(lines: list[str], old_lines: list[str], hint: int) -> int | None:
        """在 lines 中定位 old_lines 的起始下标。

        先试 diff 给出的 hint，再以 hint 为中心向两侧扩散搜索（真实场景中
        前面的 hunk 可能已改变行号偏移）；全部失败返回 None。
        """
        if not old_lines:
            # 纯插入 hunk：没有上下文可校验，只能信任 hint
            return max(0, min(hint, len(lines)))

        n = len(old_lines)
        max_start = len(lines) - n
        if max_start < 0:
            return None

        def matches(start: int) -> bool:
            if start < 0 or start > max_start:
                return False
            return all(
                lines[start + i].rstrip("\r\n") == old_lines[i].rstrip("\r\n")
                for i in range(n)
            )

        if matches(hint):
            return hint

        # 向两侧扩散：优先相信接近 hint 的位置
        for delta in range(1, len(lines) + 1):
            if matches(hint - delta):
                return hint - delta
            if matches(hint + delta):
                return hint + delta
        return None

    def apply_patch(self, file_path: str | Path, patch_content: str) -> bool:
        """把 unified diff 文本同步应用到文件，返回是否成功。

        提供给自愈引擎的同步入口（self_healing/engine.py 直接以
        `success = patcher.apply_patch(...)` 形式调用，不走 await）。

        安全保证:
            - 先算出完整新内容、通过 Python 语法校验后才落盘；
              任何一步失败都返回 False 且**不修改原文件**。
            - 不抛异常，错误通过日志与返回值暴露，便于上层回退到全量修复。
        """
        full_path = self.base_path / file_path
        if not full_path.exists():
            logger.warning(f"apply_patch: 文件不存在 {full_path}")
            return False

        try:
            original = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"apply_patch: 读取失败 {full_path}: {e}")
            return False

        try:
            diff_lines = self._strip_diff_header(patch_content.splitlines(keepends=True))
            new_lines = self._apply_diff_hunks(original.splitlines(keepends=True), diff_lines)
        except ValueError as e:
            logger.warning(f"apply_patch: 补丁无法应用 {full_path}: {e}")
            return False

        new_content = "".join(new_lines)

        if full_path.suffix == ".py":
            try:
                compile(new_content, str(full_path), "exec")
            except SyntaxError as e:
                logger.warning(f"apply_patch: 语法校验失败 {full_path}: {e}")
                return False

        try:
            full_path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            logger.error(f"apply_patch: 写入失败 {full_path}: {e}")
            return False

        return True

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
