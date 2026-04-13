"""
Runtime Host - 运行时托管主机

[Phase 4] 汲取 GoalX 的 Runtime Host 设计。
提供统一的执行上下文、资源限制和生命周期钩子。
"""

import os
import signal
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime

from .lease import RuntimeLease
from ..resource_monitor import ResourceMonitor

logger = logging.getLogger(__name__)

class RuntimeHost:
    """
    托管运行时环境的主机。
    负责:
    - 管理 Session 租约 (Lease)
    - 监控资源限制 (CPU/Memory)
    - 处理优雅退出 (SIGTERM/SIGINT)
    - 执行生命周期钩子
    """

    def __init__(
        self,
        run_dir: Path,
        session_id: str,
        resource_monitor: Optional[ResourceMonitor] = None
    ):
        self.run_dir = run_dir
        self.session_id = session_id
        self.resource_monitor = resource_monitor or ResourceMonitor()
        self.lease = RuntimeLease(run_dir, session_id)

        self._is_running = False
        self._hooks: Dict[str, List[Callable]] = {
            "before_start": [],
            "after_stop": [],
            "on_error": []
        }

    def add_hook(self, event: str, func: Callable):
        """添加生命周期钩子"""
        if event in self._hooks:
            self._hooks[event].append(func)

    async def start(self):
        """启动运行时托管"""
        logger.info(f"RuntimeHost 启动: {self.session_id} (PID: {os.getpid()})")
        self._is_running = True

        # 立即执行一次心跳，确保租约文件存在
        self._heartbeat()

        # 执行启动前钩子
        for hook in self._hooks["before_start"]:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()
            except Exception as e:
                logger.error(f"执行 before_start 钩子失败: {e}")

        # 启动租约心跳循环
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self):
        """停止运行时托管"""
        logger.info(f"RuntimeHost 停止: {self.session_id}")
        self._is_running = False

        if hasattr(self, "_heartbeat_task"):
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        self.lease.release()

        # 执行停止后钩子
        for hook in self._hooks["after_stop"]:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()
            except Exception as e:
                logger.error(f"执行 after_stop 钩子失败: {e}")

    def _heartbeat(self):
        """执行心跳逻辑"""
        try:
            # 检查资源状态
            rstate = self.resource_monitor.check_health()

            # 更新租约
            self.lease.beat(metadata={
                "memory_rss_mb": rstate.memory_rss_mb,
                "cpu_percent": rstate.cpu_percent,
                "is_healthy": rstate.is_healthy,
                "timestamp": datetime.utcnow().isoformat()
            })

            if not rstate.is_healthy:
                logger.warning(f"检测到资源异常: {rstate}")

        except Exception as e:
            logger.error(f"心跳逻辑异常: {e}")

    async def _heartbeat_loop(self):
        """租约心跳循环"""
        while self._is_running:
            await asyncio.sleep(10)  # 每 10 秒跳动一次
            self._heartbeat()

    def get_status(self) -> Dict[str, Any]:
        """获取运行时状态摘要"""
        rstate = self.resource_monitor.check_health()
        return {
            "session_id": self.session_id,
            "pid": os.getpid(),
            "is_running": self._is_running,
            "memory_usage": f"{rstate.memory_rss_mb} MB",
            "cpu_usage": f"{rstate.cpu_percent}%",
            "health": "healthy" if rstate.is_healthy else "unhealthy"
        }
