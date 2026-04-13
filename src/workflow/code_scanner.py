"""代码扫描器 — 负责扫描代码库、发现问题、生成文件画像

从 workflow/engine.py 拆分出来，职责单一。

[性能优化 v0.37.0]:
- 添加增量扫描支持，基于文件 mtime 缓存
- 只扫描变更文件，大幅提升扫描速度
"""
from __future__ import annotations

import ast
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CodeIssue:
    """代码扫描发现的问题"""
    category: str            # 'complexity' | 'duplication' | 'convention' | 'security' | 'performance'
    severity: str            # 'critical' | 'high' | 'medium' | 'low'
    file: str
    line: int
    description: str
    suggestion: str = ""
    impact_files: list[str] = field(default_factory=list)
    risk_level: str = "low"


@dataclass
class FileInfo:
    """文件画像信息"""
    path: str
    lines: int
    complexity: float        # 圈复杂度估算值
    imports: list[str] = field(default_factory=list)
    functions: int = 0
    classes: int = 0
    long_functions: list[str] = field(default_factory=list)
    duplications: int = 0


class CodeScanner:
    """代码扫描器

    职责:
    - 扫描项目代码，发现常见问题
    - 生成文件画像信息
    - 检测性能反模式

    [性能优化 v0.37.0]:
    - 支持增量扫描，基于文件 mtime 缓存
    - 只扫描变更文件，大幅提升扫描速度
    """

    def __init__(self, workdir: Path, enable_incremental: bool = True) -> None:
        self.logger = logging.getLogger("workflow.code_scanner")
        self.workdir = workdir
        self.enable_incremental = enable_incremental
        self._cache_file = workdir / '.clawd' / 'scan_cache.json'

        # [Codedb Integration]
        from ..core.indexing import TrigramIndex, WordIndex
        from ..core.symbol_index import SymbolIndex
        self.t_index = TrigramIndex()
        self.w_index = WordIndex()
        self.s_index = SymbolIndex()

        self._cache: dict[str, Any] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        """加载扫描缓存"""
        if self._cache_file.exists():
            try:
                self._cache = json.loads(self._cache_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _save_cache(self) -> None:
        """保存扫描缓存"""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
        except OSError as e:
            self.logger.warning(f"扫描缓存保存失败: {e}")

    def _get_file_mtime(self, file_path: Path) -> float:
        """获取文件修改时间"""
        try:
            return file_path.stat().st_mtime
        except OSError:
            return 0.0

    def _is_file_changed(self, rel_path: str, file_path: Path) -> bool:
        """检查文件是否已变更（基于 mtime 和 size 对比）"""
        if not self.enable_incremental:
            return True  # 禁用增量时始终认为已变更

        cached = self._cache.get(rel_path, {})
        cached_mtime = cached.get('mtime', 0.0)
        cached_size = cached.get('size', -1)

        try:
            stat = file_path.stat()
            current_mtime = stat.st_mtime
            current_size = stat.st_size
        except OSError:
            return True

        # mtime 容差 1ms，同时增加 size 校验防止漏扫
        mtime_changed = abs(current_mtime - cached_mtime) > 0.001
        size_changed = current_size != cached_size

        return mtime_changed or size_changed

    def _update_file_cache(self, rel_path: str, file_path: Path, issues: list[dict]) -> None:
        """更新文件缓存"""
        try:
            stat = file_path.stat()
            mtime = stat.st_mtime
            size = stat.st_size
        except OSError:
            mtime = 0.0
            size = -1

        self._cache[rel_path] = {
            'mtime': mtime,
            'size': size,
            'issues': issues,
            'scanned_at': time.time(),
        }

    def _get_cached_issues(self, rel_path: str) -> list[CodeIssue]:
        """获取缓存的问题"""
        cached = self._cache.get(rel_path, {}).get('issues', [])
        return [CodeIssue(**issue) for issue in cached]

    def scan_codebase(self, goal: str = "", force_full_scan: bool = False) -> list[CodeIssue]:
        """扫描项目代码，发现常见问题

        [性能优化 v0.37.0]:
        - 默认启用增量扫描，只扫描变更文件
        - 使用 force_full_scan=True 强制全量扫描
        """
        if force_full_scan:
            self.enable_incremental = False

        # [性能/高精] 扫描前重置内存索引，防止重复添加 (Python Reviewer 建议)
        self.t_index = type(self.t_index)()
        self.s_index = type(self.s_index)()

        issues: list[CodeIssue] = []
        src_dir = self.workdir / 'src'
        if not src_dir.exists():
            src_dir = self.workdir

        for py_file in sorted(src_dir.rglob('*.py')):
            rel = str(py_file.relative_to(self.workdir))
            if '__pycache__' in rel or rel.startswith('tests/'):
                continue

            try:
                source = py_file.read_text(encoding='utf-8', errors='replace')
            except (OSError, PermissionError):
                continue

            # [性能/高精] Trigram 索引：快速识别潜在内容
            self.t_index.add_document(rel, source)
            self.s_index.add_file(rel, source)

            # [性能] 增量扫描：检查文件是否变更
            if not self._is_file_changed(rel, py_file):
                issues.extend(self._get_cached_issues(rel))
                continue

            # AST-based checks
            file_issues: list[CodeIssue] = []
            file_issues.extend(self._check_complexity_ast(rel, source, py_file))
            # Regex-based quick checks
            file_issues.extend(self._check_conventions(rel, source, py_file))
            issues.extend(file_issues)

            # [性能] 更新缓存
            self._update_file_cache(
                rel, py_file,
                [{'category': i.category, 'severity': i.severity, 'file': i.file,
                  'line': i.line, 'description': i.description, 'suggestion': i.suggestion}
                 for i in file_issues]
            )

        # Duplication detection (始终全量扫描，因为需要跨文件对比)
        issues.extend(self._check_duplication(src_dir))

        # [v0.50.0] 根据目标添加特定优化点
        if goal:
            if 'test' in goal.lower():
                issues.extend(self.check_test_coverage())
            if 'performance' in goal.lower() or '优化' in goal.lower():
                issues.extend(self.check_performance_patterns())

        # Prioritize
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        issues.sort(key=lambda x: severity_order.get(x.severity, 4))

        # [性能] 保存缓存
        self._save_cache()

        return issues

    def profile_files(self) -> list[FileInfo]:
        """为项目文件生成画像"""
        infos: list[FileInfo] = []
        src_dir = self.workdir / 'src'
        if not src_dir.exists():
            return infos

        for py_file in sorted(src_dir.rglob('*.py')):
            if '__pycache__' in str(py_file):
                continue
            rel = str(py_file.relative_to(self.workdir))
            try:
                source = py_file.read_text(encoding='utf-8', errors='replace')
            except (OSError, PermissionError):
                continue

            lines = source.count('\n') + 1
            tree = self._safe_parse_ast(source, rel)

            functions = 0
            classes = 0
            long_functions: list[str] = []
            total_complexity = 1

            if tree:
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        functions += 1
                        if node.end_lineno and node.end_lineno - node.lineno > 60:
                            long_functions.append(node.name)
                    elif isinstance(node, ast.ClassDef):
                        classes += 1
                    elif isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try,
                                           ast.ExceptHandler)):
                        total_complexity += 1

            imports = []
            if tree:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(alias.name)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append(node.module)

            complexity = max(1, round(total_complexity / max(1, functions), 1))

            infos.append(FileInfo(
                path=rel, lines=lines, complexity=complexity,
                imports=imports, functions=functions, classes=classes,
                long_functions=long_functions,
            ))

        return infos

    def check_test_coverage(self) -> list[CodeIssue]:
        """检查测试覆盖率"""
        issues: list[CodeIssue] = []
        src_dir = self.workdir / 'src'
        tests_dir = self.workdir / 'tests'

        if not tests_dir.exists() or not tests_dir.iterdir():
            py_files = list((src_dir if src_dir.exists() else self.workdir).rglob('*.py'))
            if py_files:
                issues.append(CodeIssue(
                    category='convention', severity='high',
                    file='(project)', line=0,
                    description='无测试文件，代码库无覆盖保障',
                    suggestion='为关键模块添加单元测试',
                ))
        return issues

    def check_performance_patterns(self) -> list[CodeIssue]:
        """扫描常见性能反模式"""
        issues: list[CodeIssue] = []
        src_dir = self.workdir / 'src'
        if not src_dir.exists():
            return issues

        for py_file in sorted(src_dir.rglob('*.py')):
            if '__pycache__' in str(py_file):
                continue
            rel = str(py_file.relative_to(self.workdir))
            try:
                source = py_file.read_text(encoding='utf-8', errors='replace')
            except (OSError, PermissionError):
                continue

            # string concatenation in loop pattern
            if re.search(r'(for|while)\s.*\+.*str\(', source):
                issues.append(CodeIssue(
                    category='performance', severity='medium', file=rel, line=1,
                    description='疑似循环中字符串拼接',
                    suggestion='使用 list + join 或 f-string 模板',
                ))

            # list comprehension that could be generator
            if re.search(r'(sum|min|max)\(\[.*for.*\]\)', source):
                issues.append(CodeIssue(
                    category='performance', severity='low', file=rel, line=1,
                    description='sum/min/max 中使用了列表推导而非生成器',
                    suggestion='去掉方括号改为生成器表达式，减少内存分配',
                ))

        return issues

    def check_architecture(self) -> list[str]:
        """架构级优化建议"""
        points: list[str] = []
        src_dir = self.workdir / 'src'
        if not src_dir.exists():
            return points

        # Check for circular imports hint
        init_files = list(src_dir.rglob('__init__.py'))
        init_with_imports = []
        for init in init_files:
            try:
                content = init.read_text(encoding='utf-8')
                if 'import' in content:
                    init_with_imports.append(str(init.relative_to(self.workdir)))
            except (OSError, PermissionError):
                pass

        if len(init_with_imports) > 10:
            points.append(f'{len(init_with_imports)} 个 __init__.py 有导入，可能需要简化或消除循环依赖')

        # Large modules (> 500 lines in a single file)
        large_modules = []
        for py_file in src_dir.rglob('*.py'):
            if '__pycache__' in str(py_file):
                continue
            try:
                content = py_file.read_text(encoding='utf-8', errors='replace')
                if content.count('\n') > 500:
                    large_modules.append(str(py_file.relative_to(self.workdir)))
            except (OSError, PermissionError):
                pass

        if large_modules:
            points.append(f'{len(large_modules)} 个模块超过 500 行，建议拆分')

        return points

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _check_complexity_ast(self, rel: str, source: str, file_path: Path) -> list[CodeIssue]:
        """使用 AST 分析函数复杂度"""
        issues: list[CodeIssue] = []
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                lineno = node.lineno
                body_lines = node.end_lineno - lineno if node.end_lineno else 0

                # Long function check
                if body_lines > 60:
                    issues.append(CodeIssue(
                        category='convention', severity='high', file=rel, line=lineno,
                        description=f'函数 `{name}` 过长 ({body_lines} 行)',
                        suggestion='拆分为更小的函数，每个函数只做一件事',
                    ))
                elif body_lines > 30:
                    issues.append(CodeIssue(
                        category='convention', severity='medium', file=rel, line=lineno,
                        description=f'函数 `{name}` 较长 ({body_lines} 行)',
                        suggestion='考虑抽取子函数',
                    ))

                # Nesting depth check
                max_depth = self._max_nesting(node)
                if max_depth > 4:
                    issues.append(CodeIssue(
                        category='complexity', severity='high', file=rel, line=lineno,
                        description=f'函数 `{name}` 嵌套过深 (深度 {max_depth})',
                        suggestion='减少嵌套：提前 return、提取函数、使用卫语句',
                    ))

                # Too many parameters
                args = node.args
                param_count = len(args.args) - (1 if args.args and args.args[0].arg == 'self' else 0)
                param_count += len(args.posonlyargs) + len(args.kwonlyargs)
                if param_count > 5:
                    issues.append(CodeIssue(
                        category='complexity', severity='medium', file=rel, line=lineno,
                        description=f'函数 `{name}` 参数过多 ({param_count} 个)',
                        suggestion='使用 dataclass 或 dict 封装参数',
                    ))

            elif isinstance(node, ast.ClassDef):
                # Too many methods
                methods = sum(
                    1 for child in ast.walk(node)
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child != node
                )
                if methods > 15:
                    issues.append(CodeIssue(
                        category='complexity', severity='medium', file=rel,
                        line=node.lineno,
                        description=f'类 `{node.name}` 方法过多 ({methods} 个)',
                        suggestion='按职责拆分为多个类',
                    ))

        return issues

    def _check_conventions(self, rel: str, source: str, file_path: Path) -> list[CodeIssue]:
        """检查代码规范问题"""
        issues: list[CodeIssue] = []
        lines = source.splitlines()

        for i, line in enumerate(lines, 1):
            stripped = line.rstrip()

            # TODO/FIXME 堆积
            if re.match(r'\s*#\s*(TODO|FIXME|XXX|HACK)\b', stripped, re.IGNORECASE):
                issues.append(CodeIssue(
                    category='convention', severity='low', file=rel, line=i,
                    description=stripped.strip(),
                    suggestion='清理或处理注释标记的问题',
                ))

            # Very long lines
            if len(stripped) > 120:
                issues.append(CodeIssue(
                    category='convention', severity='low', file=rel, line=i,
                    description=f'行过长 ({len(stripped)} 字符)',
                    suggestion='拆分为多行',
                ))

        # Bare except
        if re.search(r'except\s*:', source):
            issues.append(CodeIssue(
                category='convention', severity='medium', file=rel, line=1,
                description='使用了 bare except',
                suggestion='指定具体的异常类型',
            ))

        # eval/exec usage (security)
        has_eval_exec = False
        for line_text in source.splitlines():
            line_s = line_text.strip()
            if line_s.startswith('#'):
                continue
            if any(skip in line_s for skip in ('re.search', 're.match', 'literal_eval', 'description=')):
                continue
            if re.search(r'\beval\s*\(', line_s) or re.search(r'\bexec\s*\(', line_s):
                has_eval_exec = True
                break
        if has_eval_exec:
            issues.append(CodeIssue(
                category='security', severity='critical', file=rel, line=1,
                description='使用了不安全的 eval/exec',
                suggestion='使用 ast 或更安全的替代方案',
            ))

        # import * usage
        if re.search(r'from\s+\S+\s+import\s+\*', source):
            issues.append(CodeIssue(
                category='convention', severity='medium', file=rel, line=1,
                description='使用了 import *',
                suggestion='显式导入需要的名称',
            ))

        return issues

    def _check_duplication(self, src_dir: Path) -> list[CodeIssue]:
        """简单重复代码检测 — 使用 3 行哈希对比"""
        if not src_dir.exists():
            return []

        line_sequences: dict[str, list[str]] = {}

        for py_file in sorted(src_dir.rglob('*.py')):
            if '__pycache__' in str(py_file):
                continue
            try:
                lines = py_file.read_text(encoding='utf-8', errors='replace').splitlines()
            except (OSError, PermissionError):
                continue

            rel = str(py_file.relative_to(self.workdir))
            for i in range(len(lines) - 2):
                block = '\n'.join(ln.rstrip() for ln in lines[i:i+3])
                if not block.strip() or len(block) < 20:
                    continue
                key = hash(block)
                entry = f'{rel}:{i+1}'
                line_sequences.setdefault(str(key), []).append(entry)

        issues: list[CodeIssue] = []
        for locations in line_sequences.values():
            unique_files = list(set(p.rsplit(':', 1)[0] for p in locations))
            if len(unique_files) > 1 or len(locations) > 5:
                issues.append(CodeIssue(
                    category='duplication', severity='medium',
                    file=locations[0].rsplit(':', 1)[0],
                    line=int(locations[0].rsplit(':', 1)[1]),
                    description=f'疑似重复代码段出现 {len(locations)} 次',
                    suggestion='抽取为公共函数',
                ))

        return issues

    @staticmethod
    def _max_nesting(node: ast.AST, depth: int = 0) -> int:
        """计算 AST 中最大的嵌套深度"""
        nesting_nodes = (ast.If, ast.For, ast.While, ast.With, ast.Try)
        max_depth = depth
        for child in ast.iter_child_nodes(node):
            child_depth = depth + 1 if isinstance(child, nesting_nodes) else depth
            max_depth = max(max_depth, CodeScanner._max_nesting(child, child_depth))
        return max_depth

    @staticmethod
    def _safe_parse_ast(source: str, filename: str) -> ast.Module | None:
        try:
            return ast.parse(source, filename=filename)
        except SyntaxError:
            return None
