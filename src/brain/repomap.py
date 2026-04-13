"""RepoMap - 代码库智能映射系统 — 从 Aider repomap.py 移植并增强

使用 tree-sitter + PageRank 算法构建代码库结构图，为 LLM 提供智能上下文。

核心特性:
- tree-sitter tags 提取（定义和引用）
- diskcache 持久化缓存（基于 mtime）
- PageRank 图排序（个性化权重）
- token 预算控制
- 多语言支持

用法:
    repomap = RepoMap(root='/path/to/repo', map_tokens=2048)
    context = repomap.get_repo_map(chat_files=['main.py'], other_files=['utils.py'])
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from collections import defaultdict, namedtuple
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ==================== 数据模型 ====================

Tag = namedtuple('Tag', 'rel_fname fname line name kind')

SQLITE_ERRORS = (sqlite3.OperationalError, sqlite3.DatabaseError, OSError)
CACHE_VERSION = 4


# ==================== Tree-sitter Tags 提取 ====================

def get_scm_fname(lang: str) -> Path | None:
    """获取 tree-sitter queries 文件路径

    参数:
        lang: 语言名称

    返回:
        .scm 文件路径，或 None
    """
    # 尝试从 tree-sitter-language-pack 获取
    try:
        from grep_ast.tsl import USING_TSL_PACK, get_language, get_parser
        if USING_TSL_PACK:
            # 使用内置的 queries
            queries_dir = Path(__file__).parent.parent / 'queries'
            scm_file = queries_dir / f'{lang}.scm'
            if scm_file.exists():
                return scm_file
    except ImportError:
        pass

    return None


def get_language_for_file(fname: str) -> str | None:
    """根据文件扩展名获取语言名称"""
    from grep_ast import filename_to_lang
    return filename_to_lang(fname)


# ==================== RepoMap 类 ====================

class RepoMap:
    """代码库智能映射

    使用 tree-sitter 提取代码标签，构建引用图谱，
    使用 PageRank 算法计算标签重要性。
    """

    TAGS_CACHE_DIR = f'.clawd.tags.cache.v{CACHE_VERSION}'

    def __init__(
        self,
        map_tokens: int = 1024,
        root: str | Path | None = None,
        main_model: Any = None,
        io: Any = None,
        repo_content_prefix: str | None = None,
        verbose: bool = False,
        max_context_window: int | None = None,
        map_mul_no_files: int = 8,
        refresh: str = 'auto',
    ) -> None:
        self.io = io
        self.verbose = verbose
        self.refresh = refresh

        if not root:
            root = os.getcwd()
        self.root = Path(root)

        self.load_tags_cache()
        self.cache_threshold = 0.95

        self.max_map_tokens = map_tokens
        self.map_mul_no_files = map_mul_no_files
        self.max_context_window = max_context_window

        self.repo_content_prefix = repo_content_prefix
        self.main_model = main_model

        # 缓存
        self.tree_cache: dict[str, Any] = {}
        self.tree_context_cache: dict[str, Any] = {}
        self.map_cache: dict[str, str] = {}
        self.map_processing_time = 0.0
        self.last_map: str | None = None

    def load_tags_cache(self) -> None:
        """加载 tags 缓存"""
        try:
            from diskcache import Cache
            cache_path = self.root / self.TAGS_CACHE_DIR
            self.TAGS_CACHE = Cache(str(cache_path))
        except ImportError:
            # diskcache 不可用，使用内存缓存
            self.TAGS_CACHE: dict[str, Any] = {}
        except SQLITE_ERRORS:
            self.TAGS_CACHE = {}

    def tags_cache_error(self, original_error: Exception | None = None) -> None:
        """处理 SQLite 错误"""
        if isinstance(self.TAGS_CACHE, dict):
            return

        cache_path = self.root / self.TAGS_CACHE_DIR
        try:
            if cache_path.exists():
                shutil.rmtree(cache_path)
            from diskcache import Cache
            self.TAGS_CACHE = Cache(str(cache_path))
        except SQLITE_ERRORS:
            self.TAGS_CACHE = {}

    def get_rel_fname(self, fname: str) -> str:
        """获取相对路径"""
        try:
            return os.path.relpath(fname, self.root)
        except ValueError:
            return fname

    def get_mtime(self, fname: str) -> float | None:
        """获取文件修改时间"""
        try:
            return os.path.getmtime(fname)
        except FileNotFoundError:
            return None

    def get_tags(self, fname: str, rel_fname: str) -> list[Tag]:
        """获取文件的 tags（带缓存）"""
        file_mtime = self.get_mtime(fname)
        if file_mtime is None:
            return []

        cache_key = fname
        try:
            val = self.TAGS_CACHE.get(cache_key)
        except SQLITE_ERRORS:
            self.tags_cache_error()
            val = self.TAGS_CACHE.get(cache_key)

        if val is not None and val.get('mtime') == file_mtime:
            return val.get('data', [])

        # 缓存未命中，重新解析
        data = list(self.get_tags_raw(fname, rel_fname))

        try:
            self.TAGS_CACHE[cache_key] = {'mtime': file_mtime, 'data': data}
        except SQLITE_ERRORS:
            self.tags_cache_error()
            self.TAGS_CACHE[cache_key] = {'mtime': file_mtime, 'data': data}

        return data

    def get_tags_raw(self, fname: str, rel_fname: str) -> Iterator[Tag]:
        """使用 tree-sitter 提取 tags"""
        lang = get_language_for_file(fname)
        if not lang:
            return

        try:
            from grep_ast.tsl import get_language, get_parser
            language = get_language(lang)
            parser = get_parser(lang)
        except Exception as e:
            if self.verbose:
                logger.warning(f'无法加载 parser: {fname}: {e}')
            return

        # 获取 queries 文件
        scm_path = get_scm_fname(lang)
        if not scm_path or not scm_path.exists():
            return

        scm_content = scm_path.read_text(encoding='utf-8')

        # 读取文件内容
        try:
            code = Path(fname).read_text(encoding='utf-8', errors='replace')
        except OSError:
            return

        if not code:
            return

        # 解析 AST
        tree = parser.parse(bytes(code, 'utf-8'))

        # 执行 queries
        try:
            from tree_sitter import Query, QueryCursor
            query = Query(language, scm_content)
            cursor = QueryCursor(query)
            captures = cursor.captures(tree.root_node)
        except Exception as e:
            if self.verbose:
                logger.warning(f'Query 执行失败: {fname}: {e}')
            return

        for tag, nodes in captures.items():
            for node in nodes:
                tag_str = str(tag)
                if tag_str.startswith('name.definition.'):
                    kind = 'def'
                elif tag_str.startswith('name.reference.'):
                    kind = 'ref'
                else:
                    continue

                yield Tag(
                    rel_fname=rel_fname,
                    fname=fname,
                    name=node.text.decode('utf-8'),
                    kind=kind,
                    line=node.start_point[0],
                )

    def get_repo_map(
        self,
        chat_files: list[str],
        other_files: list[str],
        mentioned_fnames: set[str] | None = None,
        mentioned_idents: set[str] | None = None,
        force_refresh: bool = False,
    ) -> str | None:
        """生成代码库映射

        参数:
            chat_files: 已在聊天中的文件
            other_files: 其他文件
            mentioned_fnames: 提及的文件名
            mentioned_idents: 提及的标识符
            force_refresh: 强制刷新缓存

        返回:
            格式化的代码库映射字符串
        """
        if self.max_map_tokens <= 0:
            return None

        if not other_files:
            return None

        if not mentioned_fnames:
            mentioned_fnames = set()
        if not mentioned_idents:
            mentioned_idents = set()

        max_map_tokens = self.max_map_tokens

        # 当没有文件在聊天中时，扩大视图
        padding = 4096
        if max_map_tokens and self.max_context_window:
            target = min(
                int(max_map_tokens * self.map_mul_no_files),
                self.max_context_window - padding,
            )
        else:
            target = 0

        if not chat_files and self.max_context_window and target > 0:
            max_map_tokens = target

        try:
            files_listing = self.get_ranked_tags_map(
                chat_files,
                other_files,
                max_map_tokens,
                mentioned_fnames,
                mentioned_idents,
                force_refresh,
            )
        except RecursionError:
            logger.error('代码库过大，禁用 RepoMap')
            self.max_map_tokens = 0
            return None

        if not files_listing:
            return None

        if self.verbose:
            num_tokens = self.token_count(files_listing)
            logger.info(f'Repo-map: {num_tokens / 1024:.1f} k-tokens')

        if chat_files:
            other = 'other '
        else:
            other = ''

        if self.repo_content_prefix:
            repo_content = self.repo_content_prefix.format(other=other)
        else:
            repo_content = ''

        repo_content += files_listing
        return repo_content

    def get_ranked_tags_map(
        self,
        chat_files: list[str],
        other_files: list[str],
        max_map_tokens: int,
        mentioned_fnames: set[str],
        mentioned_idents: set[str],
        force_refresh: bool,
    ) -> str:
        """获取排序后的 tags 映射"""
        # 构建引用图谱并计算 PageRank
        ranked_tags = self.get_ranked_tags(
            chat_files, other_files, mentioned_fnames, mentioned_idents, force_refresh
        )

        if not ranked_tags:
            return ''

        # 生成映射文本
        lines: list[str] = []
        current_fname: str | None = None
        token_count = 0

        for tag in ranked_tags:
            if tag.rel_fname != current_fname:
                if current_fname is not None:
                    lines.append('')
                current_fname = tag.rel_fname
                lines.append(f'{current_fname}:')

            # 添加标签行
            tag_line = f'  {tag.name} (line {tag.line + 1})'
            tag_tokens = self.token_count(tag_line)

            if token_count + tag_tokens > max_map_tokens:
                break

            lines.append(tag_line)
            token_count += tag_tokens

        return '\n'.join(lines)

    def get_ranked_tags(
        self,
        chat_files: list[str],
        other_files: list[str],
        mentioned_fnames: set[str],
        mentioned_idents: set[str],
        force_refresh: bool,
    ) -> list[Tag]:
        """使用 PageRank 排序 tags（从 Aider 增强移植）

        新增: 重要文件（special_files）在 PageRank 中获得额外权重提升，
        确保配置文件和关键元数据优先出现在 repo map 中。
        """
        # 收集所有 tags
        all_tags: list[Tag] = []
        defines: dict[str, list[Tag]] = defaultdict(list)
        references: dict[str, list[Tag]] = defaultdict(list)

        for fname in chat_files + other_files:
            rel_fname = self.get_rel_fname(fname)
            tags = self.get_tags(fname, rel_fname)

            for tag in tags:
                all_tags.append(tag)
                if tag.kind == 'def':
                    defines[tag.name].append(tag)
                else:
                    references[tag.name].append(tag)

        # 构建引用图谱
        try:
            import networkx as nx
            G = nx.DiGraph()
        except ImportError:
            # networkx 不可用，简单排序
            return sorted(all_tags, key=lambda t: (t.rel_fname, t.line))

        # 添加节点和边
        for fname in chat_files + other_files:
            rel_fname = self.get_rel_fname(fname)
            G.add_node(rel_fname)

        # 添加引用边
        for name, refs in references.items():
            for ref_tag in refs:
                source = ref_tag.rel_fname
                for def_tag in defines.get(name, []):
                    target = def_tag.rel_fname
                    if source != target:
                        if G.has_edge(source, target):
                            G[source][target]['weight'] += 1
                        else:
                            G.add_edge(source, target, weight=1)

        # 计算个性化 PageRank
        personalization: dict[str, float] = {}
        for fname in chat_files:
            rel_fname = self.get_rel_fname(fname)
            personalization[rel_fname] = 1.0
        for fname in mentioned_fnames:
            rel_fname = self.get_rel_fname(fname)
            personalization[rel_fname] = personalization.get(rel_fname, 0) + 0.5

        # 重要文件权重提升（从 Aider filter_important_files 移植）
        try:
            from .special_files import is_important_file
        except ImportError:
            is_important_file = None

        if is_important_file:
            for fname in chat_files + other_files:
                rel_fname = self.get_rel_fname(fname)
                if is_important_file(rel_fname):
                    personalization[rel_fname] = personalization.get(rel_fname, 0) + 0.3

        try:
            if personalization:
                pagerank = nx.pagerank(G, personalization=personalization)
            else:
                pagerank = nx.pagerank(G)
        except Exception:
            pagerank = {n: 1.0 for n in G.nodes()}

        # 排序 tags
        def tag_sort_key(tag: Tag) -> tuple[float, str, int]:
            pr = pagerank.get(tag.rel_fname, 0)
            return (-pr, tag.rel_fname, tag.line)

        return sorted(all_tags, key=tag_sort_key)

    def token_count(self, text: str) -> int:
        """估算文本的 token 数量"""
        if not text:
            return 0

        # 简单估算：字符数 / 4
        return len(text) // 4
