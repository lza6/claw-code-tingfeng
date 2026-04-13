"""Binary Format — Persistence for Trigram Index

Uses Python's struct module to save/load index data in a compact binary format,
minimizing JSON overhead and memory usage during serialization.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

from .trigram_index import DocPosting, TrigramIndex

# Magic numbers
POSTINGS_MAGIC = b'CDBT'
LOOKUP_MAGIC = b'CDBL'
FORMAT_VERSION = 3

class BinaryIndexWriter:
    def __init__(self, index: TrigramIndex):
        self.index = index

    def write(self, directory: str | Path):
        dir_path = Path(directory)
        dir_path.mkdir(parents=True, exist_ok=True)

        postings_path = dir_path / "trigram.postings"
        lookup_path = dir_path / "trigram.lookup"

        # 1. Prepare File Table
        # We only save files that have trigrams
        active_files = [path for path in self.index.id_to_path if path in self.index.path_to_id]
        path_to_fid = {path: i for i, path in enumerate(active_files)}

        # 2. Write Postings File
        with open(postings_path, "wb") as f:
            # Header: Magic(4) + Version(2) + FileCount(4) + SkipHead(41)
            f.write(POSTINGS_MAGIC)
            f.write(struct.pack("<H", FORMAT_VERSION))
            f.write(struct.pack("<I", len(active_files)))
            f.write(b'\x00' * 41) # Skip git head for now

            # File Table: (PathLen(H), Path)
            for path in active_files:
                p_bytes = path.encode('utf-8')
                f.write(struct.pack("<H", len(p_bytes)))
                f.write(p_bytes)

            # Postings Blob & Collect Lookup Entries
            lookup_entries = []
            current_offset = 0

            # Sort trigrams for consistent lookup
            sorted_trigrams = sorted(self.index.index.keys())

            for tri in sorted_trigrams:
                postings = self.index.index[tri]
                valid_postings = []
                for p in postings:
                    # Map doc_id to the new continuous file_id in this binary file
                    path = self.index.id_to_path[p.doc_id]
                    if path in path_to_fid:
                        valid_postings.append((path_to_fid[path], p.next_mask, p.loc_mask))

                if not valid_postings:
                    continue

                count = len(valid_postings)
                lookup_entries.append((tri, current_offset, count))

                for fid, nm, lm in valid_postings:
                    # Entry: FileID(I) + NextMask(B) + LocMask(B) + Pad(2) = 8 bytes
                    f.write(struct.pack("<IBBxx", fid, nm, lm))
                    current_offset += 1

        # 3. Write Lookup File
        with open(lookup_path, "wb") as f:
            # Header: Magic(4) + Version(2) + Pad(2) + EntryCount(4) = 12 bytes
            f.write(LOOKUP_MAGIC)
            f.write(struct.pack("<H", FORMAT_VERSION))
            f.write(b'\x00\x00')
            f.write(struct.pack("<I", len(lookup_entries)))

            # Entries: (Trigram(I), Offset(I), Count(I))
            for tri, offset, count in lookup_entries:
                f.write(struct.pack("<III", tri, offset, count))

class BinaryIndexReader:
    @staticmethod
    def load(directory: str | Path) -> Optional[TrigramIndex]:
        dir_path = Path(directory)
        postings_path = dir_path / "trigram.postings"
        lookup_path = dir_path / "trigram.lookup"

        if not postings_path.exists() or not lookup_path.exists():
            return None

        try:
            index = TrigramIndex()

            # Read Postings File
            with open(postings_path, "rb") as f:
                magic = f.read(4)
                if magic != POSTINGS_MAGIC: return None
                version = struct.unpack("<H", f.read(2))[0]
                if version != FORMAT_VERSION: return None
                file_count = struct.unpack("<I", f.read(4))[0]
                f.seek(41, os.SEEK_CUR) # Skip head

                # File Table
                for _ in range(file_count):
                    plen = struct.unpack("<H", f.read(2))[0]
                    path = f.read(plen).decode('utf-8')
                    index.get_or_create_doc_id(path)

                postings_start = f.tell()
                # We'll read postings based on lookup

                # Read Lookup File
                with open(lookup_path, "rb") as fl:
                    lmagic = fl.read(4)
                    if lmagic != LOOKUP_MAGIC: return None
                    lversion = struct.unpack("<H", fl.read(2))[0]
                    if lversion != FORMAT_VERSION: return None
                    fl.seek(2, os.SEEK_CUR) # Skip pad
                    entry_count = struct.unpack("<I", fl.read(4))[0]

                    for _ in range(entry_count):
                        tri, offset, count = struct.unpack("<III", fl.read(12))

                        # Go back to postings file to read the blob
                        f.seek(postings_start + offset * 8)
                        p_list = []
                        for _ in range(count):
                            fid, nm, lm = struct.unpack("<IBB", f.read(6))
                            f.seek(2, os.SEEK_CUR) # Skip pad
                            p_list.append(DocPosting(fid, nm, lm))

                        index.index[tri] = p_list
                        # Re-populate file_trigrams for cleanup consistency
                        for p in p_list:
                            path = index.id_to_path[p.doc_id]
                            if path not in index.file_trigrams:
                                index.file_trigrams[path] = set()
                            index.file_trigrams[path].add(tri)

            return index
        except Exception:
            return None
