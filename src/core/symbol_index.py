"""Global Symbol Index — Ported from Project B

Maintains a mapping of symbol names to their home files and line ranges.
Allows the AI agent to jump to any definition instantly.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ..rag.symbol_extractor import SymbolExtractor


@dataclass
class SymbolLocation:
    path: str
    line_start: int
    line_end: int
    kind: str
    detail: str | None = None

class SymbolIndex:
    """Global symbol registry."""
    def __init__(self):
        # symbol_name -> list of locations (multiple definitions allowed, e.g. overloaded or same name in different modules)
        self.index: dict[str, list[SymbolLocation]] = {}
        self.extractor = SymbolExtractor()

    def add_file(self, path: str, content: str):
        """Extract symbols from a file and add them to the index."""
        outline = self.extractor.extract(path, content)
        # Clear existing entries for this file to handle re-indexing
        self._clear_file(path)

        for sym in outline.symbols:
            loc = SymbolLocation(
                path=path,
                line_start=sym.line_start,
                line_end=sym.line_end,
                kind=sym.kind.value,
                detail=sym.detail
            )
            if sym.name not in self.index:
                self.index[sym.name] = []
            self.index[sym.name].append(loc)

    def _clear_file(self, path: str):
        """Remove all symbols associated with a specific file."""
        for name in list(self.index.keys()):
            self.index[name] = [loc for loc in self.index[name] if loc.path != path]
            if not self.index[name]:
                del self.index[name]

    def find_symbol(self, name: str) -> list[SymbolLocation]:
        """Find all locations where a symbol name is defined."""
        return self.index.get(name, [])

    def to_dict(self) -> dict:
        return {name: [asdict(loc) for loc in locs] for name, locs in self.index.items()}

    @classmethod
    def from_dict(cls, data: dict) -> SymbolIndex:
        idx = cls()
        for name, locs in data.items():
            idx.index[name] = [SymbolLocation(**loc) for loc in locs]
        return idx
