"""索引器持久化模块 - 索引保存与加载

从 text_indexer.py 拆分，负责：
- 索引保存 (save_index)
- 索引加载 (load_index)
- 支持新旧两种格式
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .binary_format import BinaryIndexReader, BinaryIndexWriter
from .models import Chunk, Document


def save_index_v2(
    index_path: Path,
    documents: dict[str, Document],
    chunks: dict[str, Chunk],
    word_index: dict[str, Any],
) -> None:
    """保存索引到目录（新格式）

    参数:
        index_path: 索引目录路径
        documents: 文档字典
        chunks: chunk 字典
        word_index: 词索引
    """
    index_path.mkdir(parents=True, exist_ok=True)
    docs_dir = index_path / 'documents'
    chunks_dir = index_path / 'chunks'
    docs_dir.mkdir(exist_ok=True)
    chunks_dir.mkdir(exist_ok=True)

    doc_refs: dict[str, dict[str, Any]] = {}
    for doc_id, doc in documents.items():
        doc_data = {
            'id': doc.id,
            'source': doc.source,
            'metadata': doc.metadata,
        }
        doc_refs[doc_id] = doc_data
        doc_content_path = docs_dir / f'{doc_id}.json'
        doc_content_path.write_text(json.dumps({
            'id': doc.id,
            'content': doc.content,
        }, ensure_ascii=False))

    chunk_refs: dict[str, dict[str, Any]] = {}
    for chunk_id, chunk in chunks.items():
        chunk_refs[chunk_id] = {
            'id': chunk.id,
            'document_id': chunk.document_id,
            'start_pos': chunk.start_pos,
            'end_pos': chunk.end_pos,
            'metadata': chunk.metadata,
        }
        chunk_content_path = chunks_dir / f'{chunk_id}.json'
        chunk_content_path.write_text(json.dumps({
            'content': chunk.content,
        }, ensure_ascii=False))

    index_data = {
        'version': '2',
        'document_refs': doc_refs,
        'chunk_refs': chunk_refs,
        'inverted_index': {
            word: [h.path for h in hits]
            for word, hits in word_index.items()
        },
    }
    meta_path = index_path / 'index.json'
    meta_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2))


def save_index_legacy(
    index_path: Path,
    documents: dict[str, Document],
    chunks: dict[str, Chunk],
    word_index: dict[str, Any],
    trigram_index: Any = None,
) -> None:
    """保存索引到单文件（旧格式，向后兼容）

    参数:
        index_path: 索引文件路径
        documents: 文档字典
        chunks: chunk 字典
        word_index: 词索引
        trigram_index: 三元组索引（可选）
    """
    index_data = {
        'documents': {
            doc_id: {
                'id': doc.id,
                'content': doc.content,
                'source': doc.source,
                'metadata': doc.metadata,
            }
            for doc_id, doc in documents.items()
        },
        'chunks': {
            chunk_id: {
                'id': chunk.id,
                'document_id': chunk.document_id,
                'content': chunk.content,
                'start_pos': chunk.start_pos,
                'end_pos': chunk.end_pos,
                'metadata': chunk.metadata,
            }
            for chunk_id, chunk in chunks.items()
        },
        'inverted_index': {
            word: [h.path for h in hits]
            for word, hits in word_index.items()
        },
    }
    index_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2))

    # 保存 binary trigram index
    if trigram_index is not None:
        binary_dir = index_path.parent / "binary_index"
        writer = BinaryIndexWriter(trigram_index)
        writer.write(binary_dir)


def load_index_v2(
    index_path: Path,
) -> tuple[
    dict[str, Document],
    dict[str, Chunk],
    dict[str, Any],
    dict[str, int],
]:
    """加载新格式索引（目录结构）

    参数:
        index_path: 索引目录路径

    返回:
        (documents, chunks, word_index, chunk_lengths) 元组
    """
    meta_path = index_path / 'index.json'
    index_data = json.loads(meta_path.read_text())

    docs_dir = index_path / 'documents'
    chunks_dir = index_path / 'chunks'

    documents: dict[str, Document] = {}
    for doc_id, ref in index_data['document_refs'].items():
        content_path = docs_dir / f'{doc_id}.json'
        if not content_path.exists():
            continue
        content_data = json.loads(content_path.read_text())
        documents[doc_id] = Document(
            id=ref['id'],
            content=content_data['content'],
            source=ref['source'],
            metadata=ref.get('metadata', {}),
        )

    chunks: dict[str, Chunk] = {}
    for chunk_id, ref in index_data['chunk_refs'].items():
        content_path = chunks_dir / f'{chunk_id}.json'
        if not content_path.exists():
            continue
        content_data = json.loads(content_path.read_text())
        chunks[chunk_id] = Chunk(
            id=ref['id'],
            document_id=ref['document_id'],
            content=content_data['content'],
            start_pos=ref['start_pos'],
            end_pos=ref['end_pos'],
            metadata=ref.get('metadata', {}),
        )

    word_index = index_data.get('inverted_index', {})
    chunk_lengths = {
        chunk_id: len(chunk.content)
        for chunk_id, chunk in chunks.items()
    }

    return documents, chunks, word_index, chunk_lengths


def load_index_legacy(
    index_path: Path,
) -> tuple[
    dict[str, Document],
    dict[str, Chunk],
    dict[str, Any],
    dict[str, int],
    Any,
]:
    """加载旧格式索引（单文件 JSON）

    参数:
        index_path: 索引文件路径

    返回:
        (documents, chunks, word_index, chunk_lengths, trigram_index) 元组
    """
    index_data = json.loads(index_path.read_text())

    documents = {
        doc_id: Document(
            id=doc['id'],
            content=doc['content'],
            source=doc['source'],
            metadata=doc.get('metadata', {}),
        )
        for doc_id, doc in index_data['documents'].items()
    }

    chunks = {
        chunk_id: Chunk(
            id=chunk['id'],
            document_id=chunk['document_id'],
            content=chunk['content'],
            start_pos=chunk['start_pos'],
            end_pos=chunk['end_pos'],
            metadata=chunk.get('metadata', {}),
        )
        for chunk_id, chunk in index_data['chunks'].items()
    }

    word_index = {
        term: set(chunk_ids)
        for term, chunk_ids in index_data['inverted_index'].items()
    }

    chunk_lengths = {
        chunk_id: len(chunk.content)
        for chunk_id, chunk in chunks.items()
    }

    # 加载 binary trigram index
    binary_dir = index_path.parent / "binary_index"
    trigram_index = None
    loaded_tri = BinaryIndexReader.load(binary_dir)
    if loaded_tri:
        trigram_index = loaded_tri

    return documents, chunks, word_index, chunk_lengths, trigram_index
