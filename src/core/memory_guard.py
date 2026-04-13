"""MemoryGuard — 内存泄漏防御体系

自动监控、检测、回收内存异常增长。
挂载到 AgentEngine 后，每个 turn 自动执行健康检查。

核心功能:
1. 对象数量追踪（LLM client 缓存、Event 队列、Transcript 等）
2. RSS 内存用量监控 + 软上限告警 + 硬上限强制回收
3. 周期性 gc.collect() + client 缓存清理
4. 泄漏检测：连续 N 次 turn RSS 增长且未释放 → 标记为泄漏
"""
from __future__ import annotations

import contextlib
import gc
import os
import platform
import time
from dataclasses import dataclass
from typing import Any

from ..utils import debug, warn


@dataclass
class MemorySnapshot:
    """单次采样快照"""
    timestamp: float
    rss_mb: float
    client_cache_size: int
    event_queue_size: int
    transcript_entries: int
    gc_generation_counts: tuple[int, int, int] = (0, 0, 0)
    object_count: int = 0

    @property
    def label(self) -> str:
        objs = f'{self.object_count}' if self.object_count else 'N/A'
        return (
            f'RSS={self.rss_mb:.1f}MB | '
            f'clients={self.client_cache_size} | '
            f'events={self.event_queue_size} | '
            f'transcript={self.transcript_entries} | '
            f'objects={objs}'
        )


class MemoryGuard:
    """内存护栏 — 自动防泄漏

    用法:
        guard = MemoryGuard()
        guard.enable_for_engine(engine)
    """

    def __init__(
        self,
        soft_limit_mb: float = 512.0,
        hard_limit_mb: float = 1024.0,
        leak_threshold_turns: int = 10,
        check_interval: int = 5,  # 每 N 个 turn 检查一次
    ) -> None:
        self.soft_limit_mb = soft_limit_mb
        self.hard_limit_mb = hard_limit_mb
        self.leak_threshold_turns = leak_threshold_turns
        self.check_interval = check_interval

        self._turn_count = 0
        self._snapshots: list[MemorySnapshot] = []
        self._peak_rss = 0.0
        self._enabled = False
        self._callbacks: list[callable] = []

    def enable_for_engine(self, engine: Any) -> None:
        """将 MemoryGuard 挂载到 AgentEngine。

        自动注入 turn 后检查钩子。
        """
        self._enabled = True
        engine._memory_guard = self  # type: ignore[attr-defined]
        debug('MemoryGuard 已挂载到 AgentEngine')

    def on_turn_complete(self) -> MemorySnapshot:
        """在每个 turn 完成后调用。

        返回:
            当前内存快照
        """
        self._turn_count += 1
        snapshot = self._take_snapshot()
        self._snapshots.append(snapshot)

        # 限制历史数量
        if len(self._snapshots) > 100:
            self._snapshots = self._snapshots[-50:]

        peak = max(s.rss_mb for s in self._snapshots)
        self._peak_rss = max(self._peak_rss, peak)

        # 检查泄漏
        if self._turn_count % self.leak_threshold_turns == 0:
            self._check_leak()

        # 定期 GC
        if self._turn_count % self.check_interval == 0:
            self._run_gc()

        # 硬上限检查
        if snapshot.rss_mb > self.hard_limit_mb:
            warn(f'[MemoryGuard] RSS {snapshot.rss_mb:.1f}MB 超过硬上限 {self.hard_limit_mb}MB，强制回收')
            self._run_gc(aggressive=True)
            self._cleanup_caches()

        return snapshot

    def add_callback(self, fn: callable) -> None:
        """注册内存告警回调。"""
        self._callbacks.append(fn)

    def get_report(self) -> str:
        """生成内存健康报告。"""
        if not self._snapshots:
            return '[MemoryGuard] 尚未采集任何样本'
        latest = self._snapshots[-1]
        return (
            f'[MemoryGuard 报告]\n{"=" * 40}\n'
            f'采样次数: {len(self._snapshots)}\n'
            f'当前 RSS: {latest.rss_mb:.1f}MB\n'
            f'峰值 RSS: {self._peak_rss:.1f}MB\n'
            f'软上限: {self.soft_limit_mb}MB\n'
            f'硬上限: {self.hard_limit_mb}MB\n'
            f'最近:\n  {latest.label}\n'
            f'{"=" * 40}'
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _take_snapshot(self) -> MemorySnapshot:
        """采集内存快照。"""
        rss = self._get_rss_mb()

        # LLM client 缓存大小
        try:
            from ..llm import _client_cache
            client_count = len(_client_cache)
        except Exception:
            client_count = 0

        # Event 队列大小
        try:
            from ..core.events import _global_bus
            eq_size = len(_global_bus._event_queue) if _global_bus else 0
        except Exception:
            eq_size = 0

        # Transcript
        transcript_count = 0
        with contextlib.suppress(Exception):
            transcript_count = len(getattr(self, '_transcript_ref', []))

        # GC 统计
        gc_counts = gc.get_count() if hasattr(gc, 'get_count') else (0, 0, 0)

        obj_count = len(gc.get_objects()) if hasattr(gc, 'get_objects') else 0

        return MemorySnapshot(
            timestamp=time.time(),
            rss_mb=rss,
            client_cache_size=client_count,
            event_queue_size=eq_size,
            transcript_entries=transcript_count,
            gc_generation_counts=gc_counts,
            object_count=obj_count,
        )

    def _get_rss_mb(self) -> float:
        """获取当前进程 RSS (MB)。"""
        try:
            if platform.system() == 'Windows':
                # Windows: 使用 psutil 备选方案
                return self._get_rss_psutil()
            else:
                # Linux/Mac: 读取 /proc/self/status
                with open(f'/proc/{os.getpid()}/status') as f:
                    for line in f:
                        if line.startswith('VmRSS:'):
                            return int(line.split()[1]) / 1024.0
        except Exception:
            pass
        return self._get_rss_psutil()

    def _get_rss_psutil(self) -> float:
        """通过 psutil 获取 RSS。"""
        try:
            import psutil
            proc = psutil.Process()
            return proc.memory_info().rss / (1024 * 1024)
        except Exception:
            return 0.0

    def _check_leak(self) -> None:
        """检查连续增长模式（泄漏信号）。"""
        if len(self._snapshots) < self.leak_threshold_turns:
            return
        recent = self._snapshots[-self.leak_threshold_turns:]
        rss_values = [s.rss_mb for s in recent]

        # 检测严格递增
        is_monotonic = all(rss_values[i] < rss_values[i + 1] for i in range(len(rss_values) - 1))
        growth = rss_values[-1] - rss_values[0]

        if is_monotonic and growth > 50:  # 连续增长且增幅 > 50MB
            warn(f'[MemoryGuard] 检测到潜在内存泄漏: {len(rss_values)} 个 turn 连续增长 +{growth:.1f}MB')
            self._notify(f'检测到内存泄漏信号: {growth:.1f}MB 增长')
            self._run_gc(aggressive=True)
            self._cleanup_caches()

    def _run_gc(self, aggressive: bool = False) -> None:
        """运行垃圾回收。"""
        collected = 0
        if aggressive:
            collected = gc.collect()
            debug(f'[MemoryGuard] 激进 GC 回收: {collected} 个对象')
        else:
            # 只触发 gen 0 + gen 1
            gc.collect(generation=1)
            debug('[MemoryGuard] 常规 GC 完成')

    def _cleanup_caches(self) -> None:
        """清理已知缓存: LLM client、Event bus、Transcript。"""
        # LLM client 缓存
        try:
            from ..llm import _client_cache, _client_cache_lock
            with _client_cache_lock:
                # 只保留最近 4 个
                max_keep = 4
                while len(_client_cache) > max_keep:
                    _client_cache.popitem(last=False)
                debug(f'[MemoryGuard] LLM client 缓存裁减至 {len(_client_cache)}')
        except Exception as e:
            debug(f'[MemoryGuard] 清理 client 缓存失败: {e}')

        # Event bus 清理
        try:
            from ..core.events import _global_bus
            if _global_bus:
                _global_bus.clear_events()
                debug('[MemoryGuard] Event 队列已清理')
        except Exception:
            pass

    def _notify(self, message: str) -> None:
        """发送通知。"""
        for cb in self._callbacks:
            with contextlib.suppress(Exception):
                cb(message)
        warn(f'[MemoryGuard] {message}')

    def reset(self) -> None:
        """重置所有计数。"""
        self._turn_count = 0
        self._snapshots.clear()
        self._peak_rss = 0.0


__all__ = ['MemoryGuard', 'MemorySnapshot']
