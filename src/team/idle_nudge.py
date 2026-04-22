"""
Idle Nudge - 空闲提醒机制

从 oh-my-codex-main/src/team/idle-nudge.ts 转换。
在团队等待轮询期间检测空闲的tmux pane并发送提醒。

功能:
- 空闲检测 (pane看起来ready但无活跃任务)
- 定时nudge发送
- 每pane最大nudge次数限制
- 节流扫描
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass

# ===== 常量 =====
DEFAULT_DELAY_MS = 30_000  # 30秒
DEFAULT_MAX_COUNT = 3
DEFAULT_SCAN_INTERVAL_MS = 5_000  # 5秒
DEFAULT_MESSAGE = "Next: read your inbox/mailbox, continue your assigned task now, and if blocked send the leader a concrete status update."


# ===== 配置 =====
@dataclass
class NudgeConfig:
    """Nudge配置"""
    delay_ms: int = DEFAULT_DELAY_MS  # 首次nudge前的空闲时间(ms)
    max_count: int = DEFAULT_MAX_COUNT  # 每个pane最大nudge次数
    message: str = DEFAULT_MESSAGE  # 发送的消息


@dataclass
class PaneNudgeState:
    """Pane的nudge状态"""
    nudge_count: int = 0
    first_idle_at: int | None = None
    last_nudge_at: int | None = None


# ===== 工具函数 =====
def capture_pane(pane_id: str, lines: int = 80) -> str:
    """捕获tmux pane的最后N行"""
    try:
        result = subprocess.run(
            ['tmux', 'capture-pane', '-t', pane_id, '-p', '-S', str(-lines)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout if result.returncode == 0 else ''
    except Exception:
        return ''


def pane_looks_ready(captured: str) -> bool:
    """检查pane是否看起来已准备好接受输入

    特征: 包含常见的prompt符号 ($, >, %, #, >, etc.)
    """
    if not captured:
        return False

    # 常见prompt模式
    patterns = [
        r'\$\s*$',           # $
        r'>\s*$',            # >
        r'%\s*$',           # %
        r'#\s*$',           # #
        r'❯\s*$',           # ❯
        r'→\s*$',           # →
        r'➜\s*$',           # ➜
        r'λ\s*$',           # λ
    ]

    for pattern in patterns:
        if re.search(pattern, captured, re.MULTILINE):
            return True

    return False


def pane_has_active_task(captured: str) -> bool:
    """检查pane是否有活跃任务在运行

    特征: 包含常见的运行中命令关键字
    """
    if not captured:
        return False

    # 运行中命令模式
    patterns = [
        r'\b(git|npm|python|pip|node|docker|cargo|make|ruff)\s+',
        r'\brunning\b',
        r'\bexecuting\b',
        r'Building',
        r'Installing',
        r'Compiling',
        r'Downloading',
    ]

    for pattern in patterns:
        if re.search(pattern, captured, re.IGNORECASE):
            return True

    return False


def is_pane_idle(pane_id: str) -> bool:
    """检查pane是否空闲

    空闲 = 看起来ready (有prompt) AND 无活跃任务
    """
    captured = capture_pane(pane_id)
    if not captured:
        return False

    return pane_looks_ready(captured) and not pane_has_active_task(captured)


def send_to_worker(session_name: str, pane_id: str, message: str) -> bool:
    """发送消息到worker pane

    参数:
        session_name: tmux session名称
        pane_id: pane ID (格式: %N)
        message: 要发送的消息

    返回:
        成功返回True
    """
    try:
        # 发送消息到pane
        subprocess.run(
            ['tmux', 'send-keys', '-t', pane_id, message, 'C-m'],
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception:
        return False


# ===== NudgeTracker =====
class NudgeTracker:
    """空闲pane nudge追踪器"""

    def __init__(self, config: NudgeConfig | None = None):
        self.config = config or NudgeConfig()
        self.states: dict[str, PaneNudgeState] = {}
        self.last_scan_at = 0

    def check_and_nudge(
        self,
        pane_ids: list[str],
        leader_pane_id: str | None,
        session_name: str,
    ) -> list[str]:
        """检查worker panes并在适当时nudge

        参数:
            pane_ids: worker pane ID列表
            leader_pane_id: leader pane ID (不会被nudge)
            session_name: tmux session名称

        返回:
            本次nudge的pane ID列表
        """
        now = int(time.time() * 1000)

        # 节流: 如果上次扫描太近则跳过
        if now - self.last_scan_at < DEFAULT_SCAN_INTERVAL_MS:
            return []
        self.last_scan_at = now

        nudged: list[str] = []

        for pane_id in pane_ids:
            # 不nudge leader
            if pane_id == leader_pane_id:
                continue

            # 获取或创建状态
            if pane_id not in self.states:
                self.states[pane_id] = PaneNudgeState()

            state = self.states[pane_id]

            # 达到最大nudge次数则跳过
            if state.nudge_count >= self.config.max_count:
                continue

            # 检查空闲
            idle = is_pane_idle(pane_id)

            if not idle:
                # pane活跃 - 重置空闲追踪
                state.first_idle_at = None
                continue

            # 记录首次检测到空闲的时间
            if state.first_idle_at is None:
                state.first_idle_at = now

            # 是否已空闲足够长时间
            if now - state.first_idle_at < self.config.delay_ms:
                continue

            # 发送nudge
            ok = send_to_worker(session_name, pane_id, self.config.message)
            if ok:
                state.nudge_count += 1
                state.last_nudge_at = now
                # 重置空闲计时器，这样下次nudge需要再等待完整delay
                state.first_idle_at = None
                nudged.append(pane_id)

        return nudged

    def get_summary(self) -> dict[str, dict[str, int]]:
        """获取nudge活动摘要"""
        out: dict[str, dict[str, int]] = {}
        for pane_id, state in self.states.items():
            if state.nudge_count > 0:
                out[pane_id] = {
                    'nudge_count': state.nudge_count,
                    'last_nudge_at': state.last_nudge_at or 0,
                }
        return out

    @property
    def total_nudges(self) -> int:
        """总nudge次数"""
        return sum(state.nudge_count for state in self.states.values())


# ===== 导出 =====
__all__ = [
    "NudgeConfig",
    "NudgeTracker",
    "PaneNudgeState",
    # 工具函数
    "capture_pane",
    "is_pane_idle",
    "pane_has_active_task",
    "pane_looks_ready",
    "send_to_worker",
]
