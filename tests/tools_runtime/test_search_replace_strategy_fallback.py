"""`try_strategy` 的策略级异常回退回归。

## 背景

`try_strategy` 原先只捕获 `(ValueError, IndexError, OSError)`。
`git_cherry_pick_osr_onto_o` 在**非 git 目录**会抛
`git.exc.InvalidGitRepositoryError`（不是 OSError）—— 直接穿透，
导致"多策略自动回退"在非仓库目录下彻底失效，编辑失败。

该修复此前**没有任何测试**（现有 search_replace 测试都走精确匹配路径，
永远到不了 git 策略）。本文件锁定：
- 普通策略异常 → 返回失败，不向上抛
- 错误里带异常类型，便于定位"策略写错了"
- MemoryError / RecursionError 仍向上抛（资源级问题不能被降级）
"""
from __future__ import annotations

import pytest

from src.tools_runtime.search_replace import try_strategy

PREPROC = (False, False, False)


class Boom(Exception):
    pass


class TestStrategyFallback:
    def test_strategy_exception_returns_failure_not_raises(self):
        def boom(content, search, replace):
            raise Boom("strategy exploded")

        result = try_strategy("content", "search", "replace", boom, PREPROC)
        assert result.success is False
        assert "Boom" in (result.error or "")

    def test_error_includes_exception_type(self):
        def bad(content, search, replace):
            raise TypeError("programming error")

        result = try_strategy("content", "search", "replace", bad, PREPROC)
        assert result.success is False
        assert "TypeError" in (result.error or "")

    def test_value_error_still_means_no_match(self):
        def no_match(content, search, replace):
            raise ValueError("not found")

        result = try_strategy("content", "search", "replace", no_match, PREPROC)
        assert result.success is False
        assert result.error == "未找到匹配"

    @pytest.mark.parametrize("exc", [MemoryError, RecursionError])
    def test_resource_errors_propagate(self, exc):
        def fatal(content, search, replace):
            raise exc("fatal")

        with pytest.raises(exc):
            try_strategy("content", "search", "replace", fatal, PREPROC)

    def test_successful_strategy_returns_content(self):
        def ok(content, search, replace):
            return content.replace(search, replace)

        result = try_strategy("hello world", "world", "there", ok, PREPROC)
        assert result.success is True
        assert result.content == "hello there"

    def test_non_git_directory_does_not_abort_matrix(self, tmp_path):
        """真实场景：在非 git 目录调用 git 策略，不得让整个回退中断。

        直接驱动 `flexible_search_and_replace`：精确匹配失败时应继续尝试
        其它策略，最终以明确的 ValueError 结束，而不是抛
        InvalidGitRepositoryError。
        """
        from src.tools_runtime.search_replace import flexible_search_and_replace

        with pytest.raises(ValueError):
            flexible_search_and_replace(
                "some content\n", "nothing-like-this", "x\n"
            )
