"""Knowledge Graph — 兼容层

此模块已整合至 src.rag.code_graph.py。
保留此类以保持向后兼容。
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .code_graph import CodeGraph

class DependencyGraph:
    """KnowledgeGraph 版 DependencyGraph 的兼容层"""

    def __init__(self, root: Path | str) -> None:
        self._graph = CodeGraph(root)

    def build(self, pattern: str = '**/*') -> int:
        """构建图谱"""
        self._graph.build()
        return len(self._graph.nodes)

    async def build_async(self, pattern: str = '**/*.py') -> int:
        """异步构建"""
        import asyncio
        return await asyncio.to_thread(self.build, pattern)

    def get_downstream(self, path: str) -> list[str]:
        """获取下游依赖"""
        return self._graph.get_downstream(path)

    def get_upstream(self, path: str) -> list[str]:
        """获取上游依赖 (即被谁引用)"""
        return self._graph.get_imported_by(path)

    def impact_analysis(self, path: str) -> dict[str, Any]:
        """影响分析"""
        res = self._graph.impact_analysis(path)
        # 补全旧版接口可能需要的字段
        res['direct_downstream'] = self.get_downstream(path)
        res['direct_upstream'] = self.get_upstream(path)
        return res

    def stats(self) -> dict[str, Any]:
        """统计信息"""
        nodes = self._graph.nodes.values()
        return {
            'total_files': len(self._graph.nodes),
            'total_functions': sum(len(n.functions) for n in nodes),
            'total_classes': sum(len(n.classes) for n in nodes),
        }
