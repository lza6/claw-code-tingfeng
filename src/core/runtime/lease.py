"""
Runtime Lease System - 运行时租约/生命周期管理

[Phase 4] 汲取 GoalX 的 Lease 机制。
用于跟踪 Agent 运行时的活跃状态，支持崩溃检测和僵尸进程清理。
"""

import json
import time
import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class RuntimeLease:
    """
    运行时租约 - 记录进程活跃状态。

    存储在: .clawd/runs/{run_id}/runtime/lease.json
    """

    def __init__(self, run_dir: Path, session_id: str):
        self.run_dir = run_dir
        self.session_id = session_id
        self.runtime_dir = run_dir / "runtime"
        self.lease_file = self.runtime_dir / f"lease-{session_id}.json"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        self.pid = os.getpid()
        self.start_time = datetime.utcnow().isoformat()
        self.last_beat = time.time()
        self.ttl = 60  # 默认 60 秒失效

    def beat(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        """更新心跳"""
        self.last_beat = time.time()
        data = {
            "session_id": self.session_id,
            "pid": self.pid,
            "start_time": self.start_time,
            "last_beat": self.last_beat,
            "ttl": self.ttl,
            "metadata": metadata or {}
        }

        try:
            # 原子写入租约文件
            temp_file = self.lease_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.lease_file)
        except Exception as e:
            logger.warning(f"更新租约失败: {e}")

    def is_expired(self) -> bool:
        """检查租约是否已过期"""
        if not self.lease_file.exists():
            return True
        return (time.time() - self.last_beat) > self.ttl

    def release(self) -> None:
        """释放租约"""
        if self.lease_file.exists():
            try:
                self.lease_file.unlink()
            except Exception:
                pass


class LeaseMonitor:
    """
    租约监控器 - 用于检测其他 Session 是否活跃。
    """

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.runtime_dir = run_dir / "runtime"

    def get_active_sessions(self) -> Dict[str, Dict[str, Any]]:
        """获取所有活跃的会话"""
        active = {}
        if not self.runtime_dir.exists():
            return active

        for lease_file in self.runtime_dir.glob("lease-*.json"):
            try:
                with open(lease_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                last_beat = data.get("last_beat", 0)
                ttl = data.get("ttl", 60)

                if (time.time() - last_beat) <= ttl:
                    active[data["session_id"]] = data
                else:
                    # 清理过期的租约文件
                    try:
                        lease_file.unlink()
                    except Exception:
                        pass
            except Exception:
                continue

        return active
