"""`--dimension/-d` → 运行时配置 → 提示词 的接线回归测试。

## 背景

CLI 的 `run` 命令支持 `-d/--dimension creative --dimension adversarial`，
实现是 `set_config("dimensions", dimensions)`。但**全仓库没有任何代码读取
这个键** —— 用户传了参数，工作流的提示词里一个字都不会变。

这是一条"界面有、后端没有"的典型断链：参数被接受、被存储，然后被遗忘。

## 本测试断言什么

不是"函数存在"，而是**同一条链路真的连通**：

1. `set_config("dimensions", [...])` 后，引擎能解析出非空的引导文本
2. 引导文本里包含维度名称与指导语
3. 执行器（HealableExecutor）拿到同一份引导
4. 未配置维度时，引导为空、执行器提示词不被污染（回归）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.config.injector import set_config
from src.workflow.engine import WorkflowEngine
from src.workflow.healable_executor import HealableExecutor


@pytest.fixture
def engine(tmp_path: Path) -> WorkflowEngine:
    return WorkflowEngine(workdir=tmp_path, max_iterations=1)


@pytest.fixture(autouse=True)
def _restore_runtime_dimensions():
    """隔离进程级运行时配置。

    `set_config("dimensions", ...)` 写的是**进程全局**覆盖。
    若不恢复，后续所有测试里的 WorkflowEngine 都会带着维度引导运行 ——
    实测会让 `tests/workflow/test_workflow.py::test_run_with_code` 变红
    （且单独跑该文件时是绿的，属于典型的跨文件状态泄漏）。

    与 `tests/agent/test_approval_gate.py` 对 `_ALLOWED_WORKDIRS`
    的处理同一模式。
    """
    from src.core.config.injector import set_config
    from src.core.config.runtime import get_runtime_config

    saved = get_runtime_config("dimensions", None)
    try:
        yield
    finally:
        # 只回滚 dimensions 这一个键，不要调用 clear_runtime_overrides()
        # ——那会连带清掉其它测试设置的无关键位。
        set_config("dimensions", saved if saved is not None else [])


class TestDimensionWiring:
    def test_no_dimensions_yields_empty_guidance(self, engine):
        set_config("dimensions", [])
        assert engine._resolve_dimension_guidance() == ""

    def test_configured_dimensions_produce_guidance(self, engine):
        set_config("dimensions", ["creative", "adversarial"])
        text = engine._resolve_dimension_guidance()

        assert text, "配置了维度却没有产出任何引导文本"
        assert "creative" in text.lower()
        assert "adversarial" in text.lower()
        # 内置库里的实际指导语应被带出，而不是只回显名字
        assert len(text) > 60

    def test_comma_separated_string_is_accepted(self, engine):
        """配置文件里常写成 `dimensions = "creative,adversarial"`"""
        set_config("dimensions", "creative,adversarial")
        text = engine._resolve_dimension_guidance()
        assert "creative" in text.lower()
        assert "adversarial" in text.lower()

    def test_unknown_dimension_does_not_crash(self, engine):
        set_config("dimensions", ["__不存在的维度__"])
        # 不抛异常即可；解析器可自行忽略未知项
        engine._resolve_dimension_guidance()

    def test_guidance_reaches_executor(self, engine):
        set_config("dimensions", ["security"])
        engine._dimension_guidance = engine._resolve_dimension_guidance()
        executor = engine._get_executor()
        assert executor.dimension_guidance == engine._dimension_guidance
        assert "security" in executor.dimension_guidance.lower()

    def test_executor_without_guidance_is_unchanged(self, tmp_path):
        """未配置维度时，执行器不得给任务描述加任何前缀"""
        ex = HealableExecutor(workdir=tmp_path)
        assert ex.dimension_guidance == ""
