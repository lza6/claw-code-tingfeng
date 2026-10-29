"""原生引擎后端 —— 把我们自己的 agent 接进统一驱动层

为什么需要：多引擎协同里 planner/executor/reviewer 应当可以任选引擎，
包括**我们自己的 agent**（不依赖外部 CLI 就能跑，也是默认选择）。

注意：它复用 AgentEngine（含 19 个工具、LSP、世界模型、权限门禁、挂机自决），
不是另起一套循环。
"""

from __future__ import annotations

import asyncio
import time

from pathlib import Path
from typing import Any

from .base import BackendResult, BackendUnavailable


class NativeBackend:
    """用本项目 AgentEngine 充当引擎"""

    name = "native"

    def __init__(
        self,
        workdir: Path | str = ".",
        max_iterations: int = 10,
        *,
        engine: Any = None,
    ):
        self.workdir = Path(workdir)
        self.max_iterations = max_iterations
        self._engine = engine

    # ---------- 探活 ----------
    def probe(self):
        from .base import EngineProbe

        return EngineProbe(name="native", status="ready", version="builtin", detail="内置引擎")

    def available(self) -> bool:
        return True

    def version(self) -> str:
        try:
            from .. import __version__

            return f"clawd {__version__}"
        except Exception:  # noqa: BLE001
            return "clawd"

    # ---------- 执行 ----------
    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from ..agent.factory import create_agent_engine

            self._engine = create_agent_engine(
                workdir=self.workdir, max_iterations=self.max_iterations
            )
            return self._engine
        except Exception as e:  # noqa: BLE001
            raise BackendUnavailable(f"原生引擎不可用: {e}") from e

    @staticmethod
    def _run_coro(coro: Any) -> Any:
        """在同步上下文里跑协程；**若已有事件循环则改用线程**跑

        陷阱（本项目 skill 记录）：同步函数里 `asyncio.run(...)` 在已有事件循环中会
        抛 `RuntimeError: asyncio.run() cannot be called from a running event loop`。
        collaborate 目前从 CLI（同步）调用，但库调用方可能在 async 上下文里用它。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)  # 无运行中的 loop，正常路径

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

    def run(self, goal: str, timeout: float = 900.0) -> BackendResult:
        """执行一次原生 agent 任务

        `timeout` 是**真实生效**的墙钟上限（不是装饰参数）：协程在线程池里跑，
        超时即放弃等待并返回 `timed_out=True`。
        诚实限制：Python 无法强杀线程，超时后协程线程可能仍在后台收尾
        （LLM 请求结束后自然退出）；调用方据此判定失败即可。
        """
        if not goal or not goal.strip():
            raise BackendUnavailable("goal 不能为空")
        if timeout is not None and timeout <= 0:
            raise BackendUnavailable("timeout 必须为正数")

        engine = self._get_engine()
        started = time.perf_counter()

        import concurrent.futures

        def _invoke() -> Any:
            # 协程在目标线程里创建：若提前取消，不会留下 "never awaited" 协程
            return self._run_coro(engine.run(goal))

        pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="clawd-native"
        )
        try:
            future = pool.submit(_invoke)
            try:
                session = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                return BackendResult(
                    engine="native",
                    text="",
                    errors=[f"执行超时（{timeout:g}s）：已放弃等待原生引擎"],
                    exit_code=1,
                    duration_s=time.perf_counter() - started,
                    timed_out=True,
                )
            except Exception as e:  # noqa: BLE001 — 统一转成 BackendResult 的错误
                return BackendResult(
                    engine="native", text="", errors=[f"{type(e).__name__}: {e}"],
                    exit_code=1, duration_s=time.perf_counter() - started,
                )
        finally:
            pool.shutdown(wait=False)

        text = getattr(session, "final_result", "") or ""
        steps = getattr(session, "steps", []) or []
        commands = [
            {"command": str(getattr(s, "action", "")), "exit_code": None}
            for s in steps
            if getattr(s, "action", None)
        ]
        return BackendResult(
            engine="native",
            text=str(text),
            commands=commands,
            usage={"total_tokens": int(getattr(session, "total_tokens", 0) or 0)},
            exit_code=0 if getattr(session, "is_complete", True) else 1,
            duration_s=time.perf_counter() - started,
        )
