"""代码扫描器 - 负责扫描代码库、发现优化点

从 workflow/engine.py 拆分出来 (Phase 1: IDENTIFY)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from .code_scanner import CodeIssue


class CodeScanner:
    """代码扫描器 - 扫描代码库，发现问题"""

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir

    def scan_codebase(self, goal: str = "") -> dict[str, Any]:
        """扫描代码库，生成文件画像，发现优化点

        [性能优化 v0.50.0]: 委托给增强型 CodeScanner
        """
        from .code_scanner import CodeScanner as EnhancedScanner
        scanner = EnhancedScanner(self.workdir)
        issues = scanner.scan_codebase(goal=goal)
        file_infos = scanner.profile_files()

        return {'issues': issues, 'file_infos': file_infos}

    def _scan_files(self) -> list[CodeIssue]:
        """扫描项目代码，发现常见问题"""
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

            # AST-based checks
            issues.extend(self._check_complexity_ast(rel, source, py_file))
            # Regex-based quick checks
            issues.extend(self._check_conventions(rel, source, py_file))

        # Duplication detection
        issues.extend(self._check_duplication(src_dir))

        # Prioritize by severity
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        issues.sort(key=lambda x: severity_order.get(x.severity, 4))
        return issues

    # 向后兼容别名
    def scan(self, goal: str = "") -> dict[str, Any]:
        """向后兼容: scan_codebase 的别名"""
        return self.scan_codebase(goal)

    # 保留必要的静态分析辅助方法，防止外部调用失效
    @staticmethod
    def _safe_parse_ast(source: str, filename: str):
        """安全解析 AST"""
        try:
            return ast.parse(source, filename=filename)
        except SyntaxError:
            return None

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
        if self._has_unsafe_eval_exec(source):
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

    @staticmethod
    def _has_unsafe_eval_exec(source: str) -> bool:
        """检查是否使用了不安全的 eval/exec"""
        for line_text in source.splitlines():
            line_s = line_text.strip()
            if line_s.startswith('#'):
                continue
            if any(skip in line_s for skip in ('re.search', 're.match', 'literal_eval', 'description=')):
                continue
            if re.search(r'\beval\s*\(', line_s) or re.search(r'\bexec\s*\(', line_s):
                return True
        return False

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
        for _loc, locations in line_sequences.items():
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

    def _discover_issues_by_goal(
        self, issues: list[CodeIssue], goal: str
    ) -> list[CodeIssue]:
        """根据目标添加特定优化点"""
        if 'test' in goal.lower() or 'testing' in goal.lower():
            issues.extend(self._check_test_coverage())
        if 'performance' in goal.lower() or '优化' in goal.lower() or 'perf' in goal.lower():
            issues.extend(self._check_performance_patterns())
        return issues

    def _check_test_coverage(self) -> list[CodeIssue]:
        """检查测试覆盖率"""
        issues: list[CodeIssue] = []
        tests_dir = self.workdir / 'tests'

        if not tests_dir.exists() or not list(tests_dir.iterdir()):
            src_dir = self.workdir / 'src'
            py_files = list((src_dir if src_dir.exists() else self.workdir).rglob('*.py'))
            if py_files:
                issues.append(CodeIssue(
                    category='convention', severity='high',
                    file='(project)', line=0,
                    description='无测试文件，代码库无覆盖保障',
                    suggestion='为关键模块添加单元测试',
                ))
        return issues

    def _check_performance_patterns(self) -> list[CodeIssue]:
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

    def _profile_files(self) -> list:
        """为项目文件生成画像"""
        from .code_scanner import FileInfo
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
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(alias.name)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append(node.module)
            else:
                imports = []

            complexity = max(1, round(total_complexity / max(1, functions), 1))

            infos.append(FileInfo(
                path=rel, lines=lines, complexity=complexity,
                imports=imports, functions=functions, classes=classes,
                long_functions=long_functions,
            ))

        return infos

    @staticmethod
    def _safe_parse_ast(source: str, filename: str):
        """安全解析 AST"""
        try:
            return ast.parse(source, filename=filename)
        except SyntaxError:
            return None
