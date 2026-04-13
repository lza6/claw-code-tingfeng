"""Scope Detector — Identifies the enclosing symbol (function/class) for a given line.
Ported from Project B's findEnclosingSymbolLocked.
"""
from __future__ import annotations

from .symbol_extractor import FileOutline, Symbol


class ScopeDetector:
    """Helper to find which symbol a specific line belongs to."""

    @staticmethod
    def find_enclosing_symbol(outline: FileOutline, line_num: int) -> Symbol | None:
        """Find the smallest enclosing symbol for a given line."""
        best: Symbol | None = None
        best_span: int = float('inf')

        for sym in outline.symbols:
            if sym.line_start <= line_num <= sym.line_end:
                span = sym.line_end - sym.line_start
                if span < best_span:
                    best = sym
                    best_span = span

        if best:
            return best

        # Fallback: nearest preceding symbol (e.g., if line_end is not perfectly accurate)
        nearest: Symbol | None = None
        nearest_dist: int = float('inf')

        for sym in outline.symbols:
            if sym.line_start <= line_num:
                dist = line_num - sym.line_start
                if dist < nearest_dist:
                    nearest = sym
                    nearest_dist = dist

        return nearest
