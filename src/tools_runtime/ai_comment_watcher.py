"""AI Comment Watcher — 代码中的 AI 指令检测

借鉴 Aider 的 watch.py，检测代码文件中的 AI 注释:
- `# ai!` 或 `# AI!` → 触发代码修改请求
- `# ai?` 或 `# AI?` → 触发问题询问

支持多种语言的注释语法:
- Python: #
- JavaScript/C/Java: //
- SQL: --
- Lisp: ;

使用:
    watcher = AICommentWatcher(workdir)
    watcher.start()
    # ... 用户编辑代码 ...
    comments = watcher.get_pending_comments()
    watcher.stop()
"""
from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


@dataclass
class AIComment:
    """检测到的 AI 注释"""
    file_path: Path
    line_number: int
    content: str  # 注释内容 (去除 "ai" 部分)
    action: str  # "modify" (!) 或 "ask" (?)
    code_context: str = ""  # 注释周围的代码上下文


class AICommentWatcher:
    """AI 注释检测器

    功能:
        - 监控文件变化，检测 AI 注释
        - 提取注释上下文用于 LLM 输入
        - 线程安全的事件通知
    """

    # AI 注释正则 (借鉴 Aider)
    AI_COMMENT_PATTERN = re.compile(
        r'(?:#|//|--|;+)\s*(ai\b.*|.*\bai[?!]?)\s*$',
        re.IGNORECASE
    )

    # 支持的文件扩展名
    SUPPORTED_EXTENSIONS: ClassVar[set[str]] = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h',
        '.go', '.rs', '.rb', '.php', '.sql', '.lisp', '.el', '.clj',
        '.scala', '.kt', '.swift', '.m', '.sh', '.bash', '.zsh',
    }

    def __init__(
        self,
        workdir: Path | str,
        on_comments_detected: Callable[[list[AIComment]], None] | None = None,
        max_file_size_mb: float = 1.0,
    ) -> None:
        """初始化 AI 注释检测器

        Args:
            workdir: 工作目录
            on_comments_detected: 检测到注释时的回调
            max_file_size_mb: 最大文件大小 (MB)
        """
        self.workdir = Path(workdir)
        self.on_comments_detected = on_comments_detected
        self.max_file_size_mb = max_file_size_mb

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending_comments: list[AIComment] = []
        self._lock = threading.Lock()
        self._watcher: Any = None

    def is_supported_file(self, path: Path) -> bool:
        """检查文件是否受支持"""
        return (
            path.suffix.lower() in self.SUPPORTED_EXTENSIONS
            and path.stat().st_size < self.max_file_size_mb * 1024 * 1024
        )

    def extract_comments(self, file_path: Path) -> list[AIComment]:
        """从文件中提取 AI 注释"""
        comments = []

        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            lines = content.split('\n')

            for i, line in enumerate(lines, start=1):
                match = self.AI_COMMENT_PATTERN.search(line)
                if match:
                    comment_text = match.group(1).strip()

                    # 判断操作类型
                    if comment_text.endswith('!'):
                        action = "modify"
                        comment_text = comment_text[:-1].strip()
                    elif comment_text.endswith('?'):
                        action = "ask"
                        comment_text = comment_text[:-1].strip()
                    else:
                        action = "modify"  # 默认修改

                    # 提取上下文 (前后各 3 行)
                    start_line = max(0, i - 4)
                    end_line = min(len(lines), i + 3)
                    context = '\n'.join(lines[start_line:end_line])

                    comments.append(AIComment(
                        file_path=file_path,
                        line_number=i,
                        content=comment_text,
                        action=action,
                        code_context=context,
                    ))

        except Exception as e:
            logger.debug(f'提取 AI 注释失败 {file_path}: {e}')

        return comments

    def scan_directory(self) -> list[AIComment]:
        """扫描目录中所有文件的 AI 注释"""
        all_comments = []

        for path in self.workdir.rglob('*'):
            if not path.is_file():
                continue
            if not self.is_supported_file(path):
                continue
            # 跳过 .git, node_modules 等
            if any(part.startswith('.') or part == 'node_modules' for part in path.parts):
                continue

            comments = self.extract_comments(path)
            all_comments.extend(comments)

        return all_comments

    def start(self) -> None:
        """开始监控文件变化"""
        if self._thread is not None:
            return

        self._stop_event.clear()

        try:
            from watchfiles import watch

            def _watch_loop():
                try:
                    for changes in watch(
                        str(self.workdir),
                        stop_event=self._stop_event,
                        watch_filter=self._filter_change,
                    ):
                        self._handle_changes(changes)
                except Exception as e:
                    logger.debug(f'Watch 循环结束: {e}')

            self._thread = threading.Thread(
                target=_watch_loop,
                daemon=True,
                name='ai-comment-watcher',
            )
            self._thread.start()
            logger.info('[AIWatcher] 开始监控 AI 注释')

        except ImportError:
            logger.warning('[AIWatcher] watchfiles 未安装，回退到手动扫描')
            # 回退：初始扫描一次
            comments = self.scan_directory()
            if comments:
                with self._lock:
                    self._pending_comments.extend(comments)
                if self.on_comments_detected:
                    self.on_comments_detected(comments)

    def stop(self) -> None:
        """停止监控"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info('[AIWatcher] 停止监控')

    def _filter_change(self, change_type: Any, path: str) -> bool:
        """过滤文件变化事件"""
        path_obj = Path(path)
        return (
            change_type.name in ('added', 'modified')
            and self.is_supported_file(path_obj)
        )

    def _handle_changes(self, changes: set) -> None:
        """处理文件变化"""
        new_comments = []

        for _change_type, path_str in changes:
            path = Path(path_str)
            comments = self.extract_comments(path)
            new_comments.extend(comments)

        if new_comments:
            with self._lock:
                self._pending_comments.extend(new_comments)
            logger.info(f'[AIWatcher] 检测到 {len(new_comments)} 个 AI 注释')

            if self.on_comments_detected:
                self.on_comments_detected(new_comments)

    def get_pending_comments(self) -> list[AIComment]:
        """获取待处理的 AI 注释 (并清空队列)"""
        with self._lock:
            comments = self._pending_comments.copy()
            self._pending_comments.clear()
        return comments

    def has_pending(self) -> bool:
        """检查是否有待处理的注释"""
        with self._lock:
            return len(self._pending_comments) > 0


def format_comments_for_llm(comments: list[AIComment]) -> str:
    """格式化 AI 注释为 LLM 输入

    Args:
        comments: AI 注释列表

    Returns:
        格式化的提示文本
    """
    if not comments:
        return ""

    parts = ["检测到代码中的 AI 指令:\n"]

    for i, comment in enumerate(comments, 1):
        action_text = "修改代码" if comment.action == "modify" else "回答问题"
        parts.append(f"## 指令 {i}: {action_text}\n")
        parts.append(f"文件: {comment.file_path.relative_to(comment.file_path.anchor)}\n")
        parts.append(f"行号: {comment.line_number}\n")
        parts.append(f"内容: {comment.content}\n")
        parts.append(f"\n代码上下文:\n```\n{comment.code_context}\n```\n\n")

    return '\n'.join(parts)
