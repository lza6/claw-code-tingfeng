from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SandboxResult:
    """沙箱执行结果"""
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """是否执行成功"""
        return self.exit_code == 0


@runtime_checkable
class SandboxProvider(Protocol):
    """沙箱提供者协议"""

    async def execute(
        self,
        command: list[str],
        workdir: Path | str | None = None,
        timeout: int = 30,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> SandboxResult:
        """
        在沙箱中执行命令

        Args:
            command: 命令及参数列表
            workdir: 工作目录
            timeout: 超时时间（秒）
            env: 环境变量
            memory_limit_mb: 内存限制（MB）

        Returns:
            SandboxResult: 执行结果
        """
        ...

    def close(self) -> None:
        """释放资源"""
        ...
