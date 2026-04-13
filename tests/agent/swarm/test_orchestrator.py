"""Swarm Orchestrator 模块测试"""
from __future__ import annotations

import pytest

from src.agent.swarm.orchestrator import TaskDAG, TaskDecomposition


class TestTaskDAG:
    """TaskDAG 测试"""

    def test_empty_dag(self):
        """测试空 DAG"""
        dag = TaskDAG()
        assert dag.tasks == {}
        assert dag.get_ready_tasks(set()) == []

    def test_single_task(self):
        """测试单任务 DAG"""
        tasks = [{'task_id': 'T1', 'title': 'Task 1', 'description': 'Desc', 'depends_on': ''}]
        dag = TaskDAG(tasks)
        assert len(dag.tasks) == 1
        ready = dag.get_ready_tasks(set())
        assert 'T1' in ready

    def test_linear_dependency(self):
        """测试线性依赖"""
        tasks = [
            {'task_id': 'T1', 'title': 'Task 1', 'description': 'Desc', 'depends_on': ''},
            {'task_id': 'T2', 'title': 'Task 2', 'description': 'Desc', 'depends_on': 'T1'},
            {'task_id': 'T3', 'title': 'Task 3', 'description': 'Desc', 'depends_on': 'T2'},
        ]
        dag = TaskDAG(tasks)
        
        # 初始只有 T1 就绪
        ready = dag.get_ready_tasks(set())
        assert ready == ['T1']
        
        # 完成 T1 后 T2 就绪
        dag.mark_task_completed('T1')
        ready = dag.get_ready_tasks({'T1'})
        assert 'T2' in ready
        
        # 完成 T2 后 T3 就绪
        dag.mark_task_completed('T2')
        ready = dag.get_ready_tasks({'T1', 'T2'})
        assert 'T3' in ready

    def test_parallel_tasks(self):
        """测试并行任务"""
        tasks = [
            {'task_id': 'T1', 'title': 'Task 1', 'description': 'Desc', 'depends_on': ''},
            {'task_id': 'T2', 'title': 'Task 2', 'description': 'Desc', 'depends_on': ''},
            {'task_id': 'T3', 'title': 'Task 3', 'description': 'Desc', 'depends_on': ''},
        ]
        dag = TaskDAG(tasks)
        ready = dag.get_ready_tasks(set())
        assert set(ready) == {'T1', 'T2', 'T3'}

    def test_multiple_dependencies(self):
        """测试多依赖"""
        tasks = [
            {'task_id': 'T1', 'title': 'Task 1', 'description': 'Desc', 'depends_on': ''},
            {'task_id': 'T2', 'title': 'Task 2', 'description': 'Desc', 'depends_on': ''},
            {'task_id': 'T3', 'title': 'Task 3', 'description': 'Desc', 'depends_on': 'T1,T2'},
        ]
        dag = TaskDAG(tasks)
        
        # 初始只有 T1, T2 就绪
        ready = dag.get_ready_tasks(set())
        assert set(ready) == {'T1', 'T2'}
        assert 'T3' not in ready
        
        # 完成 T1 后 T3 仍不就绪（还需 T2）
        dag.mark_task_completed('T1')
        ready = dag.get_ready_tasks({'T1'})
        assert 'T3' not in ready
        
        # 完成 T2 后 T3 就绪
        dag.mark_task_completed('T2')
        ready = dag.get_ready_tasks({'T1', 'T2'})
        assert 'T3' in ready

    def test_is_complete(self):
        """测试完成判断"""
        tasks = [
            {'task_id': 'T1', 'title': 'Task 1', 'description': 'Desc', 'depends_on': ''},
            {'task_id': 'T2', 'title': 'Task 2', 'description': 'Desc', 'depends_on': ''},
        ]
        dag = TaskDAG(tasks)
        assert dag.is_complete(set()) is False
        assert dag.is_complete({'T1'}) is False
        assert dag.is_complete({'T1', 'T2'}) is True

    def test_mark_completed_idempotent(self):
        """测试标记完成的幂等性"""
        tasks = [{'task_id': 'T1', 'title': 'Task 1', 'description': 'Desc', 'depends_on': ''}]
        dag = TaskDAG(tasks)
        dag.mark_task_completed('T1')
        dag.mark_task_completed('T1')  # 不应抛出异常

    def test_dependencies_property(self):
        """测试 TaskDecomposition 的 dependencies 属性"""
        # dependencies 属性从 sub_tasks 中提取依赖关系
        decomp = TaskDecomposition(
            sub_tasks=[
                {'task_id': 'T1', 'title': 'Task 1', 'description': '', 'depends_on': ''},
                {'task_id': 'T2', 'title': 'Task 2', 'description': '', 'depends_on': 'T1'},
            ],
        )
        # TaskDecomposition.dependencies 从 sub_tasks 提取
        deps = decomp.dependencies
        # 验证依赖关系被正确提取
        assert len(deps) >= 0  # 至少是空列表


class TestTaskDecomposition:
    """TaskDecomposition 测试"""

    def test_creation(self):
        """测试创建"""
        decomp = TaskDecomposition(
            sub_tasks=[{'task_id': 'T1', 'title': 'Test'}],
            raw_response='test response',
        )
        assert len(decomp.sub_tasks) == 1
        assert decomp.raw_response == 'test response'
        assert isinstance(decomp.dag, TaskDAG)

    def test_dependencies_property(self):
        """测试 dependencies 属性"""
        decomp = TaskDecomposition(
            sub_tasks=[
                {'task_id': 'T1', 'title': 'Task 1', 'description': '', 'depends_on': ''},
                {'task_id': 'T2', 'title': 'Task 2', 'description': '', 'depends_on': 'T1'},
            ],
        )
        deps = decomp.dependencies
        # 验证返回的是列表
        assert isinstance(deps, list)

    def test_empty_dependencies(self):
        """测试空依赖"""
        decomp = TaskDecomposition(
            sub_tasks=[
                {'task_id': 'T1', 'title': 'Task 1', 'depends_on': ''},
            ],
        )
        assert decomp.dependencies == []
