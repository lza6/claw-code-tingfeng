"""Dependency Graph — 兼容层

此模块已整合至 src.rag.code_graph.py。
保留此类以保持向后兼容。
"""
from __future__ import annotations

from .code_graph import CodeGraph


class DependencyGraph:
    """DependencyGraph 的兼容层实现，内部使用 CodeGraph"""

    def __init__(self):
        self._graph = CodeGraph()

    def update_file(self, path: str, imports: list[str]):
        """更新文件依赖"""
        self._graph.update_file(path, imports=imports)
        self._graph._resolve_all_edges() # 兼容层强制刷新

    def remove_file(self, path: str):
        """移除文件"""
        self._graph.remove_file(path)

    def get_imported_by(self, path: str) -> list[str]:
        """谁引用了我"""
        return self._graph.get_imported_by(path)

    def get_downstream(self, path: str) -> list[str]:
        """我引用了谁"""
        return self._graph.get_downstream(path)

    def get_all_paths(self) -> list[str]:
        """获取所有路径"""
        return sorted(list(self._graph.nodes.keys()))
