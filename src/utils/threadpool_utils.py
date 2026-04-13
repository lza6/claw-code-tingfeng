"""线程池工具 — 借鉴 Onyx threadpool_concurrency.py

增强特性:
- contextvars 跨线程传播（保持租户ID、请求上下文等）
- 并行执行函数元组（保留结果顺序）
- parallel_yield 多生成器并行消费
- 超时控制与回调
- 线程安全集合类型

用法:
    from src.utils.threadpool_utils import run_functions_tuples_in_parallel

    results = run_functions_tuples_in_parallel([
        (func1, (arg1,)),
        (func2, (arg2, arg3)),
    ])
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import copy
import threading
import uuid
from collections.abc import Awaitable, Callable, Iterator, MutableMapping, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from typing import Any, Generic, Protocol, TypeVar

from src.utils.logger import get_logger

logger = get_logger(__name__)

R = TypeVar("R")
KT = TypeVar("KT")  # Key type
VT = TypeVar("VT")  # Value type
_T = TypeVar("_T")  # Default type


class ThreadSafeDict(MutableMapping[KT, VT]):
    """线程安全字典 — 实现 MutableMapping 接口

    参考 Onyx ThreadSafeDict 设计。
    所有操作都是原子的，适用于多线程共享状态场景。

    用法:
        safe_dict: ThreadSafeDict[str, int] = ThreadSafeDict()
        safe_dict["key"] = 1
        value = safe_dict["key"]
    """

    def __init__(self, input_dict: dict[KT, VT] | None = None) -> None:
        self._dict: dict[KT, VT] = input_dict or {}
        self._lock = threading.Lock()

    def __getitem__(self, key: KT) -> VT:
        with self._lock:
            return self._dict[key]

    def __setitem__(self, key: KT, value: VT) -> None:
        with self._lock:
            self._dict[key] = value

    def __delitem__(self, key: KT) -> None:
        with self._lock:
            del self._dict[key]

    def __iter__(self) -> Iterator[KT]:
        with self._lock:
            return iter(list(self._dict.keys()))

    def __len__(self) -> int:
        with self._lock:
            return len(self._dict)

    def clear(self) -> None:
        """原子清除所有项"""
        with self._lock:
            self._dict.clear()

    def copy(self) -> dict[KT, VT]:
        """原子浅拷贝"""
        with self._lock:
            return self._dict.copy()

    def get(self, key: KT, default: VT | _T | None = None) -> VT | _T | None:  # type: ignore[override]
        """原子获取值"""
        with self._lock:
            return self._dict.get(key, default)

    def pop(self, key: KT, default: Any = None) -> Any:
        """原子弹出值"""
        with self._lock:
            if default is None:
                return self._dict.pop(key)
            return self._dict.pop(key, default)

    def setdefault(self, key: KT, default: VT) -> VT:
        """原子设置默认值"""
        with self._lock:
            return self._dict.setdefault(key, default)

    def update(self, *args: Any, **kwargs: VT) -> None:
        """原子更新"""
        with self._lock:
            self._dict.update(*args, **kwargs)

    def __deepcopy__(self, memo: Any) -> ThreadSafeDict[KT, VT]:
        return ThreadSafeDict(copy.deepcopy(self._dict))


class ThreadSafeSet(Generic[R]):
    """线程安全集合 — 支持原子 check-and-add

    参考 Onyx ThreadSafeSet 设计。
    check_and_add 方法防止竞态条件。

    用法:
        safe_set: ThreadSafeSet[str] = ThreadSafeSet()
        safe_set.add("item")
        was_present = safe_set.check_and_add("item")
    """

    def __init__(self, input_set: set[R] | None = None) -> None:
        self._set: set[R] = input_set.copy() if input_set else set()
        self._lock = threading.Lock()

    def __contains__(self, item: R) -> bool:
        with self._lock:
            return item in self._set

    def __len__(self) -> int:
        with self._lock:
            return len(self._set)

    def __iter__(self) -> Iterator[R]:
        with self._lock:
            return iter(list(self._set))

    def add(self, item: R) -> None:
        """原子添加"""
        with self._lock:
            self._set.add(item)

    def discard(self, item: R) -> None:
        """原子丢弃"""
        with self._lock:
            self._set.discard(item)

    def remove(self, item: R) -> None:
        """原子移除（不存在则抛异常）"""
        with self._lock:
            self._set.remove(item)

    def clear(self) -> None:
        """原子清除"""
        with self._lock:
            self._set.clear()

    def copy(self) -> set[R]:
        """原子浅拷贝"""
        with self._lock:
            return self._set.copy()

    def update(self, *others: set[R]) -> None:
        """原子合并其他集合"""
        with self._lock:
            for other in others:
                self._set.update(other)

    def check_and_add(self, item: R) -> bool:
        """原子检查并添加

        返回 True 如果已存在，False 如果是新添加。
        防止 check-then-add 竞态条件。
        """
        with self._lock:
            if item in self._set:
                return True
            self._set.add(item)
            return False

    def __deepcopy__(self, memo: Any) -> ThreadSafeSet[R]:
        with self._lock:
            return ThreadSafeSet(copy.deepcopy(self._set))


class CallableProtocol(Protocol):
    """可调用协议"""
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


def run_functions_tuples_in_parallel(
    functions_with_args: Sequence[tuple[CallableProtocol, tuple[Any, ...]]],
    allow_failures: bool = False,
    max_workers: int | None = None,
    timeout: float | None = None,
    timeout_callback: (
        Callable[[int, CallableProtocol, tuple[Any, ...]], Any] | None
    ) = None,
) -> list[Any]:
    """并行执行多个函数（带 contextvars 传播）

    参考 Onyx run_functions_tuples_in_parallel 设计。

    关键特性:
    1. contextvars 跨线程传播（保持租户ID、请求上下文等）
    2. 结果按输入顺序返回
    3. 支持超时和超时回调
    4. 可选允许部分失败

    Args:
        functions_with_args: [(func, args), ...] 列表
        allow_failures: 是否允许部分失败
        max_workers: 最大线程数
        timeout: 墙钟超时（秒）
        timeout_callback: 超时回调 (index, func, args) -> result

    Returns:
        结果列表（与输入顺序一致）

    Raises:
        Exception: 当 allow_failures=False 且函数失败时
        TimeoutError: 当超时且无回调时
    """
    workers = (
        min(max_workers, len(functions_with_args))
        if max_workers is not None
        else len(functions_with_args)
    )

    if workers <= 0:
        return []

    results: list[tuple[int, Any]] = []
    executor = ThreadPoolExecutor(max_workers=workers)

    try:
        # contextvars 传播是关键 — 保持租户ID等上下文
        future_to_index = {
            executor.submit(contextvars.copy_context().run, func, *args): i
            for i, (func, args) in enumerate(functions_with_args)
        }

        if timeout is not None:
            done, not_done = wait(future_to_index.keys(), timeout=timeout)

            for future in done:
                index = future_to_index[future]
                try:
                    results.append((index, future.result()))
                except Exception as e:
                    logger.warning(f"Function at index {index} failed: {e}")
                    results.append((index, None))
                    if not allow_failures:
                        raise

            for future in not_done:
                index = future_to_index[future]
                func, args = functions_with_args[index]
                logger.warning(
                    f"Function at index {index} timed out after {timeout}s"
                )

                if timeout_callback:
                    timeout_result = timeout_callback(index, func, args)
                    results.append((index, timeout_result))
                else:
                    results.append((index, None))
                    if not allow_failures:
                        raise TimeoutError(
                            f"Function at index {index} timed out after {timeout}s"
                        )
                future.cancel()
        else:
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    results.append((index, future.result()))
                except Exception as e:
                    logger.warning(f"Function at index {index} failed: {e}")
                    results.append((index, None))
                    if not allow_failures:
                        raise
    finally:
        executor.shutdown(wait=(timeout is None))

    results.sort(key=lambda x: x[0])
    return [result for index, result in results]


class FunctionCall(Generic[R]):
    """并行执行函数容器

    用于 run_functions_in_parallel，通过 result_id 获取结果。
    """

    def __init__(
        self, func: Callable[..., R], args: tuple = (), kwargs: dict | None = None
    ):
        self.func = func
        self.args = args
        self.kwargs = kwargs if kwargs is not None else {}
        self.result_id = str(uuid.uuid4())

    def execute(self) -> R:
        return self.func(*self.args, **self.kwargs)


def run_functions_in_parallel(
    function_calls: list[FunctionCall],
    allow_failures: bool = False,
) -> dict[str, Any]:
    """并行执行 FunctionCall 列表

    Args:
        function_calls: FunctionCall 列表
        allow_failures: 是否允许部分失败

    Returns:
        {result_id: result, ...} 字典
    """
    results: dict[str, Any] = {}

    if not function_calls:
        return results

    with ThreadPoolExecutor(max_workers=len(function_calls)) as executor:
        future_to_id = {
            executor.submit(
                contextvars.copy_context().run, func_call.execute
            ): func_call.result_id
            for func_call in function_calls
        }

        for future in as_completed(future_to_id):
            result_id = future_to_id[future]
            try:
                results[result_id] = future.result()
            except Exception as e:
                logger.warning(f"Function {result_id} failed: {e}")
                results[result_id] = None
                if not allow_failures:
                    raise

    return results


def run_async_sync_no_cancel(coro: Awaitable[T]) -> T:
    """async-to-sync 转换器

    在独立线程中执行 asyncio.run。
    注意：线程不会取消，会继续运行完成。
    """
    context = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future: concurrent.futures.Future[T] = executor.submit(
            context.run,  # type: ignore[arg-type]
            asyncio.run,
            coro,
        )
        return future.result()


def run_multiple_in_background(
    funcs: list[Callable[[], None]],
    thread_name_prefix: str = "worker",
) -> ThreadPoolExecutor:
    """在后台执行多个函数（带 contextvars 传播）

    复制当前 contextvars 一次，所有函数在该副本中运行。
    返回执行器，调用方负责 shutdown()。

    Args:
        funcs: 要执行的函数列表
        thread_name_prefix: 线程名前缀

    Returns:
        ThreadPoolExecutor 实例
    """
    ctx = contextvars.copy_context()
    executor = ThreadPoolExecutor(
        max_workers=len(funcs), thread_name_prefix=thread_name_prefix
    )
    for func in funcs:
        executor.submit(ctx.run, func)
    return executor


def _next_or_none(ind: int, gen: Iterator[R]) -> tuple[int, R | None]:
    return ind, next(gen, None)


def parallel_yield(gens: list[Iterator[R]], max_workers: int = 10) -> Iterator[R]:
    """并行消费多个生成器

    参考 Onyx parallel_yield 设计。
    线程级并行执行生成器，结果可用时即 yield。

    注意:
        提前停止迭代器不保证输入生成器也停止。
        仅在消费所有元素或可接受额外元素时使用。

    Args:
        gens: 生成器列表
        max_workers: 最大线程数

    Yields:
        生成器产生的元素
    """
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index: dict[concurrent.futures.Future[tuple[int, R | None]], int] = {
            executor.submit(_next_or_none, ind, gen): ind
            for ind, gen in enumerate(gens)
        }

        next_ind = len(gens)
        while future_to_index:
            done, _ = wait(future_to_index, return_when=FIRST_COMPLETED)
            for future in done:
                ind, result = future.result()
                if result is not None:
                    yield result
                    future_to_index[executor.submit(_next_or_none, ind, gens[ind])] = (
                        next_ind
                    )
                    next_ind += 1
                del future_to_index[future]


def parallel_yield_from_funcs(
    funcs: list[Callable[..., Iterator[R]]],
    max_workers: int = 10,
) -> Iterator[R]:
    """并行执行多个生成器函数

    Args:
        funcs: 返回生成器的函数列表
        max_workers: 最大线程数

    Yields:
        生成器产生的元素
    """
    def func_wrapper(func: Callable[..., Iterator[R]]) -> Iterator[R]:
        yield from func()

    yield from parallel_yield(
        [func_wrapper(func) for func in funcs], max_workers=max_workers
    )


__all__ = [
    "CallableProtocol",
    "FunctionCall",
    "ThreadSafeDict",
    "ThreadSafeSet",
    "parallel_yield",
    "parallel_yield_from_funcs",
    "run_async_sync_no_cancel",
    "run_functions_in_parallel",
    "run_functions_tuples_in_parallel",
    "run_multiple_in_background",
]
