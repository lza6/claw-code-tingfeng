"""线程池工具测试 - 覆盖 src/utils/threadpool_utils.py"""

import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from src.utils.threadpool_utils import (
    ThreadSafeDict,
    ThreadSafeSet,
    FunctionCall,
    run_functions_tuples_in_parallel,
    run_functions_in_parallel,
    run_async_sync_no_cancel,
    run_multiple_in_background,
    parallel_yield,
)


class TestThreadSafeDict:
    """线程安全字典测试"""

    def test_init_empty(self):
        """测试空初始化"""
        d = ThreadSafeDict()
        assert len(d) == 0

    def test_init_with_data(self):
        """测试带数据初始化"""
        d = ThreadSafeDict({"a": 1, "b": 2})
        assert len(d) == 2

    def test_setitem_getitem(self):
        """测试设置和获取"""
        d = ThreadSafeDict()
        d["key"] = "value"
        assert d["key"] == "value"

    def test_get_with_default(self):
        """测试带默认值的 get"""
        d = ThreadSafeDict()
        assert d.get("missing", "default") == "default"

    def test_pop(self):
        """测试 pop"""
        d = ThreadSafeDict({"a": 1})
        val = d.pop("a")
        assert val == 1
        assert "a" not in d

    def test_pop_with_default(self):
        """测试带默认值的 pop"""
        d = ThreadSafeDict()
        val = d.pop("missing", 42)
        assert val == 42

    def test_update(self):
        """测试 update"""
        d = ThreadSafeDict({"a": 1})
        d.update({"b": 2})
        assert d["b"] == 2

    def test_clear(self):
        """测试 clear"""
        d = ThreadSafeDict({"a": 1})
        d.clear()
        assert len(d) == 0

    def test_copy(self):
        """测试 copy"""
        d = ThreadSafeDict({"a": 1})
        c = d.copy()
        assert c == {"a": 1}

    def test_setdefault(self):
        """测试 setdefault"""
        d = ThreadSafeDict()
        val = d.setdefault("key", "value")
        assert val == "value"
        assert d["key"] == "value"

    def test_contains(self):
        """测试 contains"""
        d = ThreadSafeDict({"a": 1})
        assert "a" in d
        assert "b" not in d


class TestThreadSafeSet:
    """线程安全集合测试"""

    def test_init_empty(self):
        """测试空初始化"""
        s = ThreadSafeSet()
        assert len(s) == 0

    def test_init_with_data(self):
        """测试带数据初始化"""
        s = ThreadSafeSet({1, 2, 3})
        assert len(s) == 3

    def test_add(self):
        """测试添加"""
        s = ThreadSafeSet()
        s.add("item")
        assert "item" in s

    def test_remove(self):
        """测试移除"""
        s = ThreadSafeSet({"item"})
        s.remove("item")
        assert "item" not in s

    def test_discard(self):
        """测试 discard"""
        s = ThreadSafeSet({"item"})
        s.discard("item")
        assert "item" not in s
        s.discard("missing")  # 不抛异常

    def test_check_and_add_new(self):
        """测试 check_and_add 新元素"""
        s = ThreadSafeSet()
        result = s.check_and_add("new")
        assert result is False
        assert "new" in s

    def test_check_and_add_existing(self):
        """测试 check_and_add 已存在元素"""
        s = ThreadSafeSet({"existing"})
        result = s.check_and_add("existing")
        assert result is True

    def test_clear(self):
        """测试 clear"""
        s = ThreadSafeSet({1, 2, 3})
        s.clear()
        assert len(s) == 0


class TestRunFunctionsTuplesInParallel:
    """并行函数执行测试"""

    def test_empty_list(self):
        """测试空列表"""
        results = run_functions_tuples_in_parallel([])
        assert results == []

    def test_single_function(self):
        """测试单个函数"""
        results = run_functions_tuples_in_parallel([(lambda: 42, ())])
        assert results == [42]

    def test_multiple_functions(self):
        """测试多个函数"""
        funcs = [
            (lambda: 1, ()),
            (lambda: 2, ()),
            (lambda: 3, ()),
        ]
        results = run_functions_tuples_in_parallel(funcs)
        assert results == [1, 2, 3]

    def test_with_args(self):
        """测试带参数"""

        def add(a, b):
            return a + b

        funcs = [(add, (1, 2)), (add, (3, 4))]
        results = run_functions_tuples_in_parallel(funcs)
        assert results == [3, 7]

    def test_allow_failures(self):
        """测试允许失败"""

        def fail():
            raise ValueError("error")

        funcs = [
            (lambda: 1, ()),
            (fail, ()),
        ]
        results = run_functions_tuples_in_parallel(funcs, allow_failures=True)
        assert results[0] == 1
        assert results[1] is None


class TestFunctionCall:
    """FunctionCall 测试"""

    def test_execute(self):
        """测试执行"""

        def add(a, b):
            return a + b

        fc = FunctionCall(add, (1, 2))
        result = fc.execute()
        assert result == 3


class TestRunFunctionsInParallel:
    """并行函数列表执行测试"""

    def test_empty_list(self):
        """测试空列表"""
        results = run_functions_in_parallel([])
        assert results == {}

    def test_single_function(self):
        """测试单个函数"""
        calls = [FunctionCall(lambda: 42)]
        results = run_functions_in_parallel(calls)
        assert len(results) == 1


class TestRunAsyncSyncNoCancel:
    """async-to-sync 测试"""

    def test_basic(self):
        """测试基本功能"""

        async def coro():
            return 42

        result = run_async_sync_no_cancel(coro())
        assert result == 42


class TestRunMultipleInBackground:
    """后台执行测试"""

    def test_basic(self):
        """测试基本功能"""
        results = []

        def func():
            results.append(1)

        executor = run_multiple_in_background([func])
        time.sleep(0.1)
        executor.shutdown(wait=True)
        assert 1 in results


class TestParallelYield:
    """并行 yield 测试"""

    def test_empty(self):
        """测试空生成器"""
        result = list(parallel_yield([]))
        assert result == []

    def test_single_generator(self):
        """测试单个生成器"""
        gen = (i for i in range(3))
        result = list(parallel_yield([gen]))
        assert result == [0, 1, 2]

    def test_multiple_generators(self):
        """测试多个生成器"""
        gens = [(i for i in range(2)) for _ in range(2)]
        result = list(parallel_yield(gens))
        assert len(result) == 4