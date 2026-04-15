"""索引器工具函数 - 分块、分词、ID 生成

从 text_indexer.py 拆分，负责：
- 文档分块 (_chunk_document)
- 文本分词 (_tokenize)
- ID 生成 (_generate_id)
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path

from .models import Chunk

# [性能] 全局文件读取缓存，避免 RAG 组件间重复读取同一文件
@lru_cache(maxsize=1024)
def read_file_cached(file_path: str, max_size: int = 1024 * 1024) -> str:
    """带缓存的文件读取"""
    p = Path(file_path)
    if not p.exists():
        return ""
    try:
        stat = p.stat()
        if stat.st_size > max_size:
             # 只读取部分内容
             with open(p, 'r', encoding='utf-8', errors='replace') as f:
                 return f.read(max_size)
        return p.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return ""

def invalidate_file_cache(file_path: str | None = None):
    """清除文件缓存"""
    if file_path is None:
        read_file_cached.cache_clear()
    else:
        # lru_cache 不支持直接删除单个 key，但在 3.9+ 可以通过 cache_clear 或包装器实现
        # 简单起见，如果单个文件变动，在 update_file 层面会覆盖，LRU 会自动淘汰
        pass

# 模块级停用词缓存（所有实例共享，只创建一次）
_STOP_WORDS: frozenset[str] | None = None


def _get_stop_words_cached() -> frozenset[str]:
    """获取模块级缓存的停用词集合"""
    global _STOP_WORDS
    if _STOP_WORDS is None:
        _STOP_WORDS = frozenset({
            # 英文停用词
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'shall',
            'should', 'may', 'might', 'must', 'can', 'could',
            'of', 'to', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'into',
            'and', 'or', 'not', 'no', 'but', 'if', 'then', 'else', 'so', 'yet',
            'this', 'that', 'these', 'those', 'it', 'its', 'they', 'them',
            'he', 'she', 'we', 'you', 'i', 'me', 'him', 'her', 'us',
            'what', 'which', 'who', 'whom', 'whose', 'where', 'when', 'why', 'how',
            'all', 'each', 'every', 'both', 'few', 'many', 'much', 'some', 'any',
            'about', 'above', 'after', 'again', 'against', 'between', 'through',
            'during', 'before', 'while', 'only', 'own', 'same', 'than', 'too',
            'very', 'just', 'also', 'now', 'here', 'there',  # Python 关键字
            'def', 'class', 'return', 'import', 'as', 'lambda',
            'pass', 'break', 'continue', 'yield', 'raise', 'try', 'except',
            'finally', 'assert', 'del', 'global', 'nonlocal',
            # 中文停用词
            '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都',
            '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你',
            '会', '着', '没有', '看', '好', '自己', '这', '那', '么', '吗',
            '呢', '吧', '啊', '哦', '嗯', '哎', '呀', '哇', '哈', '嘿',
        })
    return _STOP_WORDS


def chunk_document(
    content: str,
    doc_id: str,
    doc_source: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[Chunk]:
    """将文档分块

    参数:
        content: 文档内容
        doc_id: 文档 ID
        doc_source: 文档源路径
        chunk_size: 分块大小
        chunk_overlap: 分块重叠

    返回:
        Chunk 列表
    """
    chunks = []
    start = 0

    while start < len(content):
        end = start + chunk_size
        chunk_content = content[start:end]

        if end < len(content):
            for sep in ['\n\n', '\n', '. ', '。', '！', '？']:
                last_sep = chunk_content.rfind(sep)
                if last_sep > chunk_size // 2:
                    end = start + last_sep + len(sep)
                    chunk_content = content[start:end]
                    break

        chunk_id = generate_id(f'{doc_id}:{start}')
        chunk = Chunk(
            id=chunk_id,
            document_id=doc_id,
            content=chunk_content,
            start_pos=start,
            end_pos=end,
            metadata={'source': doc_source},
        )
        chunks.append(chunk)
        start = end - chunk_overlap

    return chunks


def tokenize(text: str) -> list[str]:
    """文本分词

    增强功能 (v0.19.0):
    - 改��的中文分词支持（提取连续中文字符串）
    - 更完善的停用词表
    - 支持中英文混合文本

    策略:
    1. 提取英文单词和数字序列（长度 >= 2）
    2. 提取连续中文字符串（长度 >= 2）
    3. 过滤停用词
    """
    en_tokens = re.findall(r'[a-zA-Z0-9_]{2,}', text.lower())
    zh_tokens = re.findall(r'[\u4e00-\u9fff]{2,}', text)
    tokens = en_tokens + zh_tokens
    stop_words = _get_stop_words_cached()
    return [t for t in tokens if t not in stop_words]


def generate_id(text: str) -> str:
    """生成唯一 ID"""
    return hashlib.md5(text.encode()).hexdigest()[:12]
