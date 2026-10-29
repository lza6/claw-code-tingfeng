"""任务依赖图校验测试（回归：悬空依赖曾只 warning 后继续排序）

原实现遇到"依赖不存在的任务 id"只记一条 warning 就继续拓扑排序，
执行顺序会静默失真。计划由模型生成，静默容忍比报错危险 —— 现在必须抛错。
"""

from __future__ import annotations

import pytest

from src.workflow.models import WorkflowPhase, WorkflowTask
from src.workflow.task_planner import TaskPlanner


def _task(task_id: str, depends_on: list[str] | None = None) -> WorkflowTask:
    return WorkflowTask(
        task_id=task_id,
        phase=WorkflowPhase.PLAN,
        title=f"任务 {task_id}",
        description="d",
        depends_on=depends_on or [],
    )


class TestDependencyValidation:
    def test_linear_chain_sorted(self):
        tasks = [_task("c", ["b"]), _task("b", ["a"]), _task("a")]
        ordered = TaskPlanner.validate_and_sort_dependencies(tasks)
        assert [t.task_id for t in ordered] == ["a", "b", "c"]

    def test_dangling_dependency_raises(self):
        tasks = [_task("a"), _task("b", ["ghost"])]
        with pytest.raises(ValueError, match="悬空依赖"):
            TaskPlanner.validate_and_sort_dependencies(tasks)

    def test_dangling_message_names_both_sides(self):
        tasks = [_task("a"), _task("b", ["ghost"])]
        with pytest.raises(ValueError) as exc:
            TaskPlanner.validate_and_sort_dependencies(tasks)
        message = str(exc.value)
        assert "b -> ghost" in message
        assert "a" in message

    def test_self_cycle_raises(self):
        tasks = [_task("a", ["a"])]
        with pytest.raises(ValueError):
            TaskPlanner.validate_and_sort_dependencies(tasks)

    def test_mutual_cycle_raises(self):
        tasks = [_task("a", ["b"]), _task("b", ["a"])]
        with pytest.raises(ValueError, match="循环依赖"):
            TaskPlanner.validate_and_sort_dependencies(tasks)

    def test_empty_input_returns_empty(self):
        assert TaskPlanner.validate_and_sort_dependencies([]) == []

    def test_multiple_dangling_all_reported(self):
        tasks = [_task("a"), _task("b", ["g1"]), _task("c", ["g2"])]
        with pytest.raises(ValueError) as exc:
            TaskPlanner.validate_and_sort_dependencies(tasks)
        message = str(exc.value)
        assert "b -> g1" in message
        assert "c -> g2" in message
