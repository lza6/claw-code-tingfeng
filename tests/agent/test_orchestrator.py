import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch
from src.agent.swarm.orchestrator import OrchestratorAgent, TaskDAG, TaskDecomposition
from src.agent.swarm.message_bus import MessageBus

@pytest.fixture
def mock_message_bus():
    return MagicMock(spec=MessageBus)

@pytest.fixture
def sample_tasks():
    return [
        {'task_id': 'T1', 'title': 'Task 1', 'description': 'Desc 1', 'depends_on': ''},
        {'task_id': 'T2', 'title': 'Task 2', 'description': 'Desc 2', 'depends_on': 'T1'},
        {'task_id': 'T3', 'title': 'Task 3', 'description': 'Desc 3', 'depends_on': 'T1, T2'},
        {'task_id': 'T4', 'title': 'Task 4', 'description': 'Desc 4', 'depends_on': ''},
    ]

class TestTaskDAG:
    def test_dag_initialization(self, sample_tasks):
        dag = TaskDAG(sample_tasks)
        assert dag.in_degree['T1'] == 0
        assert dag.in_degree['T2'] == 1
        assert dag.in_degree['T3'] == 2
        assert dag.in_degree['T4'] == 0
        assert set(dag.get_ready_tasks(set())) == {'T1', 'T4'}

    def test_mark_task_completed(self, sample_tasks):
        dag = TaskDAG(sample_tasks)
        completed = set()

        # Mark T1 completed
        dag.mark_task_completed('T1')
        completed.add('T1')
        assert dag.in_degree['T2'] == 0
        assert dag.in_degree['T3'] == 1
        assert set(dag.get_ready_tasks(completed)) == {'T2', 'T4'}

        # Mark T2 completed
        dag.mark_task_completed('T2')
        completed.add('T2')
        assert dag.in_degree['T3'] == 0
        assert set(dag.get_ready_tasks(completed)) == {'T3', 'T4'}

    def test_is_complete(self, sample_tasks):
        dag = TaskDAG(sample_tasks)
        assert not dag.is_complete({'T1', 'T2'})
        assert dag.is_complete({'T1', 'T2', 'T3', 'T4'})

class TestOrchestratorAgent:
    @pytest.mark.asyncio
    async def test_decompose_task_success(self, mock_message_bus):
        agent = OrchestratorAgent("test-orchestrator", mock_message_bus)

        mock_engine = MagicMock()
        mock_session = MagicMock()
        mock_session.final_result = """
```json
{
  "thought_process": "Analysis done",
  "sub_tasks": [
    {
      "task_id": "T1",
      "title": "Sub 1",
      "description": "Desc 1",
      "assigned_to": "worker",
      "depends_on": "",
      "file_path": "test.py"
    }
  ]
}
```"""
        mock_engine.run = AsyncMock(return_value=mock_session)

        with patch.object(agent, '_get_engine', return_value=mock_engine):
            decomposition = await agent.decompose_task("Build something")

            assert len(decomposition.sub_tasks) == 1
            assert decomposition.sub_tasks[0]['task_id'] == 'T1'
            assert isinstance(decomposition.dag, TaskDAG)

    @pytest.mark.asyncio
    async def test_decompose_task_fallback(self, mock_message_bus):
        agent = OrchestratorAgent("test-orchestrator", mock_message_bus)

        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(side_effect=Exception("LLM Failure"))

        with patch.object(agent, '_get_engine', return_value=mock_engine):
            decomposition = await agent.decompose_task("Critical task")

            assert len(decomposition.sub_tasks) == 1
            assert decomposition.sub_tasks[0]['task_id'] == 'T1'
            assert "LLM Failure" in decomposition.raw_response
