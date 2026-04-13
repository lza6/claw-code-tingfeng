"""Code Graph — 统一的代码拓扑图谱

整合了原有的 DependencyGraph 与 KnowledgeGraph，提供:
1. 跨语言依赖解析 (Python AST + 多语言正则)
2. 符号提取 (类、函数)
3. 变更影响分析 (Impact Analysis)
4. 模糊路径匹配与快速反向查找
5. 循环依赖检测
"""
from __future__ import annotations

import ast
import re
import os
import time
import logging
from collections import defaultdict, deque, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Set, List, Dict, Optional

logger = logging.getLogger('rag.code_graph')

@dataclass
class CodeNode:
    """代码图谱节点 — 文件"""
    path: str                                # 相对路径
    language: str = 'text'
    imports: Set[str] = field(default_factory=set)      # import 的目标 (原始字符串)
    imported_by: Set[str] = field(default_factory=set)  # 被哪些文件导入 (已解析路径)
    resolved_imports: Set[str] = field(default_factory=set) # 解析后的依赖文件路径
    functions: List[str] = field(default_factory=list)
    classes: List[List[str]] = field(default_factory=list) # [[name, signature], ...]
    mtime: float = 0.0
    size: int = 0

from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

def _parse_file_task(root_dir: Path, rel_path: str):
    """独立的进程任务: 解析单个文件"""
    from .code_graph import CodeNode, _parse_content_for_node
    abs_path = root_dir / rel_path
    try:
        source = abs_path.read_text(encoding='utf-8', errors='replace')
        ext = abs_path.suffix.lower()
        node = CodeNode(
            path=rel_path,
            language=ext[1:] if ext else 'text',
            mtime=abs_path.stat().st_mtime,
            size=abs_path.stat().st_size
        )
        _parse_content_for_node(source, node)
        return node
    except Exception:
        return None

def _parse_content_for_node(source: str, node: CodeNode):
    """解析逻辑抽离，以便多进程调用"""
    # 静态导入，避免循环引用
    import ast
    import re
    ext = node.language
    if ext == 'py':
        try:
            tree = ast.parse(source)
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    node.functions.append(n.name)
                elif isinstance(n, ast.ClassDef):
                    node.classes.append([n.name, ""]) # 暂时不提取签名
                elif isinstance(n, ast.Import):
                    for alias in n.names:
                        node.imports.add(alias.name)
                elif isinstance(n, ast.ImportFrom) and n.module:
                    node.imports.add(n.module)
        except SyntaxError:
            pass # 回退逻辑可在此添加
    elif ext in ('js', 'ts', 'jsx', 'tsx'):
        import_patterns = [
            re.compile(r"import\s+.*?\s+from\s+['\"](.+?)['\"]"),
            re.compile(r"import\s+['\"](.+?)['\"]"),
            re.compile(r"require\s*\(\s*['\"](.+?)\s*['\"]\s*\)"),
        ]
        for p in import_patterns:
            for m in p.finditer(source):
                node.imports.add(m.group(1))

    # 统一提取模式 (此处可集成 PatternVisitor 逻辑)

class CodeGraph:
    """统一的代码拓扑图谱"""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else Path.cwd()
        self.nodes: Dict[str, CodeNode] = {}

        # 索引加速
        self._name_index: Dict[str, Set[str]] = defaultdict(set)
        self._stem_index: Dict[str, Set[str]] = defaultdict(set)

    def build(self, files: List[str] | None = None, parallel: bool = True):
        """批量构建/刷新图谱"""
        if files is None:
            files = [str(p.relative_to(self.root)).replace('\\', '/')
                    for p in self.root.glob('**/*')
                    if p.is_file() and not any(part.startswith('.') or part == '__pycache__' for part in p.parts)]

        if parallel and len(files) > 20:
            # 开启多进程加速
            cpus = min(multiprocessing.cpu_count(), 8)
            with ProcessPoolExecutor(max_workers=cpus) as executor:
                futures = [executor.submit(_parse_file_task, self.root, f) for f in files]
                for future in as_completed(futures):
                    node = future.result()
                    if node:
                        self._add_node_to_index(node)
        else:
            for f in files:
                self.update_file(f)

        # 解析依赖边
        self._resolve_all_edges()

    def _add_node_to_index(self, node: CodeNode):
        """将解析好的节点加入图谱和索引"""
        self.nodes[node.path] = node
        p = Path(node.path)
        self._name_index[p.name].add(node.path)
        self._stem_index[p.stem].add(node.path)

    def update_file(self, rel_path: str, source: str | None = None, imports: List[str] | None = None) -> CodeNode:
        """更新文件信息"""
        rel_path = rel_path.replace('\\', '/')
        abs_path = self.root / rel_path

        if source is None and abs_path.exists():
            try:
                source = abs_path.read_text(encoding='utf-8', errors='replace')
            except Exception:
                source = ""

        ext = abs_path.suffix.lower()
        node = CodeNode(
            path=rel_path,
            language=ext[1:] if ext else 'text',
            mtime=abs_path.stat().st_mtime if abs_path.exists() else time.time(),
            size=abs_path.stat().st_size if abs_path.exists() else 0
        )

        # 1. 提取元数据
        if imports is not None:
            node.imports = set(imports)
        elif source:
            self._parse_content(source, node)

        # 2. 移除旧的索引引用
        if rel_path in self.nodes:
            self.remove_file(rel_path)

        # 3. 存储节点
        self.nodes[rel_path] = node

        # 4. 更新快速查找索引
        p = Path(rel_path)
        self._name_index[p.name].add(rel_path)
        self._stem_index[p.stem].add(rel_path)

        # 5. 重新解析所有节点的依赖关系 (延迟处理或按需解析更好，但为了图谱完整性进行全量解析)
        # 注意: 在大规模构建时建议使用 build() 方法统一处理
        return node

    def remove_file(self, rel_path: str):
        """移除文件"""
        if rel_path not in self.nodes:
            return

        node = self.nodes.pop(rel_path)

        # 清除索引
        p = Path(rel_path)
        self._name_index[p.name].discard(rel_path)
        self._stem_index[p.stem].discard(rel_path)

        # 清除其他节点对我的引用
        for other in self.nodes.values():
            other.imported_by.discard(rel_path)
            other.resolved_imports.discard(rel_path)

    async def build_async(self, pattern: str = "**/*.py"):
        """异步构建接口 (兼容性封装)"""
        import asyncio
        files = [str(p.relative_to(self.root)).replace('\\', '/')
                for p in self.root.glob(pattern)
                if p.is_file() and not any(part.startswith('.') or part == '__pycache__' for part in p.parts)]
        await asyncio.to_thread(self.build, files=files, parallel=True)

    def _resolve_all_edges(self):
        """解析所有文件间的依赖边"""
        for node in self.nodes.values():
            node.resolved_imports.clear()
            for imp in node.imports:
                target = self._resolve_import(imp, node.path)
                if target:
                    node.resolved_imports.add(target)
                    if target in self.nodes:
                        self.nodes[target].imported_by.add(node.path)

    def _resolve_import(self, imp: str, from_path: str) -> str | None:
        """解析 import 到具体文件路径 (增强版解析逻辑)"""
        # 1. 直接匹配
        if imp in self.nodes: return imp

        # 2. 转换模块名匹配 (a.b.c -> a/b/c.py)
        mod_path = imp.replace('.', '/')
        for ext in ['.py', '.js', '.ts', '.jsx', '.tsx']:
            p = mod_path + ext
            if p in self.nodes: return p
            # 尝试 __init__.py
            p_init = mod_path + '/__init__' + ext
            if p_init in self.nodes: return p_init

        # 3. 相对路径解析
        if imp.startswith('.'):
            try:
                base_dir = Path(from_path).parent
                # 这里简化处理，实际可能需要更复杂的相对路径计算
                p = (base_dir / imp).relative_to(self.root)
                p_str = str(p).replace('\\', '/')
                if p_str in self.nodes: return p_str
                for ext in ['.py', '.js', '.ts']:
                    if p_str + ext in self.nodes: return p_str + ext
            except Exception:
                pass

        # 4. 模糊匹配 (基于文件名/Stem)
        name = os.path.basename(imp)
        if name in self._name_index:
            return next(iter(self._name_index[name]))
        if name in self._stem_index:
            return next(iter(self._stem_index[name]))

        return None

    def _parse_content(self, source: str, node: CodeNode):
        """解析文件内容提取符号和依赖"""
        ext = node.language
        if ext == 'py':
            self._parse_python(source, node)
        elif ext in ('js', 'ts', 'jsx', 'tsx'):
            self._parse_javascript(source, node)
        else:
            self._parse_generic(source, node)

    def _parse_python(self, source: str, node: CodeNode):
        """解析 Python AST"""
        try:
            tree = ast.parse(source)
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    node.functions.append(n.name)
                elif isinstance(n, ast.ClassDef):
                    node.classes.append(n.name)
                elif isinstance(n, ast.Import):
                    for alias in n.names:
                        node.imports.add(alias.name)
                elif isinstance(n, ast.ImportFrom) and n.module:
                    node.imports.add(n.module)
        except SyntaxError:
            self._parse_generic(source, node)

    def _parse_javascript(self, source: str, node: CodeNode):
        """基于正则解析 JS/TS"""
        import_patterns = [
            re.compile(r"import\s+.*?\s+from\s+['\"](.+?)['\"]"),
            re.compile(r"import\s+['\"](.+?)['\"]"),
            re.compile(r"require\s*\(\s*['\"](.+?)\s*['\"]\s*\)"),
        ]
        for p in import_patterns:
            for m in p.finditer(source):
                node.imports.add(m.group(1))

    def _parse_generic(self, source: str, node: CodeNode):
        """通用正则解析"""
        patterns = [
            re.compile(r"#include\s+[<\"](.+?)[>\"]"),
            re.compile(r"require\s+['\"](.+?)['\"]"),
            re.compile(r"import\s+['\"](.+?)['\"]"),
        ]
        for p in patterns:
            for m in p.finditer(source):
                node.imports.add(m.group(1))

    # -- 查询接口 (兼容原有实现) --

    def get_imported_by(self, path: str) -> List[str]:
        """谁引用了我"""
        node = self.nodes.get(path)
        if not node:
            # 尝试模糊匹配
            p = Path(path)
            paths = self._name_index.get(p.name) or self._stem_index.get(p.stem)
            if paths:
                node = self.nodes.get(next(iter(paths)))

        return sorted(list(node.imported_by)) if node else []

    def get_downstream(self, path: str) -> List[str]:
        """我引用了谁"""
        node = self.nodes.get(path)
        return sorted(list(node.resolved_imports)) if node else []

    def impact_analysis(self, path: str) -> Dict[str, Any]:
        """变更影响分析"""
        visited_up: set[str] = set()
        queue = deque(self.get_imported_by(path))
        while queue:
            curr = queue.popleft()
            if curr not in visited_up:
                visited_up.add(curr)
                queue.extend([p for p in self.get_imported_by(curr) if p not in visited_up])

        return {
            'path': path,
            'upstream_count': len(visited_up),
            'impacted_files': sorted(list(visited_up)),
            'risk_level': 'high' if len(visited_up) > 10 else ('medium' if len(visited_up) > 3 else 'low')
        }
