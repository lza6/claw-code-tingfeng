"""预算守卫模块 - 负责运行成本、时间和 Token 消耗的实时熔断 (汲取 GoalX BudgetGuard)

[汲取 GoalX] 增强特性：
- 系统资源安全监控 (PSI, RSS, Host 压力)
- 动态资源调整能力
- 安全拒绝机制：当资源压力过大时拒绝新任务
"""

from __future__ import annotations

import logging
import os
import platform
import time
from dataclasses import dataclass, field
from typing import Any

from .durable.surfaces.resource_state import (
    CgroupEvents,
    CgroupLimits,
    GoalXProcesses,
    HostInfo,
    PSIData,
    PSIValues,
    ResourceHealthState,
    ResourceState,
)
from .events import Event, EventType, get_event_bus
from .exceptions import ClawdError, ErrorCode
from .intervention import InterventionLogger

logger = logging.getLogger("core.budget.guard")

# 尝试导入 psutil 用于系统资源监控
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil 未安装，系统资源监控功能受限")


@dataclass
class ResourceThresholds:
    """[汲取 GoalX] 资源压力阈值配置"""
    memory_percent_max: float = 90.0  # 内存使用百分比上限
    cpu_percent_max: float = 95.0     # CPU 使用百分比上限
    disk_percent_max: float = 95.0   # 磁盘使用百分比上限


@dataclass
class BudgetConfig:
    """预算配置"""

    max_duration_seconds: int | None = None
    max_cost_usd: float | None = None
    max_tokens: int | None = None
    # [汲取 GoalX] 资源安全阈值
    resource_thresholds: ResourceThresholds = field(default_factory=ResourceThresholds)


class BudgetGuard:
    """预算守卫 - 实时监控并强制熔断超出预算的任务

    [汲取 GoalX] 增强资源安全：
    - 监控 Host 内存/CPU 压力
    - 在资源压力过大时拒绝新任务执行
    - 记录资源状态到 control/resource-state.json
    """

    def __init__(self, config: BudgetConfig | None = None, run_dir: str = "latest"):
        self.config = config or BudgetConfig()
        self.run_dir = run_dir
        self.intervention_logger = InterventionLogger(self.run_dir)
        self.start_time: float | None = None
        self.accumulated_cost: float = 0.0
        self.accumulated_tokens: int = 0
        self.is_exhausted: bool = False
        self.exhaustion_reason: str = ""
        # [汲取 GoalX] 资源压力追踪
        self._last_resource_check: float = 0.0
        self._resource_check_interval: float = 5.0  # 每5秒检查一次资源
        self._cached_resource_state: dict[str, Any] | None = None

    def get_resource_state(self) -> ResourceState:
        """[汲取 GoalX] 获取当前系统资源状态 (增强版本，支持 PSI 和 Cgroup)

        Returns:
            ResourceState 实例
        """
        now = time.time()
        # 使用缓存避免频繁调用 (5秒缓存)
        if self._cached_resource_state and (now - self._last_resource_check) < self._resource_check_interval:
            return ResourceState.from_dict(self._cached_resource_state)

        state = ResourceState.create_default()

        if not PSUTIL_AVAILABLE:
            state.state = ResourceHealthState.UNKNOWN
            state.reasons = ["psutil not installed"]
            return state

        try:
            # 1. 探测 Host 信息
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            state.host = HostInfo(
                mem_total_bytes=memory.total,
                mem_available_bytes=memory.available,
                swap_total_bytes=swap.total,
                swap_free_bytes=swap.free
            )

            # 2. 探测 PSI 信息 (仅 Linux)
            if platform.system() == "Linux":
                psi_path = "/proc/pressure/memory"
                if os.path.exists(psi_path):
                    try:
                        with open(psi_path) as f:
                            psi_data = f.read()
                            state.psi = self._parse_psi_data(psi_data)
                    except Exception as e:
                        logger.warning(f"读取 PSI 数据失败: {e}")

            # 3. 探测 Cgroup 信息 (仅 Linux)
            if platform.system() == "Linux":
                state.cgroup = self._probe_cgroup_info()

            # 4. 探测进程信息
            process = psutil.Process()
            state.goalx_processes = GoalXProcesses(
                master_rss_bytes=process.memory_info().rss,
                total_goalx_rss_bytes=process.memory_info().rss
            )

            # 5. 计算 Headroom
            state.calculate_headroom()

            # 6. 检查健康状况
            state.check_health()

            self._cached_resource_state = state.to_dict()
            self._last_resource_check = now
            return state

        except Exception as exc:
            logger.warning(f"获取资源状态失败: {exc}")
            state.state = ResourceHealthState.UNKNOWN
            state.reasons = [str(exc)]
            return state

    def _parse_psi_data(self, data: str) -> PSIData:
        """解析 /proc/pressure/memory 内容"""
        res = PSIData()
        for line in data.strip().split('\n'):
            parts = line.split()
            if not parts:
                continue
            label = parts[0]
            values = {}
            for p in parts[1:]:
                if '=' in p:
                    k, v = p.split('=')
                    values[k] = float(v)

            psi_val = PSIValues(
                avg10=values.get('avg10', 0.0),
                avg60=values.get('avg60', 0.0),
                avg300=values.get('avg300', 0.0)
            )
            if label == "some":
                res.memory_some = psi_val
            elif label == "full":
                res.memory_full = psi_val
        return res

    def _probe_cgroup_info(self) -> CgroupLimits:
        """探测 Cgroup V2 内存限制"""
        base = "/sys/fs/cgroup"
        res = CgroupLimits()

        def read_int(path):
            if os.path.exists(path):
                with open(path) as f:
                    val = f.read().strip()
                    if val == "max":
                        return 0
                    return int(val)
            return 0

        res.memory_current_bytes = read_int(f"{base}/memory.current")
        res.memory_high_bytes = read_int(f"{base}/memory.high")
        res.memory_max_bytes = read_int(f"{base}/memory.max")
        res.memory_swap_current_bytes = read_int(f"{base}/memory.swap.current")
        res.memory_swap_max_bytes = read_int(f"{base}/memory.swap.max")

        events_path = f"{base}/memory.events"
        if os.path.exists(events_path):
            ev = CgroupEvents()
            with open(events_path) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) == 2:
                        k, v = parts[0], int(parts[1])
                        if k == "low":
                            ev.low = v
                        elif k == "high":
                            ev.high = v
                        elif k == "max":
                            ev.max = v
                        elif k == "oom":
                            ev.oom = v
                        elif k == "oom_kill":
                            ev.oom_kill = v
            res.events = ev

        return res

    def check_resource_pressure(self) -> tuple[bool, str]:
        """[汲取 GoalX] 检查系统资源压力是否在安全范围内

        Returns:
            (is_safe, reason): 是否安全及原因
        """
        state = self.get_resource_state()
        if state.state == ResourceHealthState.UNKNOWN:
            # 无法检测时默认安全，但记录警告
            logger.warning(f"资源状态未知: {'; '.join(state.reasons)}")
            return True, "resource monitoring unavailable"

        if state.state == ResourceHealthState.CRITICAL:
            return False, f"CRITICAL: {'; '.join(state.reasons)}"

        return True, "resource pressure normal"

    def can_execute(self) -> tuple[bool, str]:
        """[汲取 GoalX] 检查是否可以安全执行新任务

        综合检查预算和资源状态

        Returns:
            (can_execute, reason): 是否可以执行及原因
        """
        # 先检查预算
        if self.is_exhausted:
            return False, f"budget exhausted: {self.exhaustion_reason}"

        # 再检查资源压力
        is_safe, reason = self.check_resource_pressure()
        if not is_safe:
            return False, f"resource pressure unsafe: {reason}"

        return True, "ready to execute"

    def start(self):
        """开始计时并订阅预算事件"""
        if self.start_time is None:
            self.start_time = time.time()
            # 汲取 GoalX: 订阅成本事件，订阅失败视为致命错误
            bus = get_event_bus()
            for event_type in (
                EventType.COST_RECORDED,
                EventType.AGENT_COST_UPDATE,
                EventType.AGENT_TOKEN_USAGE,
            ):
                try:
                    bus.subscribe(
                        event_type,
                        (
                            self._on_cost_event
                            if event_type != EventType.AGENT_TOKEN_USAGE
                            else self._on_token_event
                        ),
                    )
                except Exception as exc:
                    logger.error(
                        f"预算事件订阅失败，无法保证预算监控: {event_type.value}: {exc}"
                    )
                    raise RuntimeError(
                        f"预算守卫初始化失败: 无法订阅事件 {event_type.value}"
                    ) from exc
            logger.info(f"预算守卫已启动: {self.config}")

    def _on_token_event(self, event: Any):
        """处理来自事件总线的 Token 记录"""
        tokens = event.data.get("tokens", 0)
        if not tokens:
            tokens = event.data.get("usage", {}).get("total_tokens", 0)
        self.record_usage(tokens=tokens)

    def _on_cost_event(self, event: Any):
        """处理来自事件总线的成本记录"""
        cost = event.data.get("cost", 0.0)
        tokens = event.data.get("tokens", 0)
        self.record_usage(cost, tokens)

    def record_usage(self, cost: float = 0.0, tokens: int = 0):
        """记录资源消耗"""
        self.accumulated_cost += cost
        self.accumulated_tokens += tokens
        self.check()

    def check(self) -> bool:
        """检查是否超出预算，如果超出则标记为耗尽"""
        if self.is_exhausted:
            return True

        # 检查时间
        if self.config.max_duration_seconds and self.start_time:
            elapsed = time.time() - self.start_time
            if elapsed >= self.config.max_duration_seconds:
                self.is_exhausted = True
                self.exhaustion_reason = (
                    f"时间超限 ({elapsed:.1f}s >= {self.config.max_duration_seconds}s)"
                )

        # 检查成本
        if (
            self.config.max_cost_usd
            and self.accumulated_cost > self.config.max_cost_usd
        ):
            self.is_exhausted = True
            self.exhaustion_reason = f"成本超限 (${self.accumulated_cost:.4f} > ${self.config.max_cost_usd:.4f})"

        # 检查 Token
        if self.config.max_tokens and self.accumulated_tokens >= self.config.max_tokens:
            self.is_exhausted = True
            self.exhaustion_reason = (
                f"Token 超限 ({self.accumulated_tokens} >= {self.config.max_tokens})"
            )

        if self.is_exhausted:
            logger.warning(f"预算已耗尽! 原因: {self.exhaustion_reason}")
            # [汲取 GoalX] 发布预算耗尽事件 (不让外部抛错中断，由 validate 负责)
            try:
                get_event_bus().publish(
                    Event(
                        type=EventType.BUDGET_EXHAUSTED,
                        data={"reason": self.exhaustion_reason},
                    )
                )
            except Exception as exc:
                logger.error(f"发布预算耗尽事件失败 (非致命): {exc}")

            try:
                self.intervention_logger.record(
                    kind="budget_exhausted",
                    source="guard",
                    message=f"工作流因预算耗尽中止: {self.exhaustion_reason}",
                )
            except Exception as exc:
                logger.error(f"写入预算耗尽干预日志失败 (非致命): {exc}")

        return self.is_exhausted

    def extend_budget(self, duration_seconds: int = 0, cost_usd: float = 0.0, tokens: int = 0):
        """汲取 GoalX: 扩展现有预算"""
        if duration_seconds and self.config.max_duration_seconds:
            self.config.max_duration_seconds += duration_seconds
        elif duration_seconds:
            self.config.max_duration_seconds = duration_seconds

        if cost_usd and self.config.max_cost_usd:
            self.config.max_cost_usd += cost_usd
        elif cost_usd:
            self.config.max_cost_usd = cost_usd

        if tokens and self.config.max_tokens:
            self.config.max_tokens += tokens
        elif tokens:
            self.config.max_tokens = tokens

        self.is_exhausted = False
        self.exhaustion_reason = ""
        self.intervention_logger.record(
            kind="budget_extend",
            source="user",
            message=f"扩展预算: +{duration_seconds}s, +${cost_usd}, +{tokens}t"
        )
        logger.info(f"预算已扩展: {self.config}")

    def set_total_budget(self, duration_seconds: int | None = None, cost_usd: float | None = None, tokens: int | None = None):
        """汲取 GoalX: 设置总体预算限制"""
        if duration_seconds is not None:
            self.config.max_duration_seconds = duration_seconds
        if cost_usd is not None:
            self.config.max_cost_usd = cost_usd
        if tokens is not None:
            self.config.max_tokens = tokens

        self.is_exhausted = False
        self.exhaustion_reason = ""
        self.intervention_logger.record(
            kind="budget_set_total",
            source="user",
            message=f"设置总预算: {duration_seconds}s, ${cost_usd}, {tokens}t"
        )
        logger.info(f"总预算已更新: {self.config}")

    def clear_budget(self):
        """汲取 GoalX: 清除所有预算限制"""
        self.config.max_duration_seconds = None
        self.config.max_cost_usd = None
        self.config.max_tokens = None
        self.is_exhausted = False
        self.exhaustion_reason = ""
        self.intervention_logger.record(
            kind="budget_clear",
            source="user",
            message="清除所有预算限制"
        )
        logger.info("预算限制已清除")

    def validate(self):
        """如果预算耗尽，抛出异常强制中止"""
        if self.check():
            raise ClawdError(
                code=ErrorCode.TOKEN_LIMIT_EXCEEDED,
                message=f"Budget Exhausted: {self.exhaustion_reason}",
                details={"budget_reason": self.exhaustion_reason},
                recoverable=False,
            )

    def get_status(self) -> dict[str, Any]:
        """获取当前预算消耗状态"""
        elapsed = time.time() - self.start_time if self.start_time else 0
        return {
            "exhausted": self.is_exhausted,
            "reason": self.exhaustion_reason,
            "usage": {
                "elapsed_seconds": round(elapsed, 1),
                "cost_usd": round(self.accumulated_cost, 6),
                "tokens": self.accumulated_tokens,
            },
            "limits": {
                "duration": self.config.max_duration_seconds,
                "cost": self.config.max_cost_usd,
                "tokens": self.config.max_tokens,
            },
        }


def parse_budget_string(budget_str: str) -> BudgetConfig:
    """解析 CLI 预算字符串 (例如 '1h', '10usd', '1000t')"""
    config = BudgetConfig()
    if not budget_str:
        return config

    import re

    # 解析时间
    time_match = re.search(r"(\d+)h", budget_str)
    if time_match:
        config.max_duration_seconds = int(time_match.group(1)) * 3600
    else:
        min_match = re.search(r"(\d+)m", budget_str)
        if min_match:
            config.max_duration_seconds = int(min_match.group(1)) * 60

    # 解析成本
    cost_match = re.search(r"(\d+(?:\.\d+)?)usd", budget_str.lower())
    if cost_match:
        config.max_cost_usd = float(cost_match.group(1))

    # 解析 Token
    token_match = re.search(r"(\d+)t", budget_str.lower())
    if token_match:
        config.max_tokens = int(token_match.group(1))

    return config
