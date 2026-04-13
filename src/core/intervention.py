import os
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger("core.intervention")

@dataclass
class InterventionEvent:
    """干预事件 (汲取 GoalX Intervention Event)"""
    timestamp: str
    kind: str           # e.g., "budget_extend", "force_stop", "human_guidance"
    source: str         # "user" | "admin" | "guard"
    message: str
    affected_targets: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

class InterventionLogger:
    """
    干预日志管理器 (汲取 GoalX Intervention Logging)
    记录所有人工对 Agent 执行过程的干预，用于回溯和自我修复参考。
    """
    def __init__(self, run_dir: str):
        self.run_dir = run_dir
        self.log_path = os.path.join(run_dir, "control", "intervention.jsonl")
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def record(self, kind: str, source: str, message: str, affected_targets: Optional[List[str]] = None, **metadata):
        """记录一个干预事件"""
        event = InterventionEvent(
            timestamp=datetime.now().isoformat(),
            kind=kind,
            source=source,
            message=message,
            affected_targets=affected_targets or ["master"],
            metadata=metadata
        )

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
            logger.info(f"干预事件已记录: [{kind}] {message}")
        except Exception as e:
            logger.error(f"无法记录干预事件: {e}")

    def load_recent(self, count: int = 10) -> List[InterventionEvent]:
        """加载最近的干预事件"""
        if not os.path.exists(self.log_path):
            return []

        events = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[-count:]:
                    data = json.loads(line)
                    events.append(InterventionEvent(**data))
        except Exception as e:
            logger.error(f"加载干预事件失败: {e}")

        return events
