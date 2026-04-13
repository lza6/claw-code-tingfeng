"""Trigram Index — Ported from Project B (Zig core)

High-performance substring search index using 3-byte sequences (trigrams).
Provides O(N) candidate filtering for substring and regex queries.

Features:
- u24 trigram packing for memory efficiency.
- Sorted PostingLists with doc_id, next_mask, and loc_mask for fast verify.
- Bloom Filter style bitmask check to prune 80%+ of false positives without reading content.
"""
from __future__ import annotations

import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)

def normalize_char(c: int) -> int:
    """Normalize character for case-insensitive indexing (matching Project B)."""
    if ord('A') <= c <= ord('Z'):
        return c + (ord('a') - ord('A'))
    return c

def pack_trigram(a: int, b: int, c: int) -> int:
    """Pack three characters into a 24-bit integer."""
    return (a << 16) | (b << 8) | c

class PostingMask(NamedTuple):
    next_mask: int = 0  # Bloom filter of chars following this trigram
    loc_mask: int = 0   # Bit mask of (position % 8) where trigram appears

class DocPosting:
    __slots__ = ('doc_id', 'loc_mask', 'next_mask')
    def __init__(self, doc_id: int, next_mask: int = 0, loc_mask: int = 0):
        self.doc_id = doc_id
        self.next_mask = next_mask
        self.loc_mask = loc_mask

class RegexQuery(NamedTuple):
    """Structured regex query fragments for trigram acceleration."""
    and_trigrams: list[int] = []  # Trigrams that MUST be present
    or_groups: list[list[int]] = [] # One trigram from each list MUST be present

class TrigramIndex:
    """A memory-efficient trigram index for fast codebase search."""

    def __init__(self):
        # trigram (int) -> List[DocPosting] (sorted by doc_id)
        self.index: dict[int, list[DocPosting]] = {}
        # path -> doc_id
        self.path_to_id: dict[str, int] = {}
        # doc_id -> path
        self.id_to_path: list[str] = []
        # path -> Set of trigrams contributed (for cleanup)
        self.file_trigrams: dict[str, set[int]] = {}
        # path -> mtime (for incremental updates)
        self.file_mtimes: dict[str, float] = {}

    def get_or_create_doc_id(self, path: str) -> int:
        if path in self.path_to_id:
            return self.path_to_id[path]
        doc_id = len(self.id_to_path)
        self.id_to_path.append(path)
        self.path_to_id[path] = doc_id
        return doc_id

    def remove_file(self, path: str):
        """Remove a file from the index (call before re-indexing)."""
        doc_id = self.path_to_id.get(path)
        if doc_id is None:
            return

        trigrams = self.file_trigrams.get(path, set())
        for tri in trigrams:
            if tri in self.index:
                # Binary search to find and remove the posting
                postings = self.index[tri]
                self.index[tri] = [p for p in postings if p.doc_id != doc_id]
                if not self.index[tri]:
                    del self.index[tri]

        if path in self.file_trigrams:
            del self.file_trigrams[path]

        if path in self.file_mtimes:
            del self.file_mtimes[path]

        # We keep id_to_path stable, but remove from path_to_id
        if path in self.path_to_id:
            del self.path_to_id[path]

    def should_reindex(self, path: str) -> bool:
        """Check if a file needs to be re-indexed based on mtime."""
        import os
        if path not in self.path_to_id or path not in self.file_mtimes:
            return True
        try:
            current_mtime = os.path.getmtime(path)
            return current_mtime > self.file_mtimes[path]
        except (OSError, ValueError):
            return True

    def save(self, path: str):
        """Save index to disk (simple pickle for now)."""
        import pickle
        with open(path, 'wb') as f:
            # Note: DocPosting is __slots__, but indices can be pickled
            pickle.dump({
                'index': self.index,
                'path_to_id': self.path_to_id,
                'id_to_path': self.id_to_path,
                'file_trigrams': self.file_trigrams,
                'file_mtimes': self.file_mtimes,
            }, f)

    def update_index(self, root_dir: str | Path):
        """Perform incremental update of the index for a directory."""
        from pathlib import Path
        root = Path(root_dir).resolve()

        # Support common source file extensions
        extensions = {'.py', '.js', '.ts', '.c', '.cpp', '.h', '.go', '.rs', '.java'}

        indexed_count = 0
        removed_count = 0

        # Scan filesystem
        current_files = set()
        for path in root.rglob('*'):
            if path.is_file() and path.suffix in extensions:
                abs_path = str(path.resolve())
                current_files.add(abs_path)

                if self.should_reindex(abs_path):
                    try:
                        content = path.read_text(encoding='utf-8', errors='replace')
                        self.index_file(abs_path, content)
                        indexed_count += 1
                        logger.debug(f"Indexed: {abs_path}")
                    except Exception as e:
                        logger.error(f"Failed to index {abs_path}: {e}")

        # Cleanup deleted files
        indexed_paths = list(self.path_to_id.keys())
        for path in indexed_paths:
            if path not in current_files:
                self.remove_file(path)
                removed_count += 1

        logger.info(f"Incremental update complete: indexed {indexed_count} files, removed {removed_count} files.")

    def index_file(self, path: str, content: str):
        """Index a file's content using trigrams."""
        import os
        try:
            mtime = os.path.getmtime(path)
            self.file_mtimes[path] = mtime
        except (OSError, ValueError):
            pass

        self.remove_file(path)
        doc_id = self.get_or_create_doc_id(path)

        local_postings: dict[int, list] = {}

        encoded = content.encode('utf-8', errors='replace')
        if len(encoded) < 3:
            return

        ws = {ord(' '), ord('\t'), ord('\n'), ord('\r')}

        for i in range(len(encoded) - 2):
            c0, c1, c2 = encoded[i], encoded[i+1], encoded[i+2]
            # [Optimization] Skip whitespace-only trigrams (terrible filters, ~12% of total)
            # Consistent with Project B's logic.
            if c0 in ws and c1 in ws and c2 in ws:
                continue

            tri = pack_trigram(normalize_char(c0), normalize_char(c1), normalize_char(c2))

            if tri not in local_postings:
                local_postings[tri] = [0, 0]

            masks = local_postings[tri]
            masks[1] |= (1 << (i % 8))
            if i + 3 < len(encoded):
                masks[0] |= (1 << (normalize_char(encoded[i+3]) % 8))

        file_tris = set()
        for tri, (next_mask, loc_mask) in local_postings.items():
            if tri not in self.index:
                self.index[tri] = []
            self.index[tri].append(DocPosting(doc_id, next_mask, loc_mask))
            file_tris.add(tri)
        self.file_trigrams[path] = file_tris

    def get_candidates(self, query: str) -> list[str] | None:
        """Find candidate files containing ALL trigrams of the query.

        Uses rotated bitmasks to verify trigram adjacency without reading files.
        """
        if not query or len(query) < 3:
            return None

        encoded_query = query.encode('utf-8', errors='replace')
        tri_count = len(encoded_query) - 2

        query_tris = []
        unique_seen = set()
        for i in range(tri_count):
            tri = pack_trigram(normalize_char(encoded_query[i]), normalize_char(encoded_query[i+1]), normalize_char(encoded_query[i+2]))
            if tri not in unique_seen:
                query_tris.append(tri)
                unique_seen.add(tri)

        sets: list[list[DocPosting]] = []
        for tri in query_tris:
            if tri not in self.index:
                return []
            sets.append(self.index[tri])

        if not sets:
            return []

        sets.sort(key=len)
        result_ids = [p.doc_id for p in sets[0]]

        for s in sets[1:]:
            new_results = []
            si = 0
            for rid in result_ids:
                while si < len(s) and s[si].doc_id < rid:
                    si += 1
                if si < len(s) and s[si].doc_id == rid:
                    new_results.append(rid)
                    si += 1
            result_ids = new_results
            if not result_ids:
                break

        final_candidates = []
        for doc_id in result_ids:
            possible = True
            for j in range(tri_count - 1):
                tri_a = pack_trigram(normalize_char(encoded_query[j]), normalize_char(encoded_query[j+1]), normalize_char(encoded_query[j+2]))
                tri_b = pack_trigram(normalize_char(encoded_query[j+1]), normalize_char(encoded_query[j+2]), normalize_char(encoded_query[j+3]))

                mask_a = self._get_posting(tri_a, doc_id)
                mask_b = self._get_posting(tri_b, doc_id)

                if not mask_a or not mask_b:
                    possible = False
                    break

                next_char_bit = (1 << (normalize_char(encoded_query[j+3]) % 8))
                if not (mask_a.next_mask & next_char_bit):
                    possible = False
                    break

                rotated = ((mask_a.loc_mask << 1) & 0xFF) | (mask_a.loc_mask >> 7)
                if not (rotated & mask_b.loc_mask):
                    possible = False
                    break

            if possible:
                final_candidates.append(self.id_to_path[doc_id])

        return final_candidates

    def candidates_regex(self, query: RegexQuery) -> list[str] | None:
        """Find candidates satisfying complex regex AND/OR trigram requirements.

        Ported from Project B's candidatesRegex.
        """
        if not query.and_trigrams and not query.or_groups:
            return None

        result_ids: set[int] | None = None

        # Process AND requirements
        for tri in query.and_trigrams:
            postings = self.index.get(tri)
            if postings is None:
                return []

            ids = {p.doc_id for p in postings}
            if result_ids is None:
                result_ids = ids
            else:
                result_ids &= ids
                if not result_ids:
                    return []

        # Process OR requirements (groups where at least one trigram must match)
        for group in query.or_groups:
            if not group:
                continue

            group_ids: set[int] = set()
            for tri in group:
                postings = self.index.get(tri)
                if postings:
                    group_ids.update(p.doc_id for p in postings)

            if result_ids is None:
                result_ids = group_ids
            else:
                result_ids &= group_ids
                if not result_ids:
                    return []

        if result_ids is None:
            return None

        return [self.id_to_path[rid] for rid in sorted(result_ids)]

    def _get_posting(self, trigram: int, doc_id: int) -> DocPosting | None:
        postings = self.index.get(trigram)
        if not postings:
            return None
        lo, hi = 0, len(postings) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if postings[mid].doc_id == doc_id:
                return postings[mid]
            if postings[mid].doc_id < doc_id:
                lo = mid + 1
            else:
                hi = mid - 1
        return None
