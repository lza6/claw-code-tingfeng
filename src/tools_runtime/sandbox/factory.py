from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Any

from .base import SandboxProvider
from .docker import DockerSandboxProvider
from .local import LocalSandboxProvider

logger = logging.getLogger(__name__)


class SandboxType(str, Enum):
    """沙箱类型"""
    LOCAL = "local"
    DOCKER = "docker"


class SandboxFactory:
    """沙箱工厂类"""

    @staticmethod
    def create(
        sandbox_type: SandboxType | str | None = None,
        **kwargs: Any
    ) -> SandboxProvider:
        """
        根据配置创建沙箱提供者

        Args:
            sandbox_type: 沙箱类型 (local/docker)
            **kwargs: 构造参数

        Returns:
            SandboxProvider: 沙箱实例
        """
        # 优先级：参数指定 -> 环境变量 -> 默认 local
        st = sandbox_type or os.environ.get("SANDBOX_TYPE", SandboxType.LOCAL)

        if st == SandboxType.DOCKER:
            try:
                # 检查 docker 环境
                import subprocess
                subprocess.run(["docker", "--version"], capture_output=True, check=True)
                logger.info("创建 Docker 沙箱提供者")
                return DockerSandboxProvider(**kwargs)
            except Exception as e:
                logger.warning(f"无法创建 Docker 沙箱: {e}，回退到本地执行")
                return LocalSandboxProvider()

        logger.info("创建本地沙箱提供者")
        return LocalSandboxProvider()
