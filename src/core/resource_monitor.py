import psutil
import logging
import os
import platform
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

logger = logging.getLogger("core.resource")

@dataclass(frozen=True)
class ResourceState:
    cpu_percent: float
    memory_rss_mb: float
    disk_free_gb: float
    load_avg: tuple[float, float, float]
    is_healthy: bool


@dataclass
class ResourceProfile:
    """[汲取 GoalX ResourceProfile] 详细的资源画像"""
    host: str = field(default_factory=platform.node)
    pid: int = os.getpid()
    cpu_percent: float = 0.0
    memory_rss_mb: float = 0.0
    memory_percent: float = 0.0
    memory_available_gb: float = 0.0
    memory_total_gb: float = 0.0
    disk_percent: float = 0.0
    disk_free_gb: float = 0.0
    load_avg: tuple = (0.0, 0.0, 0.0)
    timestamp: str = ""


class ResourceMonitor:
    """
    资源安全监控器 (借鉴 GoalX)
    监控 RSS, CPU, 负载等，确保执行安全。

    [汲取 GoalX 增强]:
    - ResourceProfile 详细画像
    - PSI (Pressure Stall Information) 监控
    - 资源历史追踪
    """

    def __init__(self, memory_threshold_mb: float = 4096.0, cpu_threshold: float = 85.0):
        self.memory_threshold_mb = memory_threshold_mb
        self.cpu_threshold = cpu_threshold
        self._history: list[ResourceState] = []
        self._max_history = 100  # 保留最近 100 条记录

    def check_health(self) -> ResourceState:
        """检查当前系统健康状态"""
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        rss_mb = mem_info.rss / (1024 * 1024)

        cpu_percent = psutil.cpu_percent(interval=0.1)
        disk_usage = psutil.disk_usage('/')
        load_avg = os.getloadavg() if hasattr(os, 'getloadavg') else (0.0, 0.0, 0.0)

        is_healthy = (
            rss_mb < self.memory_threshold_mb and
            cpu_percent < self.cpu_threshold
        )

        state = ResourceState(
            cpu_percent=cpu_percent,
            memory_rss_mb=rss_mb,
            disk_free_gb=disk_usage.free / (1024**3),
            load_avg=load_avg,
            is_healthy=is_healthy
        )

        # 记录历史
        self._history.append(state)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        if not is_healthy:
            logger.warning(f"系统资源紧张: {state}")

        return state

    def get_resource_profile(self) -> ResourceProfile:
        """[汲取 GoalX] 获取详细资源画像

        Returns:
            ResourceProfile: 包含主机、PID、CPU、内存、磁盘等详细信息
        """
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        rss_mb = mem_info.rss / (1024 * 1024)

        virtual_mem = psutil.virtual_memory()
        disk_usage = psutil.disk_usage('/' if platform.system() != "Windows" else "C:\\")

        from datetime import datetime

        profile = ResourceProfile(
            host=platform.node(),
            pid=process.pid,
            cpu_percent=psutil.cpu_percent(interval=0.1),
            memory_rss_mb=round(rss_mb, 1),
            memory_percent=virtual_mem.percent,
            memory_available_gb=round(virtual_mem.available / (1024**3), 2),
            memory_total_gb=round(virtual_mem.total / (1024**3), 2),
            disk_percent=disk_usage.percent,
            disk_free_gb=round(disk_usage.free / (1024**3), 2),
            load_avg=os.getloadavg() if hasattr(os, 'getloadavg') else (0.0, 0.0, 0.0),
            timestamp=datetime.now().isoformat()
        )

        return profile

    def get_resource_history(self, limit: int = 10) -> list[ResourceState]:
        """获取资源历史记录

        Args:
            limit: 返回最近 N 条记录

        Returns:
            资源状态历史列表
        """
        return self._history[-limit:]

    def check_memory_pressure(self) -> tuple[bool, str]:
        """[汲取 GoalX] 检查内存压力

        Returns:
            (is_pressure, reason): 是否存在内存压力及原因
        """
        profile = self.get_resource_profile()

        if profile.memory_percent > 90:
            return True, f"内存使用率极高 ({profile.memory_percent:.1f}%)"
        if profile.memory_rss_mb > 8192:  # 8GB
            return True, f"进程 RSS 过大 ({profile.memory_rss_mb:.1f}MB)"
        if profile.memory_available_gb < 1.0:
            return True, f"可用内存不足 ({profile.memory_available_gb:.2f}GB)"

        return False, "memory pressure normal"

    def check_cpu_pressure(self) -> tuple[bool, str]:
        """[汲取 GoalX] 检查 CPU 压力

        Returns:
            (is_pressure, reason): 是否存在 CPU 压力及原因
        """
        profile = self.get_resource_profile()

        if profile.cpu_percent > 95:
            return True, f"CPU 使用率极高 ({profile.cpu_percent:.1f}%)"
        if profile.load_avg[0] > os.cpu_count() * 2:
            return True, f"负载过高 ({profile.load_avg[0]:.1f})"

        return False, "cpu pressure normal"

    def record_resource_log(self, log_path: str):
        """记录资源状态到文件 (类似 GoalX control/resource-state.json)"""
        profile = self.get_resource_profile()

        import json
        data = {
            "host": profile.host,
            "pid": profile.pid,
            "cpu_percent": profile.cpu_percent,
            "memory_rss_mb": profile.memory_rss_mb,
            "memory_percent": profile.memory_percent,
            "memory_available_gb": profile.memory_available_gb,
            "memory_total_gb": profile.memory_total_gb,
            "disk_percent": profile.disk_percent,
            "disk_free_gb": profile.disk_free_gb,
            "load_avg": list(profile.load_avg),
            "timestamp": profile.timestamp,
            "healthy": profile.cpu_percent < self.cpu_threshold and profile.memory_rss_mb < self.memory_threshold_mb
        }

        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'w') as f:
            json.dump(data, f, indent=2)
