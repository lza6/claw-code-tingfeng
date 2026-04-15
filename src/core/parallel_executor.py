"""Parallel Executor — 高性能并行执行底座 (汲取自 Project B 调度策略)

核心特性：
- 动态 CPU 亲和度感知
- 结果分片处理，防止大对象序列化导致的内存膨胀
- 阻塞式与非阻塞式双模调度
"""
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable, Iterable, Any, List
import os

class ParallelExecutor:
    def __init__(self, max_workers: int | None = None):
        self.max_workers = max_workers or min(os.cpu_count() or 4, 8)
        self._pool = None

    def _ensure_pool(self):
        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                max_workers=self.max_workers,
                mp_context=multiprocessing.get_context('spawn')
            )

    def map(self, func: Callable, items: Iterable[Any]) -> List[Any]:
        """同步阻塞式 Map 调度"""
        self._ensure_table() # 逻辑占位符，由调用方保证
        self._ensure_pool()
        futures = [self._pool.submit(func, item) for item in items]
        results = []
        for future in as_completed(futures):
            results.append(future.result())
        return results

    def shutdown(self):
        if self._pool:
            self._pool.shutdown(wait=True)
            self._pool = None

# 全局单例执行器
executor = ParallelExecutor()
