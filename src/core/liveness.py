import os
import time
import logging
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from .resource_monitor import ResourceMonitor

logger = logging.getLogger("core.liveness")

@dataclass
class LivenessPulse:
    """心跳脉冲记录"""
    timestamp: str
    component: str
    status: str
    memory_rss_mb: float
    cpu_percent: float
    last_event_id: Optional[str] = None

class LivenessMonitor:
    """
    生存状态监控器 (汲取 GoalX Heartbeat/Liveness 设计)
    用于检测 Agent 是否在长时间执行中失联或陷入异常状态。
    """
    def __init__(self, run_dir: str, resource_monitor: ResourceMonitor):
        self.run_dir = run_dir
        self.resource_monitor = resource_monitor
        self.pulse_path = os.path.join(run_dir, "control", "liveness.json")
        os.makedirs(os.path.dirname(self.pulse_path), exist_ok=True)

    def beat(self, component: str, last_event_id: Optional[str] = None):
        """发送一次心跳脉冲"""
        res_state = self.resource_monitor.check_health()
        pulse = LivenessPulse(
            timestamp=datetime.now().isoformat(),
            component=component,
            status="healthy" if res_state.is_healthy else "degraded",
            memory_rss_mb=res_state.memory_rss_mb,
            cpu_percent=res_state.cpu_percent,
            last_event_id=last_event_id
        )

        try:
            with open(self.pulse_path, 'w') as f:
                json.dump(asdict(pulse), f, indent=2)
            logger.debug(f"心跳脉冲: {component} -> {pulse.status}")
        except Exception as e:
            logger.error(f"写入心跳脉冲失败: {e}")

    def check_deadman_switch(self, timeout_seconds: int = 300) -> bool:
        """检查“死人开关”：如果心跳超时，则认为组件已崩溃"""
        if not os.path.exists(self.pulse_path):
            return False

        try:
            with open(self.pulse_path, 'r') as f:
                data = json.load(f)
                last_beat = datetime.fromisoformat(data["timestamp"])
                if (datetime.now() - last_beat).total_seconds() > timeout_seconds:
                    logger.warning(f"检测到组件失联: {data['component']} 最后一次心跳在 {data['timestamp']}")
                    return True
        except Exception as e:
            logger.error(f"检查心跳失败: {e}")

        return False
