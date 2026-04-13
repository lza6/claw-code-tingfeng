from __future__ import annotations

import asyncio
import time
from pathlib import Path

from .base import SandboxProvider, SandboxResult


class DockerSandboxProvider(SandboxProvider):
    """Docker 沙箱提供者（通过 docker CLI 或 SDK）"""

    def __init__(self, image: str = "python:3.10-slim", container_name: str | None = None) -> None:
        self.image = image
        self.container_name = container_name or f"clawd-sandbox-{int(time.time())}"
        self._is_container_running = False

    async def _ensure_container(self) -> None:
        """确保 Docker 容器正在运行"""
        if self._is_container_running:
            return

        # 检查镜像是否存在，不存在则拉取
        check_image = await asyncio.create_subprocess_exec(
            "docker", "images", "-q", self.image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await check_image.communicate()
        if not stdout.strip():
            # 拉取镜像
            pull_image = await asyncio.create_subprocess_exec(
                "docker", "pull", self.image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await pull_image.communicate()

        # 启动常驻容器（使用 sleep infinity）
        start_cmd = [
            "docker", "run", "-d",
            "--name", self.container_name,
            "--rm",
            "-v", f"{Path.cwd()}:/workspace",
            "-w", "/workspace",
            self.image,
            "sleep", "infinity"
        ]

        proc = await asyncio.create_subprocess_exec(
            *start_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        self._is_container_running = True

    async def execute(
        self,
        command: list[str],
        workdir: Path | str | None = None,
        timeout: int = 30,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> SandboxResult:
        """在 Docker 容器中执行命令"""
        start_time = time.monotonic()
        await self._ensure_container()

        # 构造 docker exec 命令
        exec_cmd = ["docker", "exec"]

        # 内存限制 (Docker exec 不直接支持 --memory, 这里通过 cgroups prlimit 或在 run 时设置)
        # 注意: 这里的实现逻辑是每次 exec。如果需要严格限制，应在 run 时指定。
        # 这里我们通过 docker update 动态调整容器限制 (针对单容器常驻模式)
        if memory_limit_mb:
            try:
                limit_proc = await asyncio.create_subprocess_exec(
                    "docker", "update", "--memory", f"{memory_limit_mb}m",
                    "--memory-swap", f"{memory_limit_mb}m",
                    self.container_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await limit_proc.communicate()
            except Exception:
                pass

        # 环境变量
        if env:
            for k, v in env.items():
                exec_cmd.extend(["-e", f"{k}={v}"])

        # 工作目录
        if workdir:
            # 尝试映射为容器内路径
            try:
                rel_path = Path(workdir).relative_to(Path.cwd())
                exec_cmd.extend(["-w", f"/workspace/{rel_path}"])
            except ValueError:
                # 如果不在工作区内，暂时不支持（安全起见）
                pass

        exec_cmd.append(self.container_name)
        exec_cmd.extend(command)

        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                # 尝试终止 exec 进程
                try:
                    proc.kill()
                    # 容器内进程可能还在跑，但由于容器是 --rm 且 exec 只是附属，通常没关系
                    # 极端情况下可以 docker exec container kill -9 PID
                except Exception:
                    pass
                return SandboxResult(
                    exit_code=124,
                    stdout="",
                    stderr=f"Docker 执行超时 ({timeout}s)",
                    duration_ms=(time.monotonic() - start_time) * 1000,
                )

            duration_ms = (time.monotonic() - start_time) * 1000

            return SandboxResult(
                exit_code=proc.returncode or 0,
                stdout=stdout.decode('utf-8', errors='replace') if stdout else "",
                stderr=stderr.decode('utf-8', errors='replace') if stderr else "",
                duration_ms=duration_ms,
            )

        except Exception as e:
            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr=f"Docker 执行错误: {e}",
                duration_ms=(time.monotonic() - start_time) * 1000,
            )

    def close(self) -> None:
        """关闭并删除容器"""
        if self._is_container_running:
            # 同步方式关闭
            subprocess.run(["docker", "stop", "-t", "2", self.container_name],
                           capture_output=True, check=False)
            self._is_container_running = False
