"""Word Index — Inverted index for fast keyword search with line hits.
Ported from Project B (Zig core).
"""
from __future__ import annotations

import re
from typing import NamedTuple


class WordHit(NamedTuple):
    """A single occurrence of a word."""
    path: str
    line_num: int

class WordIndex:
    """An inverted index mapping words to (file, line) locations.

    Ported from Project B's WordIndex. Optimized for low memory and fast re-indexing.
    """

    def __init__(self):
        # word -> List[WordHit]
        self.index: dict[str, list[WordHit]] = {}
        # path -> Set of words contributed (for efficient cleanup)
        self.file_words: dict[str, set[str]] = {}

    def remove_file(self, path: str):
        """Remove all hits belonging to the given path."""
        words = self.file_words.get(path, set())
        for word in words:
            if word in self.index:
                # Remove hits for this path
                # Project B uses swapRemove for speed; here we use list comprehension
                self.index[word] = [h for h in self.index[word] if h.path != path]
                if not self.index[word]:
                    del self.index[word]

        if path in self.file_words:
            del self.file_words[path]

    def index_file(self, path: str, content: str):
        """Tokenize content and index words with line numbers."""
        self.remove_file(path)

        current_file_words: set[str] = set()

        lines = content.splitlines()
        for i, line in enumerate(lines):
            line_num = i + 1
            # Simple tokenization: alphanumeric sequences >= 2 chars
            # Consistent with Project B's WordTokenizer
            words = re.findall(r'[a-zA-Z0-9_]{2,}', line.lower())

            for word in words:
                if word not in self.index:
                    self.index[word] = []

                # Avoid duplicate hits for the same word on the same line
                if self.index[word] and self.index[word][-1].path == path and self.index[word][-1].line_num == line_num:
                    continue

                self.index[word].append(WordHit(path, line_num))
                current_file_words.add(word)

        self.file_words[path] = current_file_words

    def search(self, word: str) -> list[WordHit]:
        """Search for a word, returning all file/line hits."""
        return self.index.get(word.lower(), [])

    def search_deduped(self, word: str) -> list[str]:
        """Search and return unique file paths containing the word."""
        hits = self.search(word)
        return sorted({h.path for h in hits})
