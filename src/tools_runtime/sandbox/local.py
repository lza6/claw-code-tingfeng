from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
import time
from pathlib import Path

from .base import SandboxProvider, SandboxResult


class LocalSandboxProvider(SandboxProvider):
    """本地沙箱提供者（基于 subprocess）"""

    def __init__(self) -> None:
        self._processes: list[asyncio.subprocess.Process] = []

    async def execute(
        self,
        command: list[str],
        workdir: Path | str | None = None,
        timeout: int = 30,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> SandboxResult:
        """在本地执行命令 (注意: memory_limit_mb 在本地模式下暂不支持)"""
        start_time = time.monotonic()
        workdir_str = str(workdir) if workdir else None

        creationflags = 0
        if sys.platform == 'win32':
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            # 使用原生异步 subprocess
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir_str,
                env=env,
                creationflags=creationflags,
            )
            self._processes.append(proc)

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                with contextlib.suppress(OSError):
                    proc.kill()
                return SandboxResult(
                    exit_code=124,
                    stdout="",
                    stderr=f"命令执行超时 ({timeout}s)",
                    duration_ms=(time.monotonic() - start_time) * 1000,
                )
            finally:
                if proc in self._processes:
                    self._processes.remove(proc)

            duration_ms = (time.monotonic() - start_time) * 1000

            return SandboxResult(
                exit_code=proc.returncode or 0,
                stdout=stdout.decode('utf-8', errors='replace') if stdout else "",
                stderr=stderr.decode('utf-8', errors='replace') if stderr else "",
                duration_ms=duration_ms,
            )

        except FileNotFoundError:
            return SandboxResult(
                exit_code=127,
                stdout="",
                stderr=f"命令未找到: {command[0]}",
                duration_ms=(time.monotonic() - start_time) * 1000,
            )
        except Exception as e:
            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr=f"执行错误: {e}",
                duration_ms=(time.monotonic() - start_time) * 1000,
            )

    def close(self) -> None:
        """清理所有正在运行的进程"""
        for proc in self._processes:
            with contextlib.suppress(OSError):
                proc.kill()
        self._processes.clear()
