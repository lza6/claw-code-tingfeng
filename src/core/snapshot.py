"""Codebase Snapshot — Ported from Project B (snapshot.zig)

Serializes the entire indexing state into a portable JSON file.
Enables instant hot-starts for the MCP server.
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path
from typing import Any

from .indexing import TrigramIndex, WordIndex
from .symbol_index import SymbolIndex


class CodebaseSnapshot:
    """Handles serialization of the entire codebase state."""

    @staticmethod
    def create_snapshot(
        t_index: TrigramIndex,
        w_index: WordIndex,
        s_index: SymbolIndex,
        metadata: dict[str, Any] | None = None
    ) -> str:
        """Create a full JSON snapshot of the codebase state."""
        data = {
            "version": "1.0.0",
            "metadata": metadata or {},
            "trigram_index": {
                "doc_paths": t_index.doc_paths,
                # Convert array.array to list for JSON serialization
                "postings": {str(k): list(v) for k, v in t_index.postings.items()}
            },
            "word_index": {
                "doc_paths": w_index.doc_paths,
                "index": w_index.index
            },
            "symbol_index": s_index.to_dict()
        }
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def save_snapshot(path: Path, snapshot_json: str, compress: bool = True):
        """Save snapshot to disk, optionally compressed."""
        if compress:
            # Use zlib compression to save space (Project B uses a custom binary format,
            # but compressed JSON is a good middle ground for Python)
            compressed = zlib.compress(snapshot_json.encode('utf-8'))
            path.write_bytes(compressed)
        else:
            path.write_text(snapshot_json, encoding='utf-8')

    @staticmethod
    def load_snapshot(path: Path) -> dict[str, Any]:
        """Load and decompress a snapshot from disk."""
        if not path.exists():
            raise FileNotFoundError(f"Snapshot not found: {path}")

        data = path.read_bytes()
        try:
            # Try decompressing
            decompressed = zlib.decompress(data).decode('utf-8')
            return json.loads(decompressed)
        except zlib.error:
            # If not compressed, read as plain text
            return json.loads(data.decode('utf-8'))
