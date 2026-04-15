from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ...core.experience_bank import ExperienceBank
from ...core.telemetry.monitoring import MonitoringSystem
from ...self_healing.engine import SelfHealingEngine

logger = logging.getLogger(__name__)


@dataclass
class OptimizationTask:
    """优化任务"""
    id: str
    target: str
    issue_type: str
    context: dict[str, Any] = field(default_factory=dict)
    priority: int = 1
    created_at: float = field(default_factory=time.time)


class IterativeOptimizer:
    """自主迭代优化引擎

    职责:
    - 持续监控系统健康状态
    - 自动识别性能瓶颈和重复错误
    - 驱动 Self-Healing 引擎进行自主修复和优化
    - 演化代码库，实现“无需干预”的自我提升
    """

    def __init__(
        self,
        monitoring: MonitoringSystem | None = None,
        self_healing: SelfHealingEngine | None = None,
        experience_bank: ExperienceBank | None = None,
        interval: int = 300,  # 5 分钟检查一次
    ) -> None:
        self.monitoring = monitoring or MonitoringSystem()
        self.self_healing = self_healing or SelfHealingEngine()
        self.experience_bank = experience_bank or ExperienceBank()
        self.interval = interval
        self._running = False
        self._task_queue: asyncio.PriorityQueue[OptimizationTask] = asyncio.PriorityQueue()
        self._background_tasks: set[asyncio.Task] = set()

        # 诊断: 打印经验库路径
        if hasattr(self.experience_bank, '_storage_path'):
            logger.info(f"经验库存储路径: {self.experience_bank._storage_path}")

    async def start(self) -> None:
        """启动优化循环"""
        if self._running:
            return
        self._running = True
        logger.info("自主迭代优化引擎已启动")

        t1 = asyncio.create_task(self._monitor_loop())
        t2 = asyncio.create_task(self._execution_loop())
        self._background_tasks.add(t1)
        self._background_tasks.add(t2)
        t1.add_done_callback(self._background_tasks.discard)
        t2.add_done_callback(self._background_tasks.discard)

    async def stop(self) -> None:
        """停止优化循环"""
        self._running = False
        logger.info("自主迭代优化引擎已停止")

    async def _monitor_loop(self) -> None:
        """监控循环: 识别优化机会"""
        while self._running:
            try:
                logger.info("--- 开始优化监控周期 ---")
                # 0. 重新加载经验库 (确保读取到最新记录)
                if hasattr(self.experience_bank, 'load'):
                    count = await asyncio.to_thread(self.experience_bank.load)
                    logger.info(f"经验库已重载: {count} 条记录")

                # 1. 检查性能瓶颈
                metrics = self.monitoring.get_recent_metrics(duration=3600)
                logger.info(f"性能指标分析: 找到 {len(metrics)} 个潜在瓶颈")
                for metric in metrics:
                    if metric.get("latency", 0) > 1000:  # 延迟超过 1s
                        logger.info(f"创建性能优化任务: {metric.get('operation')}")
                        await self._queue_task(
                            OptimizationTask(
                                id=f"perf_{int(time.time())}",
                                target=metric.get("operation", "unknown"),
                                issue_type="performance_bottleneck",
                                context=metric,
                                priority=2
                            )
                        )

                # 2. 检查高频错误
                stats = self.experience_bank.get_stats()
                by_cat = stats.get('by_category', {})
                logger.info(f"高频错误分析: {by_cat}")
                for cat, count in by_cat.items():
                    if count > 5:  # 同一类型错误出现超过 5 次
                        logger.info(f"检测到高频错误: {cat} ({count} 次)，准备创建优化任务")
                        await self._queue_task(
                            OptimizationTask(
                                id=f"err_{cat}_{int(time.time())}",
                                target=cat,
                                issue_type="recurrent_error",
                                context={"count": count},
                                priority=3
                            )
                        )

            except Exception as e:
                logger.error(f"优化监控循环出错: {e}")

            await asyncio.sleep(self.interval)

    async def _execution_loop(self) -> None:
        """执行循环: 应用修复和优化"""
        while self._running:
            try:
                # 获取高优先级任务
                task = await self._task_queue.get()
                logger.info(f"开始处理优化任务: {task.issue_type} -> {task.target}")

                # 驱动 Self-Healing 进行修复
                success = await self.self_healing.heal_autonomous(
                    target=task.target,
                    issue_type=task.issue_type,
                    context=task.context
                )

                if success:
                    logger.info(f"任务处理成功: {task.id}")
                else:
                    logger.warning(f"任务处理失败: {task.id}")

                self._task_queue.task_done()

            except Exception as e:
                logger.error(f"优化执行循环出错: {e}")

            await asyncio.sleep(10)

    async def _queue_task(self, task: OptimizationTask) -> None:
        """将任务加入队列"""
        logger.debug(f"尝试入队任务: {task.id}")
        # 简单查重
        await self._task_queue.put(task)
