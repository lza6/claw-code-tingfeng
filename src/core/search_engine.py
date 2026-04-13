"""Search Engine - High-performance Trigram and Word indices.

Ported from Project B (Codedb) Zig implementation.
"""
from __future__ import annotations

import collections
import contextlib
import re
from pathlib import Path

# --- Inverted Word Index ---

class WordHit:
    def __init__(self, path: str, line_num: int):
        self.path = path
        self.line_num = line_num

    def __repr__(self) -> str:
        return f"WordHit({self.path}, {self.line_num})"

class WordIndex:
    """O(1) word lookup index.

    Maps word -> list of (path, line) hits.
    """
    def __init__(self):
        self.index: dict[str, list[WordHit]] = collections.defaultdict(list)
        self.file_words: dict[str, set[str]] = collections.defaultdict(set)

    def remove_file(self, path: str):
        """Remove all entries for a file."""
        if path not in self.file_words:
            return

        words = self.file_words.pop(path)
        for word in words:
            if word in self.index:
                # Filter out hits for this path
                self.index[word] = [hit for hit in self.index[word] if hit.path != path]
                if not self.index[word]:
                    self.index.pop(word)

    def index_file(self, path: str, content: str):
        """Tokenize and index words."""
        self.remove_file(path)

        lines = content.splitlines()
        for i, line in enumerate(lines):
            line_num = i + 1
            # Simple word tokenizer: alphanumeric and underscores
            words = re.findall(r'\w+', line)
            for word in words:
                if len(word) < 2:
                    continue

                # Deduplicate hits on the same line
                if self.index[word] and self.index[word][-1].path == path and self.index[word][-1].line_num == line_num:
                    continue

                hit = WordHit(path, line_num)
                self.index[word].append(hit)
                self.file_words[path].add(word)

    def search(self, word: str) -> list[WordHit]:
        """Look up all hits for a word."""
        return self.index.get(word, [])

# --- Trigram Index ---

class TrigramIndex:
    """Trigram-accelerated substring search.

    Ported from Codedb v2 (Zig).
    Maps 3-byte sequences -> set of file paths.
    """
    def __init__(self):
        # Trigram (int) -> List of (Doc ID, next_mask, loc_mask)
        self.index: dict[int, list[tuple[int, int, int]]] = collections.defaultdict(list)
        self.file_trigrams: dict[str, set[int]] = collections.defaultdict(set)
        self.id_to_path: list[str] = []
        self.path_to_id: dict[str, int] = {}

    def _get_or_create_id(self, path: str) -> int:
        if path in self.path_to_id:
            return self.path_to_id[path]
        doc_id = len(self.id_to_path)
        self.id_to_path.append(path)
        self.path_to_id[path] = doc_id
        return doc_id

    @staticmethod
    def pack_trigram(a: int, b: int, c: int) -> int:
        """Pack 3 chars (0-255) into a 24-bit integer."""
        return (a << 16) | (b << 8) | c

    @staticmethod
    def normalize_char(c: str) -> int:
        """Case-insensitive normalization."""
        return ord(c.lower()) if len(c) == 1 else 0

    def remove_file(self, path: str):
        if path not in self.path_to_id:
            return

        doc_id = self.path_to_id[path]
        trigrams = self.file_trigrams.pop(path, set())
        for tri in trigrams:
            if tri in self.index:
                # Remove this doc_id from the posting list
                # Postings are sorted by doc_id in Zig, we use list here
                with contextlib.suppress(ValueError):
                    self.index[tri].remove(doc_id)
                if not self.index[tri]:
                    self.index.pop(tri)

        # Note: id_to_path is not fully re-compacted for performance,
        # but path_to_id is cleared. In practice, snapshots handle this.
        self.path_to_id.pop(path)

    def index_file(self, path: str, content: str):
        self.remove_file(path)
        doc_id = self._get_or_create_id(path)

        if len(content) < 3:
            return

        content_lower = content.lower()
        # local_masks: trigram -> (next_mask, loc_mask)
        local_masks: dict[int, list[int]] = collections.defaultdict(lambda: [0, 0])

        for i in range(len(content_lower) - 2):
            c0 = content_lower[i]
            c1 = content_lower[i+1]
            c2 = content_lower[i+2]

            if c0.isspace() and c1.isspace() and c2.isspace():
                continue

            tri = self.pack_trigram(ord(c0), ord(c1), ord(c2))
            # Update loc_mask (bit position % 8)
            local_masks[tri][1] |= (1 << (i % 8))
            # Update next_mask if there's a 4th char
            if i + 3 < len(content_lower):
                c3 = content_lower[i+3]
                local_masks[tri][0] |= (1 << (ord(c3) % 8))

        for tri, (nm, lm) in local_masks.items():
            self.index[tri].append((doc_id, nm, lm))
            self.file_trigrams[path].add(tri)

    def candidates(self, query: str) -> set[str] | None:
        """Find candidate files containing ALL trigrams of the query."""
        if len(query) < 3:
            return None

        query_lower = query.lower()
        unique_trigrams = set()
        for i in range(len(query_lower) - 2):
            tri = self.pack_trigram(ord(query_lower[i]), ord(query_lower[i+1]), ord(query_lower[i+2]))
            unique_trigrams.add(tri)

        if not unique_trigrams:
            return None

        # Smallest posting list first (optimization)
        sorted_tris = sorted(unique_trigrams, key=lambda t: len(self.index.get(t, [])))

        # Check first trigram
        first_postings = self.index.get(sorted_tris[0])
        if not first_postings:
            return set()

        # result_ids: doc_id -> (next_mask, loc_mask) for current query trigram
        # We start with the first trigram's doc IDs
        result_doc_masks: dict[int, list[int]] = {p[0]: [p[1], p[2]] for p in first_postings}

        for tri in sorted_tris[1:]:
            if not result_doc_masks:
                break

            current_postings = {p[0]: (p[1], p[2]) for p in self.index.get(tri, [])}
            # Intersection
            new_doc_masks = {}
            for doc_id in result_doc_masks:
                if doc_id in current_postings:
                    # Logic here: we just need the doc_id to be in ALL trigram indices.
                    # The masks are used in the refinement step next.
                    new_doc_masks[doc_id] = result_doc_masks[doc_id]
            result_doc_masks = new_doc_masks

        # Refinement using Bloom filters/Masks (Ported from Codedb candidates)
        final_candidates = set()
        for doc_id in result_doc_masks:
            # Check consecutive trigram pairs
            tri_count = len(query_lower) - 2
            if tri_count >= 2:
                possible = True
                for j in range(tri_count - 1):
                    tri_a = self.pack_trigram(ord(query_lower[j]), ord(query_lower[j+1]), ord(query_lower[j+2]))
                    tri_b = self.pack_trigram(ord(query_lower[j+1]), ord(query_lower[j+2]), ord(query_lower[j+3]))

                    # Find doc entries in index for tri_a and tri_b
                    # This is slightly slower in Python than Zig, but avoids false positives
                    post_a = next((p for p in self.index.get(tri_a, []) if p[0] == doc_id), None)
                    post_b = next((p for p in self.index.get(tri_b, []) if p[0] == doc_id), None)

                    if not post_a or not post_b:
                        possible = False
                        break

                    nm_a, lm_a = post_a[1], post_a[2]
                    _nm_b, lm_b = post_b[1], post_b[2]

                    # 1. next_mask check
                    next_bit = (1 << (ord(query_lower[j+3]) % 8))
                    if not (nm_a & next_bit):
                        possible = False
                        break

                    # 2. loc_mask rotation check (rotated 1 bit left)
                    rotated_lm_a = ((lm_a << 1) | (lm_a >> 7)) & 0xFF
                    if not (rotated_lm_a & lm_b):
                        possible = False
                        break

                if possible:
                    final_candidates.add(self.id_to_path[doc_id])
            else:
                final_candidates.add(self.id_to_path[doc_id])

        return final_candidates

# --- Unified Search Engine ---

class SearchEngine:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.word_index = WordIndex()
        self.trigram_index = TrigramIndex()
        self._indexed_files: set[str] = set()

    def index_project(self):
        """Index all files in the project."""
        from .utils.ignore_parser import should_ignore
        for path in self.root_dir.rglob('*'):
            if path.is_file() and not should_ignore(path):
                try:
                    content = path.read_text(errors='ignore')
                    rel_path = str(path.relative_to(self.root_dir))
                    self.index_file(rel_path, content)
                except Exception:
                    continue

    def index_file(self, rel_path: str, content: str):
        self.word_index.index_file(rel_path, content)
        self.trigram_index.index_file(rel_path, content)
        self._indexed_files.add(rel_path)

    def search_word(self, word: str) -> list[WordHit]:
        return self.word_index.search(word)

    def search_substring(self, query: str) -> list[str]:
        """High-performance substring search."""
        candidates = self.trigram_index.candidates(query)
        if candidates is None:
            # Fallback to brute force or return empty
            return []

        # Refine candidates with actual string search (to avoid false positives with Bloom filters/collisions)
        results = []
        for path in candidates:
            abs_path = self.root_dir / path
            try:
                # In a real impl, we'd cache content or use mmap
                content = abs_path.read_text(errors='ignore')
                if query.lower() in content.lower():
                    results.append(path)
            except Exception:
                continue
        return results
