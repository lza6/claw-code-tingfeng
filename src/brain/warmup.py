"""世界模型后台预热（自动触发，不阻塞主流程）

为什么需要它：
`RepositoryWorldModel.initialize()` 在大仓库上要跑几分钟。之前把它放在 MCP 工具调用里，
结果"一次调用要么挂死、要么超时报错"——体验极差。正确做法是**进程启动时后台预热**，
需要用时它基本已经就绪；没就绪时如实返回进度，而不是阻塞或假装成功。

用法（引擎启动时自动调用，也可显式）:
    from src.brain.warmup import ensure_warm, warm_status
    ensure_warm(workdir)          # 非阻塞，重复调用幂等
    warm_status(workdir)          # {"state": "indexing|ready|failed", ...}
"""

from __future__ import annotations

import asyncio
import threading
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class _WarmState:
    root: str
    state: str = "idle"  # idle | indexing | ready | failed
    started_at: float = 0.0
    finished_at: float = 0.0
    error: str = ""
    model: Any = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_STATES: dict[str, _WarmState] = {}
_GUARD = threading.Lock()

#: 超过该数量的源文件时默认不自动全量索引（实测 600 模块仓库 >4 分钟仍未完成，
#: 后台长时间占 CPU 得不偿失）。需要时可设 CLAWD_WM_FORCE=1 强制，或调大阈值。
DEFAULT_MAX_FILES = 300
_SOURCE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs"}
_SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".clawd"}


def _count_sources(root: Path, limit: int) -> int:
    """统计源文件数（超过 limit 即提前返回，避免自身变慢）"""
    n = 0
    try:
        for p in root.rglob("*"):
            if p.suffix in _SOURCE_EXTS and p.is_file() and not any(
                part in _SKIP_DIRS for part in p.parts
            ):
                n += 1
                if n > limit:
                    return n
    except OSError:
        pass
    return n


def _state_for(root: Path) -> _WarmState:
    key = str(root.resolve())
    with _GUARD:
        st = _STATES.get(key)
        if st is None:
            st = _WarmState(root=key)
            _STATES[key] = st
        return st


def _index(st: _WarmState) -> None:
    """后台线程：真正执行索引"""
    try:
        from .world_model import RepositoryWorldModel

        model = RepositoryWorldModel(Path(st.root))
        asyncio.run(model.initialize())
        with st.lock:
            st.model = model
            st.state = "ready"
            st.finished_at = time.time()
    except Exception as e:  # noqa: BLE001 — 预热失败只降级，不影响主流程
        with st.lock:
            st.state = "failed"
            st.error = f"{type(e).__name__}: {e}"
            st.finished_at = time.time()


def ensure_warm(root: Path | str, *, blocking: bool = False,
                max_files: int | None = None, force: bool | None = None) -> _WarmState:
    """确保世界模型开始（或已完成）预热

    Args:
        root: 仓库根
        blocking: True 时同步等待完成（测试/CLI 用）；默认非阻塞
        max_files: 源文件数上限，超过则跳过自动索引（默认 300，可用 CLAWD_WM_MAX_FILES 覆盖）
        force: True 强制索引；默认读环境变量 CLAWD_WM_FORCE

    Returns:
        当前预热状态对象；大仓库被跳过时为 state="skipped_large"
    """
    import os

    target = Path(root)
    st = _state_for(target)
    with st.lock:
        if st.state in ("ready", "indexing", "skipped_large"):
            already = True
        else:
            already = False
            st.state = "indexing"
            st.started_at = time.time()
            st.error = ""

    if already:
        if blocking and st.state == "indexing":
            deadline = time.time() + 600
            while st.state == "indexing" and time.time() < deadline:
                time.sleep(0.1)
        return st

    # 大仓库保护：默认不全量索引（实测 600 模块 >4 分钟未完），除非显式强制
    if force is None:
        force = os.environ.get("CLAWD_WM_FORCE", "").lower() in ("1", "true", "yes")
    if max_files is None:
        try:
            max_files = int(os.environ.get("CLAWD_WM_MAX_FILES", str(DEFAULT_MAX_FILES)))
        except ValueError:
            max_files = DEFAULT_MAX_FILES

    if not force:
        count = _count_sources(target, max_files)
        if count > max_files:
            with st.lock:
                st.state = "skipped_large"
                st.error = (
                    f"源文件 {count}+ 超过阈值 {max_files}，已跳过自动索引"
                    f"（全量索引会占用数分钟 CPU）。需要时设 CLAWD_WM_FORCE=1 或 "
                    f"CLAWD_WM_MAX_FILES=<更大值>；轻量替代：ProjectMapTool / 原生 grep"
                )
                st.finished_at = time.time()
            return st

    if blocking:
        _index(st)
    else:
        threading.Thread(target=_index, args=(st,), daemon=True,
                         name="clawd-wm-warmup").start()
    return st


def get_model(root: Path | str) -> Any | None:
    """已就绪则返回模型，否则 None（不触发索引）"""
    st = _state_for(Path(root))
    return st.model if st.state == "ready" else None


def is_ready(root: Path | str) -> bool:
    return _state_for(Path(root)).state == "ready"


def warm_status(root: Path | str) -> dict[str, Any]:
    """人类可读的预热状态（供工具/CLI/日志展示）"""
    st = _state_for(Path(root))
    elapsed = 0.0
    if st.started_at:
        end = st.finished_at or time.time()
        elapsed = round(end - st.started_at, 1)
    return {
        "state": st.state,
        "root": st.root,
        "elapsed_s": elapsed,
        "error": st.error,
        "indexed": st.state == "ready",
    }
