"""Symbol Extractor — Ported from Project B (explore.zig)

Lightweight, regex-based structural parser for extracting symbols (functions, classes, imports)
from source code without full AST parsing. Supports Python, TypeScript/JavaScript, and Zig.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class SymbolKind(str, Enum):
    FUNCTION = "function"
    CLASS = "class"
    STRUCT = "struct"
    ENUM = "enum"
    UNION = "union"
    CONSTANT = "constant"
    VARIABLE = "variable"
    IMPORT = "import"
    INTERFACE = "interface"
    METHOD = "method"
    TRAIT = "trait"
    IMPL = "impl"
    TYPE_ALIAS = "type_alias"
    MACRO = "macro"
    TEST = "test"
    MARKDOWN_H1 = "h1"
    MARKDOWN_H2 = "h2"
    MARKDOWN_H3 = "h3"
    UNKNOWN = "unknown"

@dataclass
class Symbol:
    name: str
    kind: SymbolKind
    line_start: int
    line_end: int
    detail: str | None = None

@dataclass
class FileOutline:
    path: str
    language: str
    line_count: int
    symbols: list[Symbol]
    imports: list[str] = field(default_factory=list)

def detect_language(path: str) -> str:
    path = path.lower()
    if path.endswith('.py'):
        return 'python'
    if path.endswith(('.ts', '.tsx')):
        return 'typescript'
    if path.endswith(('.js', '.jsx')):
        return 'javascript'
    if path.endswith('.zig'):
        return 'zig'
    if path.endswith('.rs'):
        return 'rust'
    if path.endswith('.go'):
        return 'go'
    if path.endswith(('.c', '.h')):
        return 'c'
    if path.endswith(('.cpp', '.hpp', '.cc', '.cxx')):
        return 'cpp'
    if path.endswith('.php'):
        return 'php'
    if path.endswith(('.md', '.markdown')):
        return 'markdown'
    if path.endswith('.json'):
        return 'json'
    if path.endswith(('.yaml', '.yml')):
        return 'yaml'
    return 'unknown'

class SymbolExtractor:
    def __init__(self):
        pass

    def extract(self, path: str, content: str) -> FileOutline:
        language = detect_language(path)
        lines = content.splitlines()
        symbols = []
        imports = []

        if language == 'python':
            symbols, imports = self._parse_python(lines)
        elif language in ('typescript', 'javascript'):
            symbols, imports = self._parse_ts_js(lines)
        elif language == 'zig':
            symbols, imports = self._parse_zig(lines)
        elif language == 'rust':
            symbols, imports = self._parse_rust(lines)
        elif language == 'go':
            symbols, imports = self._parse_go(lines)
        elif language in ('c', 'cpp'):
            symbols, imports = self._parse_c_cpp(lines)
        elif language == 'php':
            symbols, imports = self._parse_php(lines)
        elif language == 'markdown':
            symbols = self._parse_markdown(lines)

        # Post-process to fix line_endings where possible
        self._fix_line_endings(symbols, len(lines))

        return FileOutline(
            path=path,
            language=language,
            line_count=len(lines),
            symbols=symbols,
            imports=imports
        )

    def _fix_line_endings(self, symbols: list[Symbol], total_lines: int):
        """Estimate line_end for symbols based on the start of the next symbol."""
        if not symbols:
            return
        # Sort by start line
        symbols.sort(key=lambda s: s.line_start)
        for i in range(len(symbols) - 1):
            # If line_end is same as line_start, try to extend it to just before the next symbol
            if symbols[i].line_end == symbols[i].line_start:
                symbols[i].line_end = max(symbols[i].line_start, symbols[i+1].line_start - 1)
        # Last symbol goes to end of file if it's a block-like symbol
        if symbols[-1].line_end == symbols[-1].line_start:
            symbols[-1].line_end = total_lines

    def _parse_python(self, lines: list[str]) -> tuple[list[Symbol], list[str]]:
        symbols = []
        imports = []
        in_docstring = False
        docstring_char = None

        for i, line in enumerate(lines, 1):
            trimmed = line.strip()

            # Simplified docstring tracking (consistent with Project B logic)
            if not in_docstring:
                if '"""' in trimmed:
                    in_docstring = True
                    docstring_char = '"""'
                    # If it's a single-line docstring, flip back
                    if trimmed.count('"""') % 2 == 0:
                        in_docstring = False
                    if not trimmed.startswith('"""'): # Code before docstring
                        self._parse_python_line(trimmed.split('"""')[0], i, symbols, imports)
                    continue
                elif "'''" in trimmed:
                    in_docstring = True
                    docstring_char = "'''"
                    if trimmed.count("'''") % 2 == 0:
                        in_docstring = False
                    if not trimmed.startswith("'''"):
                        self._parse_python_line(trimmed.split("'''")[0], i, symbols, imports)
                    continue
            else:
                if docstring_char in trimmed:
                    in_docstring = False
                continue

            if trimmed.startswith('#') or not trimmed:
                continue

            self._parse_python_line(trimmed, i, symbols, imports)

        return symbols, imports

    def _parse_python_line(self, trimmed: str, line_num: int, symbols: list[Symbol], imports: list[str]):
        # Functions
        if trimmed.startswith('def '):
            match = re.match(r'def\s+([a-zA-Z_]\w*)', trimmed)
            if match:
                symbols.append(Symbol(match.group(1), SymbolKind.FUNCTION, line_num, line_num, trimmed))
        # Classes
        elif trimmed.startswith('class '):
            match = re.match(r'class\s+([a-zA-Z_]\w*)', trimmed)
            if match:
                symbols.append(Symbol(match.group(1), SymbolKind.CLASS, line_num, line_num, trimmed))
        # Imports
        elif trimmed.startswith('import ') or trimmed.startswith('from '):
            symbols.append(Symbol("import", SymbolKind.IMPORT, line_num, line_num, trimmed))
            if trimmed.startswith('import '):
                modules = trimmed[7:].split(',')
                for m in modules:
                    m_name = m.strip().split()[0]
                    if m_name:
                        imports.append(m_name)
            else: # from ... import ...
                match = re.match(r'from\s+([\w.]+)\s+import', trimmed)
                if match:
                    imports.append(match.group(1))

    def _parse_ts_js(self, lines: list[str]) -> tuple[list[Symbol], list[str]]:
        symbols = []
        imports = []
        in_block_comment = False

        for i, line in enumerate(lines, 1):
            trimmed = line.strip()
            if not trimmed:
                continue

            if in_block_comment:
                if '*/' in trimmed:
                    in_block_comment = False
                    # Check if there's code after the comment end
                    after = trimmed.split('*/')[-1].strip()
                    if after:
                        self._parse_ts_js_line(after, i, symbols, imports)
                continue

            if '/*' in trimmed:
                if '*/' not in trimmed:
                    in_block_comment = True
                # Parse part before /*
                before = trimmed.split('/*')[0].strip()
                if before:
                    self._parse_ts_js_line(before, i, symbols, imports)
                continue

            if trimmed.startswith('//'):
                continue

            self._parse_ts_js_line(trimmed, i, symbols, imports)

        return symbols, imports

    def _parse_ts_js_line(self, trimmed: str, line_num: int, symbols: list[Symbol], imports: list[str]):
        # Functions / Methods
        if 'function ' in trimmed or '=>' in trimmed:
            match = re.search(r'function\s+([a-zA-Z_]\w*)', trimmed) or \
                    re.search(r'(?:const|let|var)\s+([a-zA-Z_]\w*)\s*=', trimmed)
            if match:
                symbols.append(Symbol(match.group(1), SymbolKind.FUNCTION, line_num, line_num, trimmed))

        # Classes / Interfaces
        if trimmed.startswith('class ') or trimmed.startswith('interface '):
            kind = SymbolKind.CLASS if trimmed.startswith('class ') else SymbolKind.INTERFACE
            match = re.match(r'(?:class|interface)\s+([a-zA-Z_]\w*)', trimmed)
            if match:
                symbols.append(Symbol(match.group(1), kind, line_num, line_num, trimmed))

        # Imports
        if trimmed.startswith('import '):
            symbols.append(Symbol("import", SymbolKind.IMPORT, line_num, line_num, trimmed))
            match = re.search(r"import\s+.*\s+from\s+['\"](.*)['\"]", trimmed)
            if match:
                imports.append(match.group(1))

    def _parse_zig(self, lines: list[str]) -> tuple[list[Symbol], list[str]]:
        symbols = []
        imports = []
        for i, line in enumerate(lines, 1):
            trimmed = line.strip()
            if 'fn ' in trimmed:
                match = re.search(r'fn\s+([a-zA-Z_]\w*)', trimmed)
                if match:
                    symbols.append(Symbol(match.group(1), SymbolKind.FUNCTION, i, i, line))
            elif 'const ' in trimmed:
                if 'struct {' in trimmed or 'enum {' in trimmed or 'union {' in trimmed:
                    kind = SymbolKind.STRUCT if 'struct {' in trimmed else SymbolKind.ENUM
                    match = re.search(r'const\s+([a-zA-Z_]\w*)', trimmed)
                    if match:
                        symbols.append(Symbol(match.group(1), kind, i, i, line))
                elif '@import(' in trimmed:
                    match = re.search(r"@import\(['\"](.*)['\"]\)", trimmed)
                    if match:
                        imports.append(match.group(1))
        return symbols, imports

    def _parse_rust(self, lines: list[str]) -> tuple[list[Symbol], list[str]]:
        symbols = []
        imports = []
        for i, line in enumerate(lines, 1):
            trimmed = line.strip()
            if trimmed.startswith(('pub fn ', 'fn ')):
                match = re.search(r'fn\s+([a-zA-Z_]\w*)', trimmed)
                if match:
                    symbols.append(Symbol(match.group(1), SymbolKind.FUNCTION, i, i, line))
            elif trimmed.startswith(('pub struct ', 'struct ', 'pub enum ', 'enum ')):
                kind = SymbolKind.STRUCT if 'struct ' in trimmed else SymbolKind.ENUM
                match = re.search(r'(?:struct|enum)\s+([a-zA-Z_]\w*)', trimmed)
                if match:
                    symbols.append(Symbol(match.group(1), kind, i, i, line))
            elif trimmed.startswith(('pub use ', 'use ', 'mod ', 'pub mod ')):
                match = re.search(r'(?:use|mod)\s+([\w:]+)', trimmed)
                if match:
                    imports.append(match.group(1))
        return symbols, imports

    def _parse_go(self, lines: list[str]) -> tuple[list[Symbol], list[str]]:
        symbols = []
        imports = []
        for i, line in enumerate(lines, 1):
            trimmed = line.strip()
            if trimmed.startswith('func '):
                match = re.search(r'func\s+(?:\(.*\)\s+)?([a-zA-Z_]\w*)', trimmed)
                if match:
                    symbols.append(Symbol(match.group(1), SymbolKind.FUNCTION, i, i, line))
            elif trimmed.startswith('type ') and 'struct {' in trimmed:
                match = re.search(r'type\s+([a-zA-Z_]\w*)\s+struct', trimmed)
                if match:
                    symbols.append(Symbol(match.group(1), SymbolKind.STRUCT, i, i, line))
            elif trimmed.startswith('import '):
                match = re.search(r'import\s+["\'](.*)["\']', trimmed)
                if match:
                    imports.append(match.group(1))
        return symbols, imports

    def _parse_c_cpp(self, lines: list[str]) -> tuple[list[Symbol], list[str]]:
        symbols = []
        imports = []
        for i, line in enumerate(lines, 1):
            trimmed = line.strip()
            # Very basic C++ parsing
            if '(' in trimmed and ')' in trimmed and '{' in trimmed and not trimmed.startswith(('#', '//', '/*')):
                match = re.search(r'([a-zA-Z_]\w*)\s*\(', trimmed)
                if match:
                    symbols.append(Symbol(match.group(1), SymbolKind.FUNCTION, i, i, line))
            elif 'class ' in trimmed or 'struct ' in trimmed:
                match = re.search(r'(?:class|struct)\s+([a-zA-Z_]\w*)', trimmed)
                if match:
                    symbols.append(Symbol(match.group(1), SymbolKind.CLASS, i, i, line))
            elif trimmed.startswith('#include '):
                match = re.search(r'#include\s+[<"](.*)[>"]', trimmed)
                if match:
                    imports.append(match.group(1))
        return symbols, imports

    def _parse_php(self, lines: list[str]) -> tuple[list[Symbol], list[str]]:
        symbols = []
        imports = []
        for i, line in enumerate(lines, 1):
            trimmed = line.strip()
            if 'function ' in trimmed:
                match = re.search(r'function\s+([a-zA-Z_]\w*)', trimmed)
                if match:
                    symbols.append(Symbol(match.group(1), SymbolKind.FUNCTION, i, i, line))
            elif 'class ' in trimmed or 'trait ' in trimmed or 'interface ' in trimmed:
                match = re.search(r'(?:class|trait|interface)\s+([a-zA-Z_]\w*)', trimmed)
                if match:
                    symbols.append(Symbol(match.group(1), SymbolKind.CLASS, i, i, line))
            elif trimmed.startswith('use ') and '\\' in trimmed:
                match = re.search(r'use\s+([\w\\]+)', trimmed)
                if match:
                    imports.append(match.group(1))
        return symbols, imports

    def _parse_markdown(self, lines: list[str]) -> list[Symbol]:
        symbols = []
        for i, line in enumerate(lines, 1):
            if line.startswith('# '):
                symbols.append(Symbol(line[2:].strip(), SymbolKind.MARKDOWN_H1, i, i))
            elif line.startswith('## '):
                symbols.append(Symbol(line[3:].strip(), SymbolKind.MARKDOWN_H2, i, i))
            elif line.startswith('### '):
                symbols.append(Symbol(line[4:].strip(), SymbolKind.MARKDOWN_H3, i, i))
        return symbols
