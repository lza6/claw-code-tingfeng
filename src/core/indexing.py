"""Indexing Core — Ported from Project B (index.zig)

Provides Trigram v2 indexing and Inverted Word Index for sub-millisecond search performance.
Uses integer document IDs and bitmask-based trigram lookups.
"""
from __future__ import annotations

import array
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TrigramIndex:
    """Trigram v2 indexing core.

    Uses integer document IDs and sorted posting lists for fast intersect/union.
    """
    doc_paths: list[str] = field(default_factory=list)
    # trigram (3 chars) -> sorted list of doc_ids
    postings: dict[int, array.array] = field(default_factory=dict)

    def _to_trigrams(self, text: str) -> set[int]:
        """Convert text to a set of integer trigrams using 21-bit encoding (7 bits per char).
        Lowercases for case-insensitivity.
        """
        trigrams: set[int] = set()
        text = text.lower()
        if len(text) < 3:
            return trigrams

        data = text.encode('ascii', errors='ignore')
        for i in range(len(data) - 2):
            # Encode 3 chars into 24 bits (8 bits per char)
            t = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2]
            trigrams.add(t)
        return trigrams

    def add_document(self, path: str, content: str) -> None:
        doc_id = len(self.doc_paths)
        self.doc_paths.append(path)

        trigrams = self._to_trigrams(content)
        for t in trigrams:
            if t not in self.postings:
                self.postings[t] = array.array('I')
            self.postings[t].append(doc_id)

    def search(self, query: str) -> list[str]:
        if not query:
            return []

        if len(query) < 3:
            return []

        query_trigrams = self._to_trigrams(query)
        if not query_trigrams:
            return []

        result_doc_ids: set[int] = set()
        first = True

        for t in query_trigrams:
            if t not in self.postings:
                return []

            docs = set(self.postings[t])
            if first:
                result_doc_ids = docs
                first = False
            else:
                result_doc_ids &= docs
                if not result_doc_ids:
                    break

        return [self.doc_paths[did] for did in sorted(result_doc_ids)]


@dataclass
class WordIndex:
    """Inverted Word Index for O(1) identifier lookup."""
    # word -> list of (doc_id, line_num)
    index: dict[str, list[tuple[int, int]]] = field(
        default_factory=lambda: dict()
    )
    doc_paths: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Ensure default_factory types are initialized."""
        if self.index is None:
            self.index = {}
        if self.doc_paths is None:
            self.doc_paths = []

    def add_document(self, path: str, content: str) -> None:
        doc_id = len(self.doc_paths)
        self.doc_paths.append(path)

        # Tokenize by non-alphanumeric (Project B logic)
        for line_num, line in enumerate(content.splitlines(), 1):
            words = set(re.findall(r'[a-zA-Z_]\w*', line))
            for word in words:
                if word not in self.index:
                    self.index[word] = []
                self.index[word].append((doc_id, line_num))

    def find_word(self, word: str) -> list[tuple[str, int]]:
        hits = self.index.get(word, [])
        return [(self.doc_paths[did], ln) for did, ln in hits]


def build_index(root: Path, file_pattern: str = "*.py") -> tuple[TrigramIndex, WordIndex]:
    t_index = TrigramIndex()
    w_index = WordIndex()

    for file_path in root.rglob(file_pattern):
        if not file_path.is_file() or '.git' in file_path.parts or '__pycache__' in file_path.parts:
            continue
        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
            rel_path = str(file_path.relative_to(root))
            t_index.add_document(rel_path, content)
            w_index.add_document(rel_path, content)
        except Exception:
            continue

    return t_index, w_index


__all__ = ['TrigramIndex', 'WordIndex', 'build_index']
