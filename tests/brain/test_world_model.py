"""WorldModel 模块单元测试"""
import ast
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from src.brain.world_model import RepositoryWorldModel


class TestRepositoryWorldModelInit:
    """RepositoryWorldModel 初始化测试"""

    def test_init_default(self, tmp_path):
        """默认初始化"""
        wm = RepositoryWorldModel(root_dir=tmp_path)
        assert wm.root_dir == tmp_path
        assert wm._is_initialized is False
        assert isinstance(wm._intent_cache, dict)
        assert isinstance(wm._arch_patterns, list)

    def test_init_with_custom_components(self, tmp_path):
        """自定义组件初始化"""
        mock_indexer = MagicMock()
        mock_graph = MagicMock()

        wm = RepositoryWorldModel(
            root_dir=tmp_path,
            text_indexer=mock_indexer,
            dependency_graph=mock_graph,
        )

        assert wm.text_indexer is mock_indexer
        assert wm.dependency_graph is mock_graph


class TestRepositoryWorldModelInitialize:
    """RepositoryWorldModel 初始化方法测试"""

    @pytest.mark.asyncio
    async def test_initialize(self, tmp_path):
        """初始化方法"""
        wm = RepositoryWorldModel(root_dir=tmp_path)
        await wm.initialize()
        assert wm._is_initialized is True

    @pytest.mark.asyncio
    async def test_initialize_twice(self, tmp_path):
        """重复初始化不重复执行"""
        wm = RepositoryWorldModel(root_dir=tmp_path)
        await wm.initialize()
        await wm.initialize()
        assert wm._is_initialized is True


class TestRepositoryWorldModelContext:
    """RepositoryWorldModel 上下文方法测试"""

    def test_get_context_for_file(self, tmp_path):
        """获取文件上下文"""
        wm = RepositoryWorldModel(root_dir=tmp_path)

        # Mock the dependency graph and text indexer
        mock_graph = MagicMock()
        mock_graph.impact_analysis.return_value = {
            "direct_upstream": ["a.py"],
            "direct_downstream": ["b.py"],
        }
        wm.dependency_graph = mock_graph

        mock_indexer = MagicMock()
        mock_indexer.get_context.return_value = ["context1", "context2"]
        wm.text_indexer = mock_indexer

        # Create a file in the root
        test_file = tmp_path / "test.py"
        test_file.write_text("class Test: pass")

        ctx = wm.get_context_for_file(str(test_file))

        assert ctx["file"] == "test.py"
        assert "upstream" in ctx
        assert "downstream" in ctx
        assert "semantic_context" in ctx
        assert "patterns" in ctx


class TestRepositoryWorldModelPatterns:
    """RepositoryWorldModel 模式检测测试"""

    def test_detect_singleton(self, tmp_path):
        """检测 Singleton 模式"""
        wm = RepositoryWorldModel(root_dir=tmp_path)

        # Create a file with Singleton pattern
        code = '''
class Singleton:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
'''
        test_file = tmp_path / "singleton.py"
        test_file.write_text(code)

        patterns = wm._detect_patterns(str(test_file))
        assert "Singleton" in patterns

    def test_detect_observer(self, tmp_path):
        """检测 Observer 模式"""
        wm = RepositoryWorldModel(root_dir=tmp_path)

        code = '''
class Subject:
    def __init__(self):
        self._observers = []

    def subscribe(self, observer):
        self._observers.append(observer)

    def notify(self):
        for obs in self._observers:
            obs.update()
'''
        test_file = tmp_path / "observer.py"
        test_file.write_text(code)

        patterns = wm._detect_patterns(str(test_file))
        assert "Observer" in patterns

    def test_detect_command(self, tmp_path):
        """检测 Command 模式"""
        wm = RepositoryWorldModel(root_dir=tmp_path)

        code = '''
class Command:
    def execute(self):
        pass
'''
        test_file = tmp_path / "command.py"
        test_file.write_text(code)

        patterns = wm._detect_patterns(str(test_file))
        assert "Command" in patterns

    def test_detect_factory(self, tmp_path):
        """检测 Factory 模式"""
        wm = RepositoryWorldModel(root_dir=tmp_path)

        code = '''
def create_object():
    return MyClass()
'''
        test_file = tmp_path / "factory.py"
        test_file.write_text(code)

        patterns = wm._detect_patterns(str(test_file))
        assert "Factory" in patterns

    def test_detect_adapter_from_filename(self, tmp_path):
        """从文件名检测 Adapter 模式"""
        wm = RepositoryWorldModel(root_dir=tmp_path)

        code = '''
class Adapter:
    pass
'''
        test_file = tmp_path / "my_adapter.py"
        test_file.write_text(code)

        patterns = wm._detect_patterns(str(test_file))
        assert "Adapter" in patterns

    def test_detect_proxy_from_filename(self, tmp_path):
        """从文件名检测 Proxy 模式"""
        wm = RepositoryWorldModel(root_dir=tmp_path)

        code = '''
class Proxy:
    pass
'''
        test_file = tmp_path / "my_proxy.py"
        test_file.write_text(code)

        patterns = wm._detect_patterns(str(test_file))
        assert "Proxy" in patterns


class TestRepositoryWorldModelStats:
    """RepositoryWorldModel 统计方法测试"""

    def test_stats(self, tmp_path):
        """统计方法返回正确的数据"""
        wm = RepositoryWorldModel(root_dir=tmp_path)

        # Mock the components
        mock_graph = MagicMock()
        mock_graph.stats.return_value = {"node_count": 10, "edge_count": 5}
        wm.dependency_graph = mock_graph

        mock_indexer = MagicMock()
        mock_indexer.get_stats.return_value = {"total_documents": 20}
        wm.text_indexer = mock_indexer

        stats = wm.stats()

        assert stats["node_count"] == 10
        assert stats["edge_count"] == 5
        assert stats["indexed_docs"] == 20
        assert stats["memory_friendly"] is True


class TestRepositoryWorldModelEdgeCases:
    """RepositoryWorldModel 边界情况测试"""

    def test_get_context_nonexistent_file(self, tmp_path):
        """获取不存在文件的上下文"""
        wm = RepositoryWorldModel(root_dir=tmp_path)

        # No mock - should handle gracefully
        ctx = wm.get_context_for_file("nonexistent.py")
        # Should return something, not crash
        assert ctx is not None

    def test_detect_patterns_invalid_file(self, tmp_path):
        """检测无效文件的模式"""
        wm = RepositoryWorldModel(root_dir=tmp_path)

        patterns = wm._detect_patterns("nonexistent.py")
        assert patterns == []

    def test_detect_patterns_syntax_error(self, tmp_path):
        """检测语法错误文件的模式"""
        wm = RepositoryWorldModel(root_dir=tmp_path)

        code = 'invalid python code @#$'
        test_file = tmp_path / "syntax_error.py"
        test_file.write_text(code)

        patterns = wm._detect_patterns(str(test_file))
        assert patterns == []