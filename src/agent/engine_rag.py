"""Agent Engine RAG — 引擎 RAG 上下文增强模块"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger('agent.engine.rag')


async def deep_rag_patch(rag_index: Any, messages: list[dict[str, Any]]) -> str | None:
    """深度 RAG 上下文增强（错误恢复路径）

    当工具调用因"缺少信息"错误失败时，此方法会：
    1. 从错误消息中提取查询意图（关键词）
    2. 使用 RAG 索引检索相关代码片段
    3. 返回格式化的上下文，注入到用户消息中
    """
    if not rag_index:
        return None

    # 1. 提取查询意图
    query_parts: list[str] = []
    for msg in messages:
        error_text = msg.get('error', '') or msg.get('output', '')
        if error_text:
            # 提取关键词：移除常见停用词，保留有意义的标识符
            tokens = re.findall(r'[a-zA-Z_]\w{2,}', error_text)
            ignore = {
                'the', 'and', 'for', 'not', 'but', 'this', 'that', 'with', 'from', 'have',
                'been', 'was', 'were', 'are', 'could', 'would', 'should', 'will', 'your',
                'file', 'line', 'error', 'unknown', 'name', 'module', 'cannot', 'import',
                'attribute', 'type'
            }
            query_parts.extend(t for t in tokens if t.lower() not in ignore)

    if not query_parts:
        return None

    query = ' '.join(query_parts[:6])  # 限制查询长度
    results: list[str] = []

    # 2. 根据索引类型执行搜索
    try:
        from ..rag import LazyIndexer, TextIndexer

        if isinstance(rag_index, (TextIndexer, LazyIndexer)):
            # TextIndexer: BM25 搜索
            search_results = rag_index.search(query, top_k=3)
            for sr in search_results:
                source = getattr(sr.chunk, 'source', '未知')
                results.append(f'[来源: {source}]\n{sr.chunk.content[:500]}')

            # 尝试获取依赖上下文
            if hasattr(rag_index, 'get_imported_by'):
                imported_by = rag_index.get_imported_by(query.split()[0])
                if imported_by:
                    results.append(f'相关引用方: {", ".join(imported_by[:3])}')

        elif hasattr(rag_index, 'get_context'):
            # 通用接口: get_context(query, top_k=3)
            ctx = rag_index.get_context(query, top_k=3)
            if ctx:
                results.append(ctx)

    except Exception as exc:
        logger.warning(f'RAG 补丁执行失败: {exc}')
        return None

    if not results:
        return None

    return f'## 补充参考资料（基于错误: "{query}"）\n\n' + '\n\n---\n\n'.join(results)
