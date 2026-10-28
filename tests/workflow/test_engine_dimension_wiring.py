"""WorkflowEngine 维度引导接线测试

背景（2026-10-28）：CLI `--dimension/-d` 把维度写入运行期配置，但此前没有任何消费者
——`src/workflow/dimensions.py` 的 resolve/get_dimensions_prompt 从未被调用，
形成"假开关"（帮助里说有维度引导，实际毫无作用）。本测试锁定接线后的行为。
"""

from pathlib import Path

import pytest

from src.core.config.injector import get_config_injector
from src.workflow.engine import WorkflowEngine


@pytest.fixture
def engine(tmp_path: Path):
    injector = get_config_injector()
    injector.clear_runtime_overrides()
    yield WorkflowEngine(workdir=tmp_path)
    injector.clear_runtime_overrides()


def test_no_dimensions_returns_goal_unchanged(engine):
    assert engine._inject_dimension_guidance("实现登录") == "实现登录"


def test_dimensions_appended_to_goal(engine):
    get_config_injector().set("dimensions", ["creative", "audit"])

    out = engine._inject_dimension_guidance("实现登录")

    assert out.startswith("实现登录")
    assert "Dimension Guidance" in out
    assert len(out) > len("实现登录")


def test_dimensions_accepts_comma_separated_string(engine):
    get_config_injector().set("dimensions", "creative, adversarial")

    out = engine._inject_dimension_guidance("目标")

    assert "Dimension Guidance" in out


def test_unknown_dimension_degrades_gracefully(engine):
    """未知维度不得抛错，也不得破坏 goal。"""
    get_config_injector().set("dimensions", ["not-a-real-dimension"])

    out = engine._inject_dimension_guidance("目标")

    assert out.startswith("目标")


def test_empty_list_returns_goal_unchanged(engine):
    get_config_injector().set("dimensions", [])
    assert engine._inject_dimension_guidance("目标") == "目标"
