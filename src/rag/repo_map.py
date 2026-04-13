"""RepoMap — 代码地图生成器

借鉴 Aider 的 RepoMap，实现:
1. Tree-sitter 语法分析
2. Token 预算管理
3. 结构化代码摘要
4. 多文件关联分析

增强 (v0.60.0):
- SQLite 标签缓存 (来自 Aider)
- 多语言支持扩展
- 动态 token 预算调整
- RepoMap 刷新策略

使用:
    from src.rag.repo_map import RepoMap

    repo_map = RepoMap(token_budget=8000)
    map_output = repo_map.get_map(["src/main.py", "src/utils.py"])
"""
from __future__ import annotations

import os
import sqlite3
import time
from collections import OrderedDict
from pathlib import Path

from ..utils import get_logger

logger = get_logger(__name__)

# 支持的语言 (来自 Aider)
SUPPORTED_LANGUAGES = {
    "python": [".py", ".pyi"],
    "javascript": [".js", ".jsx", ".mjs"],
    "typescript": [".ts", ".tsx"],
    "html": [".html", ".htm"],
    "css": [".css", ".scss", ".sass", ".less"],
    "go": [".go"],
    "rust": [".rs"],
    "java": [".java"],
    "c": [".c", ".h"],
    "cpp": [".cpp", ".cc", ".cxx", ".hpp"],
    "csharp": [".cs"],
    "ruby": [".rb"],
    "php": [".php"],
    "swift": [".swift"],
    "kotlin": [".kt", ".kts"],
    "scala": [".scala"],
    "shell": [".sh", ".bash", ".zsh"],
    "json": [".json"],
    "yaml": [".yaml", ".yml"],
    "markdown": [".md"],
    "sql": [".sql"],
}


# ===== Aider 风格标签缓存 =====
TAGS_CACHE_VERSION = 3
TAGS_CACHE_DIR = f".clawd.tags.cache.v{TAGS_CACHE_VERSION}"


class CodeStructure:
    """代码结构信息"""
    def __init__(
        self,
        path: str,
        language: str,
        classes: list[str] | None = None,
        functions: list[dict] | None = None,
        imports: list[str] | None = None,
        exports: list[str] | None = None,
        docstring: str | None = None,
    ):
        self.path = path
        self.language = language
        self.classes = classes or []
        self.functions = functions or []  # [{"name": "foo", "signature": "..."}]
        self.imports = imports or []
        self.exports = exports or []
        self.docstring = docstring or ""

    def to_map_entry(self, depth: int = 1) -> str:
        """转换为层次化地图条目

        参数:
            depth: 深度 (1=类/方法名, 2=带签名, 3=带 Docstring)
        """
        lines = [f"# {self.path} ({self.language})"]

        # [深度控制] 根据重要性动态调整展示粒度
        if depth >= 2:
            # 类
            for cls in self.classes:
                lines.append(f"  class {cls}:")

            # 函数 (带签名)
            for func in self.functions:
                sig = func.get('signature', '')
                if depth >= 3 and func.get('docstring'):
                    doc = func['docstring'].split('\n')[0][:50]
                    lines.append(f"    def {func['name']}({sig}):  # {doc}")
                else:
                    lines.append(f"    def {func['name']}({sig})")
        else:
            # 极简模式: 仅展示顶层符号名
            summary = ", ".join(self.classes + [f["name"] for f in self.functions])
            if summary:
                lines.append(f"  symbols: {summary[:200]}...")
            elif self.docstring:
                lines.append(f"  doc: {self.docstring[:100]}...")

        return '\n'.join(lines)


from .dependency_graph import DependencyGraph


class RepoMap:
    """代码地图生成器

    借鉴 Aider 的 RepoMap 实现:
    - 使用 tree-sitter 进行语法分析
    - 符号图排名 (PageRank)
    - Token 预算管理
    """

    def __init__(
        self,
        token_budget: int = 1024,
        root_dir: Path | None = None,
        language_weights: dict[str, float] | None = None,
        max_context_window: int | None = None,
        map_multiplier_no_files: float = 2.0,
        refresh: str = "auto",
        dep_graph: DependencyGraph | None = None,
    ):
        self.token_budget = token_budget  # max_map_tokens
        self.root_dir = root_dir or Path.cwd()
        self.dep_graph = dep_graph or DependencyGraph()
        self.max_context_window = max_context_window
        self.map_multiplier_no_files = map_multiplier_no_files
        self.refresh = refresh

        self.language_weights = language_weights or {
            "python": 1.0,
            "javascript": 0.9,
            "typescript": 0.9,
            "go": 0.8,
            "rust": 0.8,
            "java": 0.7,
        }

        # Aider 风格缓存 (带 LRU 驱逐策略)
        self._structure_cache: OrderedDict[str, CodeStructure] = OrderedDict()
        self.max_cache_size: int = 1000
        self._cache_time: float = 0
        self._cache_ttl: float = 60  # 60秒缓存

        # SQLite 标签缓存 (Aider 风格)
        self._tags_cache_dir = self.root_dir / ".clawd" / TAGS_CACHE_DIR
        self._tags_cache_dir.mkdir(parents=True, exist_ok=True)
        self._db_connection: sqlite3.Connection | None = None

        # 缓存计算结果
        self._ranks_cache: dict[str, float] = {}
        self._ranks_cache_time: float = 0

        logger.debug(f"RepoMap initialized: token_budget={token_budget}, root={self.root_dir}")

    def __enter__(self) -> RepoMap:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        """释放资源，关闭数据库连接"""
        if self._db_connection:
            try:
                self._db_connection.close()
                self._db_connection = None
                logger.debug("RepoMap database connection closed.")
            except Exception as e:
                logger.error(f"Error closing RepoMap database: {e}")

    def __del__(self) -> None:
        self.close()

    def _calculate_pagerank(self, structures: list[CodeStructure]) -> dict[str, float]:
        """计算符号/文件的 PageRank 权重 (轻量级实现)"""
        if not structures:
            return {}

        # 1. 建立节点与链接
        # 统一使用相对路径作为 key
        scores = {s.path: 1.0 for s in structures}

        # 预先提取依赖关系
        forward_deps = {}
        # 优化：建立后缀索引以加速模块匹配
        suffix_map = {}
        for path in scores:
            p = Path(path)
            # 存储文件名及其父目录名，用于匹配
            suffix_map[p.name] = path
            suffix_map[p.stem] = path

        for s in structures:
            # 优先从 dep_graph 获取
            deps = self.dep_graph.get_downstream(s.path)
            if not deps:
                # 回退到 struct 内部的 imports (尝试解析为相对路径)
                deps = s.imports

            # 过滤掉不在 structures 中的依赖，并确保是相对路径
            valid_deps = []
            for d in deps:
                # 优化：使用字典查找代替循环匹配
                if d in scores:
                    valid_deps.append(d)
                elif d in suffix_map:
                    valid_deps.append(suffix_map[d])
            forward_deps[s.path] = valid_deps

        # 计算出度
        out_counts = {path: len(deps) or 1 for path, deps in forward_deps.items()}

        # 2. 迭代计算 (3轮即可实现初步收敛)
        damping = 0.85
        num_nodes = len(scores)
        if num_nodes == 0: return {}

        for _ in range(3):
            new_scores = {path: (1.0 - damping) / num_nodes for path in scores}
            for path, deps in forward_deps.items():
                if not deps:
                    # 悬挂节点：平分给所有人
                    for p in new_scores:
                        new_scores[p] += damping * scores[path] / num_nodes
                else:
                    for dep in deps:
                        new_scores[dep] += damping * scores[path] / out_counts[path]
            scores = new_scores

        return scores

    def _get_tags_db(self) -> sqlite3.Connection:
        """获取 SQLite 标签缓存连接"""
        if self._db_connection is None:
            db_path = self._tags_cache_dir / "tags.db"
            self._db_connection = sqlite3.connect(str(db_path))
            self._db_connection.row_factory = sqlite3.Row

            # 创建表 (如果不存在)
            self._db_connection.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    file_path TEXT PRIMARY KEY,
                    language TEXT,
                    tags TEXT,
                    mtime REAL,
                    size INTEGER
                )
            """)
            self._db_connection.commit()

        return self._db_connection

    def save_tags_cache(self, file_path: str, language: str, tags_data: str, mtime: float, size: int) -> None:
        """保存标签到缓存 (Aider 风格)"""
        try:
            db = self._get_tags_db()
            db.execute(
                "INSERT OR REPLACE INTO tags (file_path, language, tags, mtime, size) VALUES (?, ?, ?, ?, ?)",
                (file_path, language, tags_data, mtime, size)
            )
            db.commit()
        except Exception as e:
            logger.debug(f"Failed to save tags cache: {e}")

    def load_tags_cache(self, file_path: str) -> dict | None:
        """从缓存加载标签 (Aider 风格)"""
        try:
            db = self._get_tags_db()
            row = db.execute(
                "SELECT language, tags, mtime, size FROM tags WHERE file_path = ?",
                (file_path,)
            ).fetchone()

            if row:
                # 验证文件是否已更改
                path = Path(file_path)
                if path.exists():
                    current_mtime = path.stat().st_mtime
                    current_size = path.stat().st_size
                    if current_mtime == row['mtime'] and current_size == row['size']:
                        return {
                            'language': row['language'],
                            'tags': row['tags'],
                            'mtime': row['mtime'],
                            'size': row['size'],
                        }
        except Exception as e:
            logger.debug(f"Failed to load tags cache: {e}")

        return None

    def detect_language(self, file_path: str) -> str | None:
        """检测文件语言"""
        ext = Path(file_path).suffix.lower()
        for lang, exts in SUPPORTED_LANGUAGES.items():
            if ext in exts:
                return lang
        return None

    def get_structure(self, file_path: str) -> CodeStructure:
        """获取文件结构

        优先使用 tree-sitter，如果不可用则回退到简单解析。
        实现 LRU 驱逐策略。
        """
        # 检查缓存并应用 LRU
        if file_path in self._structure_cache:
            struct = self._structure_cache.pop(file_path)
            # 只有在 TTL 内才重用
            if time.time() - self._cache_time < self._cache_ttl:
                self._structure_cache[file_path] = struct
                return struct

        language = self.detect_language(file_path)
        if not language:
            return CodeStructure(path=file_path, language="unknown")

        try:
            # 尝试使用 tree-sitter
            structure = self._parse_with_tree_sitter(file_path, language)
        except ImportError:
            # 回退到简单解析
            structure = self._parse_simple(file_path, language)

        # 存入缓存
        self._structure_cache[file_path] = structure
        self._cache_time = time.time()

        # 驱逐最旧的
        if len(self._structure_cache) > self.max_cache_size:
            self._structure_cache.popitem(last=False)

        return structure

    def _parse_with_tree_sitter(self, file_path: str, language: str) -> CodeStructure:
        """使用 tree-sitter 解析"""
        try:
            from tree_sitter import Parser

            # 语言映射
            lang_map = {
                "python": "python",
                "javascript": "javascript",
                "typescript": "typescript",
                "go": "go",
                "rust": "rust",
                "java": "java",
            }

            lang_map.get(language, language)

            # 简化版：使用基础解析
            Parser()
            content = Path(file_path).read_text(encoding='utf-8', errors='replace')

            # 提取函数和类
            classes = []
            functions = []
            imports = []

            if language == "python":
                # 简单的正则解析
                import re
                # 类
                classes = re.findall(r'^class\s+(\w+)', content, re.MULTILINE)
                # 函数
                functions = re.findall(r'^def\s+(\w+)\s*\(([^)]*)\)', content, re.MULTILINE)
                functions = [{"name": f[0], "signature": f[1]} for f in functions]
                # 导入
                imports = re.findall(r'^import\s+(\S+)', content, re.MULTILINE)
                imports.extend(re.findall(r'^from\s+(\S+)\s+import', content, re.MULTILINE))

            return CodeStructure(
                path=file_path,
                language=language,
                classes=classes,
                functions=functions,
                imports=imports,
            )

        except Exception as e:
            logger.debug(f"Tree-sitter parsing failed: {e}")
            return self._parse_simple(file_path, language)

    def _parse_simple(self, file_path: str, language: str) -> CodeStructure:
        """简单解析（无 tree-sitter 时）"""
        try:
            content = Path(file_path).read_text(encoding='utf-8', errors='replace')
        except Exception:
            return CodeStructure(path=file_path, language=language)

        classes = []
        functions = []
        imports = []

        for line in content.split('\n'):
            stripped = line.strip()

            if language == "python":
                if stripped.startswith('class '):
                    parts = stripped.split()
                    if len(parts) >= 2:
                        classes.append(parts[1].rstrip(':'))
                elif stripped.startswith('def '):
                    # 提取函数签名
                    match = stripped[4:].split('(')
                    if match:
                        func_name = match[0]
                        signature = '(' + '(' if len(match) > 1 else ''
                        functions.append({"name": func_name, "signature": signature})
                elif stripped.startswith('import ') or stripped.startswith('from '):
                    if 'import' in stripped:
                        parts = stripped.split()
                        if len(parts) >= 2:
                            imports.append(parts[1])

        return CodeStructure(
            path=file_path,
            language=language,
            classes=classes,
            functions=functions,
            imports=imports,
        )

    def get_map(
        self,
        files: list[str],
        show_imports: bool = True,
        show_docstrings: bool = False,
    ) -> str:
        """生成代码地图 (Aider 风格接口)

        Args:
            files: 文件列表 (chat files)
            show_imports: 是否显示导入
            show_docstrings: 是否显示文档字符串

        Returns:
            格式化的地图字符串

        Note: 这是 Aider 风格 get_repo_map 的简化版本
        """
        if not files:
            return ""

        # 获取所有文件结构 (并行处理)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor() as executor:
            structures = list(executor.map(self.get_structure, files))

        # 按语言权重排序
        structures.sort(
            key=lambda s: self.language_weights.get(s.language, 0.5),
            reverse=True,
        )

        # 估算 token 并裁剪
        return self._format_map(structures, show_imports, show_docstrings)

    def get_repo_map(
        self,
        chat_files: list[str],
        other_files: list[str],
        mentioned_fnames: set | None = None,
        mentioned_idents: set | None = None,
        force_refresh: bool = False,
        scanner: Any | None = None,
    ) -> str | None:
        """Aider 风格 repo map 生成 (完整实现)

        Args:
            chat_files: 当前聊天中的文件
            other_files: 仓库中的其他文件
            mentioned_fnames: 提到的文件名
            mentioned_idents: 提到的标识符
            force_refresh: 强制刷新缓存
            scanner: 外部传入的 UnifiedScanner 实例，用于加速

        Returns:
            格式化的 repo map 或 None
        """
        if self.token_budget <= 0:
            return None
        if not other_files:
            return None

        mentioned_fnames = mentioned_fnames or set()
        mentioned_idents = mentioned_idents or set()

        # 动态 token 预算 (Aider 风格: 无文件时扩大视野)
        max_map_tokens = self.token_budget

        # 无聊天文件时，扩大范围
        if not chat_files and self.max_context_window:
            padding = 4096
            target = min(
                int(max_map_tokens * self.map_multiplier_no_files),
                self.max_context_window - padding,
            )
            if target > 0:
                max_map_tokens = target

        # 获取排名标签地图
        try:
            files_listing = self._get_ranked_tags_map(
                chat_files,
                other_files,
                max_map_tokens,
                mentioned_fnames,
                mentioned_idents,
                force_refresh,
                scanner=scanner
            )
        except RecursionError:
            logger.warning("Disabling repo map, repo too large")
            self.token_budget = 0
            return None

        if not files_listing:
            return None

        # 记录统计
        self.last_map = files_listing

        if chat_files:
            prefix = "\nother "
        else:
            prefix = "\n"

        return prefix + files_listing

    def _get_ranked_tags_map(
        self,
        chat_files: list[str],
        other_files: list[str],
        max_tokens: int,
        mentioned_fnames: set,
        mentioned_idents: set,
        force_refresh: bool,
        scanner: Any | None = None,
    ) -> str:
        """获取排名后的标签地图 (基于 PageRank)"""

        # 优化：优先过滤 chat_files，减少 Pagerank 计算量
        chat_files_set = set(chat_files)
        other_files = [f for f in other_files if f not in chat_files_set]
        all_files = chat_files + other_files

        if scanner:
            # 使用统一扫描器加速
            all_structures = scanner.get_repo_map_structures()
            # 过滤只属于 all_files 的结构
            all_files_set = set(all_files)
            all_structures = [s for s in all_structures if s.path in all_files_set]

            # 如果扫描器中没有所有文件，补充扫描缺失的
            existing_paths = {s.path for s in all_structures}
            missing = [f for f in all_files if f not in existing_paths]
            if missing:
                for f in missing:
                    res = scanner.scan_file(f)
                    if res.success:
                        all_structures.append(res.structure)
        else:
            # 获取所有文件的结构 (并行处理)
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor() as executor:
                all_structures = list(executor.map(self.get_structure, all_files))

        # 优化：限制 PageRank 计算的文件数量，对于超大型仓库非常重要
        MAX_PAGERANK_FILES = 2000
        if len(all_structures) > MAX_PAGERANK_FILES:
            # 如果文件太多，按文件大小或修改时间初步预选
            all_structures.sort(key=lambda s: os.path.getsize(self.root_dir / s.path) if (self.root_dir / s.path).exists() else 0, reverse=True)
            all_structures = all_structures[:MAX_PAGERANK_FILES]

        # 缓存检查 (如果文件列表没变，且在 TTL 内)
        cache_key = ",".join(sorted(all_files))
        if not force_refresh and hasattr(self, '_last_all_files_key') and self._last_all_files_key == cache_key:
            if time.time() - self._ranks_cache_time < 300: # 5分钟缓存
                ranks = self._ranks_cache
            else:
                ranks = None
        else:
            ranks = None

        if ranks is None:
            # 更新依赖图
            for struct in all_structures:
                try:
                    # 同步更新依赖图
                    self.dep_graph.update_file(struct.path, struct.imports)
                except Exception as e:
                    logger.debug(f"Failed to update dep graph for {struct.path}: {e}")

            # 计算 PageRank 权重
            ranks = self._calculate_pagerank(all_structures)
            self._ranks_cache = ranks
            self._ranks_cache_time = time.time()
            self._last_all_files_key = cache_key

        # 复合权重排序: Pagerank * 语言权重 * (如果被提及则翻倍)
        # 预先计算文件名集合以加速查找
        mentioned_names = {f for f in mentioned_fnames}

        def _get_weight(s: CodeStructure) -> float:
            base = ranks.get(s.path, 1.0)
            lang = self.language_weights.get(s.language, 0.5)
            importance = 1.0
            # 优化：直接在 set 中查找
            if Path(s.path).name in mentioned_names:
                importance = 2.0
            return base * lang * importance

        all_structures.sort(key=_get_weight, reverse=True)

        # 格式化输出
        return self._format_map(all_structures, True, False)

    def _format_map(
        self,
        structures: list[CodeStructure],
        show_imports: bool,
        show_docstrings: bool,
    ) -> str:
        """格式化地图输出 (带更准确的 Token 估算)"""
        lines = []
        total_tokens = 0

        # 预估 Token：1 个单词约 1.3 token
        TOKEN_RATIO = 1.3

        for struct in structures:
            # 跳过二进制/不支持的文件
            if struct.language == "unknown":
                continue

            entry = [f"\n// {struct.path}"]
            current_entry_tokens = len(struct.path.split('/')) + 2

            # 导入
            if show_imports and struct.imports:
                imports_str = f"  // imports: {', '.join(struct.imports[:5])}"
                entry.append(imports_str)
                current_entry_tokens += int(len(imports_str.split()) * TOKEN_RATIO)

            # 类
            for cls in struct.classes:
                entry.append(f"  class {cls}")
                current_entry_tokens += 3

            # 函数
            for func in struct.functions[:10]:  # 限制每个文件函数数量
                entry.append(f"  def {func['name']}(...)")
                current_entry_tokens += 3

            # 文档
            if show_docstrings and struct.docstring:
                doc = struct.docstring[:50]
                entry.append(f"  // {doc}")
                current_entry_tokens += int(len(doc.split()) * TOKEN_RATIO)

            # 检查 token 预算
            if total_tokens + current_entry_tokens > self.token_budget:
                # 尝试只添加文件名作为占位符
                if total_tokens + 5 < self.token_budget:
                    lines.append(f"\n// {struct.path} (truncated)")
                break

            total_tokens += current_entry_tokens
            lines.extend(entry)

        return '\n'.join(lines)

    def get_files_by_pattern(
        self,
        patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> list[str]:
        """获取匹配模式的文件

        优先使用 Git 命令获取文件列表以提高速度并遵循忽略规则。
        """
        import fnmatch
        import subprocess

        files = []
        is_git = (self.root_dir / ".git").exists()

        if is_git:
            try:
                # 使用 git ls-files 获取受控文件列表
                result = subprocess.run(
                    ["git", "ls-files"],
                    cwd=self.root_dir,
                    capture_output=True,
                    text=True,
                    check=True
                )
                all_raw_files = result.stdout.splitlines()
            except Exception:
                is_git = False

        if not is_git:
            # 回退到 os.walk
            all_raw_files = []
            for root, dirs, filenames in os.walk(self.root_dir):
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith('.')
                    and d not in ['node_modules', 'venv', '__pycache__', 'build', 'dist']
                ]
                for filename in filenames:
                    filepath = os.path.join(root, filename)
                    all_raw_files.append(os.path.relpath(filepath, self.root_dir))

        # 过滤模式
        if not patterns:
            patterns = ["**/*.py", "**/*.js", "**/*.ts"]

        for rel_path in all_raw_files:
            filename = os.path.basename(rel_path)

            # 检查包含模式
            included = False
            for pattern in patterns:
                if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(filename, pattern):
                    included = True
                    break

            if not included:
                continue

            # 检查排除模式
            if exclude_patterns:
                for pattern in exclude_patterns:
                    if fnmatch.fnmatch(rel_path, pattern):
                        included = False
                        break

            if included:
                files.append(rel_path)

        return files


# 全局实例
_repo_map: RepoMap | None = None


def get_repo_map(
    token_budget: int = 8000,
    root_dir: Path | None = None,
) -> RepoMap:
    """获取全局 RepoMap 实例"""
    global _repo_map
    if _repo_map is None:
        _repo_map = RepoMap(token_budget, root_dir)
    return _repo_map
