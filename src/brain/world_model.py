"""WorldModel - 代码库感知心脏 (v3 核心组件)

功能:
- 统一管理代码拓扑 (DependencyGraph) 和语义索引 (TextIndexer)
- 缓存项目级意图与设计模式
- 提供基于"上下文指纹"的快速环境感知
- 内存友好型实现: 零本地大模型依赖，全异步轻量逻辑
"""
from __future__ import annotations

import ast
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..rag.knowledge_graph import DependencyGraph
from ..rag.text_indexer import TextIndexer

logger = logging.getLogger(__name__)


class PatternVisitor(ast.NodeVisitor):
    """单次遍历 AST 以检测设计模式 (优化版)"""

    def __init__(self):
        self.patterns = set()

    def visit_ClassDef(self, node: ast.ClassDef):
        methods = set()
        has_instance_var = False
        chain_count = 0

        # 单次遍历 body 提取所有特征
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.add(item.name)
                # 检查链式调用 (Builder)
                for stmt in item.body:
                    if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Name) and stmt.value.id == 'self':
                        chain_count += 1
                        break
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id in ('_instance', '_singleton'):
                        has_instance_var = True

        # 模式匹配逻辑
        # Observer
        if {'subscribe', 'notify'} <= methods or {'add_observer', 'notify_observers'} <= methods:
            self.patterns.add('Observer')

        # Singleton
        if '__new__' in methods or has_instance_var:
            self.patterns.add('Singleton')

        # Command
        if 'execute' in methods and len(methods) <= 5:
            self.patterns.add('Command')

        # Builder
        if chain_count >= 2:
            self.patterns.add('Builder')

        # Adapter & Strategy
        name_lower = node.name.lower()
        if 'adapter' in name_lower:
            self.patterns.add('Adapter')

        strategy_indicators = {'execute', 'run', 'process', 'handle', 'apply'}
        if (methods & strategy_indicators) and len(methods) >= 3 and ('strategy' in name_lower):
            self.patterns.add('Strategy')

        # Decorator (Base class check)
        for base in node.bases:
            if isinstance(base, ast.Name) and 'decorator' in base.id.lower():
                self.patterns.add('Decorator')

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._check_factory_or_decorator(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._check_factory_or_decorator(node)
        self.generic_visit(node)

    def _check_factory_or_decorator(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        func_name = node.name.lower()
        has_nested = False

        # 预先检查是否有嵌套函数
        for n in node.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                has_nested = True
                break

        for stmt in node.body:
            if isinstance(stmt, ast.Return) and stmt.value:
                # Factory
                if (
                    isinstance(stmt.value, ast.Call)
                    and isinstance(stmt.value.func, ast.Name)
                    and any(kw in func_name for kw in ('create', 'build', 'factory', 'make'))
                ):
                    self.patterns.add('Factory')
                # Decorator
                if has_nested and isinstance(stmt.value, ast.Name):
                    self.patterns.add('Decorator')


@lru_cache(maxsize=1024)
def get_file_patterns(root_dir: Path, file_path: str) -> list[str]:
    """缓存版模式检测 (优化版)"""
    abs_path = root_dir / file_path if not Path(file_path).is_absolute() else Path(file_path)
    if not abs_path.exists():
        return []
    try:
        # 性能优化：限制读取大小
        stat = abs_path.stat()
        if stat.st_size > 128 * 1024:
            return []

        source = abs_path.read_text(encoding='utf-8', errors='replace')
        tree = ast.parse(source)
        visitor = PatternVisitor()
        visitor.visit(tree)

        patterns = visitor.patterns
        stem = abs_path.stem.lower()
        for kw in ('adapter', 'proxy', 'facade'):
            if kw in stem:
                patterns.add(kw.capitalize())
        return sorted(list(patterns))
    except Exception:
        return []


class RepositoryWorldModel:
    """代码库世界模型"""

    def __init__(
        self,
        root_dir: Path | str,
        text_indexer: TextIndexer | None = None,
        dependency_graph: DependencyGraph | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.text_indexer = text_indexer or TextIndexer(root_dir=self.root_dir)
        self.dependency_graph = dependency_graph or DependencyGraph(root_dir)

        # 意图记忆库
        self._intent_cache: dict[str, str] = {}
        # 架构规范库
        self._arch_patterns: list[str] = []

        self._is_initialized = False
        self._prefetch_history: set[str] = set()
        self._relevant_files_cache: dict[str, list[str]] = {}

    async def initialize(self) -> None:
        """初始化世界模型，扫描代码库 (优化版: 基于语义指纹的增量索引)"""
        if self._is_initialized:
            return

        logger.info(f"正在初始化代码库世界模型 (语义感知增量模式): {self.root_dir}")

        # 1. 加载指纹存储 (从 GoalX 汲取持久化思想)
        fingerprints = {}
        fp_path = self.root_dir / ".clawd" / "brain" / "fingerprints.json"
        if fp_path.exists():
            try:
                import json
                fingerprints = json.loads(fp_path.read_text(encoding='utf-8'))
            except Exception: pass

        from .fingerprint import ContextFingerprint

        # 2. 构建代码图谱 (并行 AST 分析)
        try:
            from ..rag.code_graph import CodeGraph
            if not isinstance(self.dependency_graph, CodeGraph):
                self.dependency_graph = CodeGraph(self.root_dir)

            import asyncio
            await asyncio.to_thread(self.dependency_graph.build, parallel=True)
            logger.info(f"代码图谱索引完成: {len(self.dependency_graph.nodes)} 个文件")
        except Exception as e:
            logger.warning(f"并行代码图谱构建失败: {e}")
            await self.dependency_graph.build_async("**/*.py")

        # 3. 智能增量文本索引
        files = list(self.root_dir.glob("**/*.py"))
        changed_files = []
        new_fingerprints = {}

        for f in files:
            rel_f = str(f.relative_to(self.root_dir))
            current_fp = ContextFingerprint.generate(f)
            new_fingerprints[rel_f] = current_fp
            if current_fp != fingerprints.get(rel_f):
                changed_files.append(f)

        if changed_files:
            logger.info(f"检测到 {len(changed_files)} 个文件发生语义变更，触发索引更新")
            # 批量添加变更文件
            tasks = [self.text_indexer.add_file_async(f) for f in changed_files]
            await asyncio.gather(*tasks)
        else:
            logger.info("代码库语义无变化，跳过 RAG 重索引")

        # 4. 持久化新指纹
        try:
            fp_path.parent.mkdir(parents=True, exist_ok=True)
            fp_path.write_text(json.dumps(new_fingerprints), encoding='utf-8')
        except Exception: pass

        self._is_initialized = True
        logger.info("世界模型初始化完成。")

        # 发布 RAG 指标更新
        try:
            from ..core.events import Event, EventType, get_event_bus
            text_stats = self.text_indexer.get_stats()
            metrics = {
                'indexed_files': indexed_count,
                'total_terms': text_stats.get('index_terms', 0),
                'coverage_percent': (indexed_count / max(text_stats.get('total_documents', 1), 1)) * 100
            }
            get_event_bus().publish(Event(
                type=EventType.RAG_INDEX_UPDATED,
                data=metrics,
                source='world_model'
            ))
        except Exception:
            pass

    def predict_relevant_files(self, current_file: str, depth: int = 1) -> list[str]:
        """预测相关文件 (优化版: 结果缓存)"""
        rel_path = str(Path(current_file).relative_to(self.root_dir)) if Path(current_file).is_absolute() else current_file

        if rel_path in self._relevant_files_cache:
            return self._relevant_files_cache[rel_path]

        predictions = set()

        # 1. 依赖关系预测 (直接上下游)
        predictions.update(self.dependency_graph.get_imported_by(rel_path))
        predictions.update(self.dependency_graph.get_downstream(rel_path))

        # 2. 语义关联文件
        if hasattr(self.text_indexer, 'search'):
             keywords = Path(rel_path).stem.replace('_', ' ')
             results = self.text_indexer.search(keywords, top_k=5)
             for r in results:
                 if r.document and r.document.source != rel_path:
                     try:
                         r_rel = str(Path(r.document.source).relative_to(self.root_dir))
                         predictions.add(r_rel)
                     except ValueError:
                         predictions.add(r.document.source)

        res = sorted(list(predictions))
        if len(self._relevant_files_cache) < 500:
            self._relevant_files_cache[rel_path] = res
        return res

    async def prefetch_context(self, current_file: str) -> dict[str, Any]:
        """预取上下文 (优化版: 限制数量并使用历史记录)"""
        relevant_files = self.predict_relevant_files(current_file)

        to_prefetch = [f for f in relevant_files if f not in self._prefetch_history]

        results = {}
        for fpath in to_prefetch[:10]:
            results[fpath] = self.get_context_for_file(fpath)
            self._prefetch_history.add(fpath)

        return results


    def get_context_for_file(self, file_path: str) -> dict[str, Any]:
        """获取指定文件的架构级上下文"""
        rel_path = str(Path(file_path).relative_to(self.root_dir)) if Path(file_path).is_absolute() else file_path

        # 获取受影响的上游和下游
        impact = self.dependency_graph.impact_analysis(rel_path)

        # 获取相关语义上下文 (前 3 个)
        semantic = self.text_indexer.get_context(f"架构关联: {rel_path}", top_k=3)

        return {
            "file": rel_path,
            "upstream": impact.get("direct_upstream", []),
            "downstream": impact.get("direct_downstream", []),
            "semantic_context": semantic,
            "patterns": self._detect_patterns(rel_path)
        }

    def _detect_patterns(self, file_path: str) -> list[str]:
        """基于 AST 结构检测设计模式 (优化后的单次遍历+缓存版)"""
        return get_file_patterns(self.root_dir, file_path)

    def stats(self) -> dict[str, Any]:
        """返回世界模型健康度统计"""
        graph_stats = self.dependency_graph.stats()
        text_stats = self.text_indexer.get_stats()

        return {
            "node_count": graph_stats.get("node_count", 0),
            "edge_count": graph_stats.get("edge_count", 0),
            "indexed_docs": text_stats.get("total_documents", 0),
            "memory_friendly": True
        }
