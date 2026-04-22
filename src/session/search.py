"""Session History Search - 会话历史全文检索

从 oh-my-codex-main/src/session-history/search.ts 汲取设计：
- 流式读取JSONL文件，避免大文件内存爆炸
- 支持时间过滤（since: 7d, 24h, timestamp）
- 支持会话/项目过滤
- 上下文片段提取
- 统计信息（searched_files, matched_sessions）

Clawd Code适配：
- 搜索 .clawd/sessions/ 下的 JSON 文件（rollout-*.jsonl 格式）
- 支持中文等UTF-8内容
- 流式处理，内存高效
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class SearchableRecordType(Enum):
    """可搜索记录类型"""
    SESSION_META = "session_meta"
    EVENT_MSG = "event_msg"
    RESPONSE_USER = "response_item:message:user"
    RESPONSE_ASSISTANT = "response_item:message:assistant"
    FUNCTION_CALL = "response_item:function_call"
    RAW = "raw"


@dataclass
class SessionSearchOptions:
    """会话搜索选项"""
    query: str
    limit: int = 10
    session_id: str | None = None
    since: str | None = None  # "7d", "24h", ISO timestamp
    project: str | None = None  # project path or "current" or "all"
    case_sensitive: bool = False
    context: int = 80  # 上下文字符数
    sessions_dir: Path = Path('.clawd/sessions')


@dataclass
class SessionSearchResult:
    """搜索结果"""
    session_id: str
    timestamp: str | None
    cwd: str | None
    record_type: str
    line_number: int
    snippet: str
    file_path: str


@dataclass
class SessionSearchReport:
    """搜索报告"""
    query: str
    searched_files: int
    matched_sessions: int
    results: list[SessionSearchResult]
    has_more: bool = False


# 时间规格解析（借鉴OMX）
DURATION_RE = re.compile(r'^(\d+)([smhdw])$', re.IGNORECASE)


def parse_since_spec(value: str, now: datetime | None = None) -> datetime | None:
    """
    解析since时间规格

    支持格式：
    - "7d", "24h", "30m", "10s"
    - ISO timestamp "2026-04-17T10:30:00"
    """
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    # 持续时间格式
    match = DURATION_RE.match(value)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        multipliers = {
            's': 1,
            'm': 60,
            'h': 3600,
            'd': 86400,
            'w': 604800,
        }
        delta_seconds = amount * multipliers[unit]
        base_time = now or datetime.now()
        return base_time - timedelta(seconds=delta_seconds)

    # ISO时间戳
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(
            f"Invalid --since value '{value}'. "
            "Use formats like 7d, 24h, 10m, or ISO timestamp."
        )


def normalize_project_filter(project: str | None, cwd: Path) -> str | None:
    """
    规范化项目过滤器

    Args:
        project: 用户指定的项目过滤
        cwd: 当前工作目录

    Returns:
        规范化的项目路径或None（表示all）
    """
    if not project:
        return None
    trimmed = project.strip()
    if trimmed == '':
        return None
    if trimmed.lower() == 'current':
        return str(cwd.resolve())
    if trimmed.lower() == 'all':
        return None
    return str(Path(project).resolve())


def safe_parse_json(line: str) -> dict[str, Any] | None:
    """安全解析JSON行"""
    try:
        parsed = json.loads(line)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def extract_session_meta(parsed: dict[str, Any] | None) -> dict[str, Any] | None:
    """提取会话元数据"""
    if not parsed or parsed.get('type') != 'session_meta':
        return None
    payload = parsed.get('payload')
    if not isinstance(payload, dict):
        return None
    return {
        'session_id': payload.get('id'),
        'timestamp': payload.get('timestamp'),
        'cwd': payload.get('cwd'),
    }


def collect_text_fragments(value: Any, fragments: list[str]) -> None:
    """
    递归收集文本片段（用于从嵌套结构中提取搜索文本）

    跳过 base_instructions 和 developer_instructions 字段
    """
    if isinstance(value, str):
        if value.strip():
            fragments.append(value)
        return

    if isinstance(value, list):
        for item in value:
            collect_text_fragments(item, fragments)
        return

    if isinstance(value, dict):
        for key, child in value.items():
            if key in ('base_instructions', 'developer_instructions'):
                continue
            collect_text_fragments(child, fragments)
        return


def extract_searchable_texts(
    parsed: dict[str, Any] | None,
    raw_line: str
) -> list[tuple[str, str]]:
    """
    从记录中提取可搜索文本

    Returns:
        [(text, record_type), ...]
    """
    if not parsed:
        return [(raw_line, SearchableRecordType.RAW.value)]

    top_type = parsed.get('type', 'unknown')
    texts: list[tuple[str, str]] = []

    # 会话元数据
    if top_type == 'session_meta':
        payload = parsed.get('payload', {})
        if isinstance(payload, dict):
            summary_parts = [
                str(payload.get('id', '')),
                str(payload.get('cwd', '')),
                str(payload.get('agent_role', '')),
                str(payload.get('agent_nickname', '')),
            ]
            summary = ' '.join(filter(None, summary_parts)).strip()
            if summary:
                texts.append((summary, SearchableRecordType.SESSION_META.value))
        return texts

    # 事件消息
    if top_type == 'event_msg':
        payload = parsed.get('payload', {})
        fragments: list[str] = []
        collect_text_fragments(payload, fragments)
        text = ' \n '.join(fragments).strip()
        if text:
            texts.append((text, f"{SearchableRecordType.EVENT_MSG.value}:{payload.get('type', 'unknown')}"))
        return texts

    # 响应项（user/assistant消息）
    if top_type == 'response_item':
        payload = parsed.get('payload', {})
        if not isinstance(payload, dict):
            return texts

        payload_type = payload.get('type', 'unknown')

        if payload_type == 'message':
            role = payload.get('role', 'unknown')
            if role in ('user', 'assistant'):
                fragments: list[str] = []
                collect_text_fragments(payload.get('content', {}), fragments)
                text = ' \n '.join(fragments).strip()
                if text:
                    texts.append((text, f"{SearchableRecordType.RESPONSE_USER.value if role == 'user' else SearchableRecordType.RESPONSE_ASSISTANT.value}"))
            return texts

        # 函数调用或输出
        fragments: list[str] = []
        if payload_type == 'function_call':
            name = payload.get('name')
            if name:
                fragments.append(str(name))
            arguments = payload.get('arguments')
            if arguments:
                fragments.append(str(arguments))
        elif payload_type == 'function_call_output':
            output = payload.get('output')
            collect_text_fragments(output, fragments)
        else:
            collect_text_fragments(payload, fragments)

        text = ' \n '.join(fragments).strip()
        if text:
            texts.append((text, f"{SearchableRecordType.FUNCTION_CALL.value}:{payload_type}"))
        return texts

    # 未知类型，返回原始行
    return [(raw_line, top_type)]


def build_snippet(
    text: str,
    query: str,
    context: int,
    case_sensitive: bool
) -> str | None:
    """
    从匹配文本中提取片段（带上下文）

    Args:
        text: 完整文本
        query: 搜索查询
        context: 上下文字符数（每侧）

    Returns:
        片段字符串，未匹配则返回None
    """
    if not text:
        return None

    haystack = text if case_sensitive else text.lower()
    needle = query if case_sensitive else query.lower()

    index = haystack.find(needle)
    if index < 0:
        return None

    start = max(0, index - context)
    end = min(len(text), index + len(query) + context)

    prefix = '…' if start > 0 else ''
    suffix = '…' if end < len(text) else ''

    snippet = text[start:end].strip()
    if not snippet:
        return None

    # 规范化空白字符
    snippet = re.sub(r'\s+', ' ', snippet)

    return f"{prefix}{snippet}{suffix}"


def matches_filter(value: str | None, filter: str | None, case_sensitive: bool) -> bool:
    """
    检查值是否匹配过滤器

    Args:
        value: 要检查的值
        filter: 过滤器（None表示匹配所有）
        case_sensitive: 是否大小写敏感
    """
    if filter is None:
        return True
    if value is None:
        return False

    if case_sensitive:
        return filter in value
    return filter.lower() in value.lower()


async def search_sessions_file(
    file_path: Path,
    options: SessionSearchOptions,
    since_cutoff: datetime | None,
    project_filter: str | None,
    cwd: Path,
) -> list[SessionSearchResult]:
    """
    搜索单个会话文件

    Args:
        file_path: 会话文件路径
        options: 搜索选项
        since_cutoff: 时间过滤截止点（早于此时间的会话被跳过）
        project_filter: 项目路径过滤
        cwd: 当前工作目录

    Returns:
        搜索结果列表
    """

    results: list[SessionSearchResult] = []
    meta: dict[str, Any] | None = None
    line_number = 0
    skip_file = False

    try:
        # 流式读取文件
        with open(file_path, encoding='utf-8') as f:
            for raw_line in f:
                line_number += 1
                parsed = safe_parse_json(raw_line)

                # 第一行提取会话元数据
                if line_number == 1:
                    meta = extract_session_meta(parsed)
                    fallback_session_id = file_path.stem
                    if not meta:
                        meta = {
                            'session_id': fallback_session_id,
                            'timestamp': None,
                            'cwd': None,
                        }

                    # 应用过滤器
                    session_timestamp = None
                    if meta.get('timestamp'):
                        try:
                            session_timestamp = datetime.fromisoformat(
                                meta['timestamp'].replace('Z', '+00:00')
                            )
                        except ValueError:
                            pass

                    if (since_cutoff and session_timestamp and
                            session_timestamp < since_cutoff):
                        skip_file = True
                        break

                    if not matches_filter(meta.get('session_id'), options.session_id, options.case_sensitive):
                        skip_file = True
                        break

                    if not matches_filter(meta.get('cwd'), project_filter, options.case_sensitive):
                        skip_file = True
                        break

                # 搜索可搜索文本
                for text, record_type in extract_searchable_texts(parsed, raw_line):
                    snippet = build_snippet(
                        text,
                        options.query,
                        options.context,
                        options.case_sensitive
                    )
                    if not snippet or not meta:
                        continue

                    results.append(SessionSearchResult(
                        session_id=meta['session_id'],
                        timestamp=meta.get('timestamp'),
                        cwd=meta.get('cwd'),
                        record_type=record_type,
                        line_number=line_number,
                        snippet=snippet,
                        file_path=str(file_path),
                    ))

                    if len(results) >= options.limit:
                        return results
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
        # 文件损坏或编码问题，跳过
        pass

    return [] if skip_file else results


async def search_session_history(
    query: str,
    sessions_dir: Path = Path('.clawd/sessions'),
    limit: int = 10,
    session_id: str | None = None,
    since: str | None = None,
    project: str | None = None,
    case_sensitive: bool = False,
    context: int = 80,
) -> SessionSearchReport:
    """
    搜索会话历史（流式、内存高效）

    Args:
        query: 搜索查询（必需，非空）
        sessions_dir: 会话存储目录
        limit: 最大结果数（默认10，上限100）
        session_id: 过滤特定会话ID
        since: 时间过滤（如 "7d", "24h", ISO时间戳）
        project: 项目过滤（"current", "all", 或具体路径）
        case_sensitive: 是否大小写敏感
        context: 上下文字符数

    Returns:
        搜索报告，包含统计和结果
    """
    from datetime import datetime

    query = query.strip()
    if not query:
        raise ValueError("Search query must not be empty")

    # 限制参数
    limit = max(1, min(limit, 100))
    context = max(0, min(context, 400))

    cwd = Path.cwd()
    sessions_dir = sessions_dir.resolve()

    # 解析时间过滤
    since_cutoff: datetime | None = None
    if since:
        since_cutoff = parse_since_spec(since, datetime.now())

    # 规范化项目过滤
    project_filter = normalize_project_filter(project, cwd)

    # 收集会话文件（按修改时间倒序）
    if not sessions_dir.exists():
        return SessionSearchReport(
            query=query,
            searched_files=0,
            matched_sessions=0,
            results=[],
        )

    # 假设文件命名模式：rollout-*.jsonl 或 *.json
    # 优先查找 rollout-*.jsonl（OMX兼容），其次 *.json（Clawd Code当前格式）
    jsonl_files = list(sessions_dir.glob('rollout-*.jsonl'))
    json_files = list(sessions_dir.glob('*.json')) if not jsonl_files else []

    # 排序：最新修改的文件在前
    all_files = sorted(
        jsonl_files + json_files,
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True
    )

    results: list[SessionSearchResult] = []
    searched_files = 0
    matched_sessions: set[str] = set()

    # 并发搜索多个文件（但限制并发数，避免IO压力）
    import asyncio

    semaphore = asyncio.Semaphore(5)  # 最大5个并发文件读取

    async def search_with_limit(file_path: Path) -> list[SessionSearchResult]:
        async with semaphore:
            searched_files += 1
            return await search_sessions_file(
                file_path, options, since_cutoff, project_filter, cwd
            )

    # 并发执行搜索
    tasks = [search_with_limit(fp) for fp in all_files[:limit * 2]]  # 多查一些文件
    file_results = await asyncio.gather(*tasks, return_exceptions=[])

    for result_list in file_results:
        if isinstance(result_list, list):
            for res in result_list:
                results.append(res)
                matched_sessions.add(res.session_id)
                if len(results) >= limit:
                    break
        if len(results) >= limit:
            break

    # 截断到限制
    results = results[:limit]

    return SessionSearchReport(
        query=query,
        searched_files=searched_files,
        matched_sessions=len(matched_sessions),
        results=results,
        has_more=len(results) >= limit,
    )


def format_search_result(result: SessionSearchResult, width: int = 80) -> str:
    """格式化单个搜索结果（人类可读）"""
    timestamp_str = ""
    if result.timestamp:
        try:
            dt = datetime.fromisoformat(result.timestamp.replace('Z', '+00:00'))
            timestamp_str = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            timestamp_str = result.timestamp[:19]

    header = f"[{result.session_id}]"
    if timestamp_str:
        header += f" {timestamp_str}"
    if result.record_type != 'raw':
        header += f" ({result.record_type})"

    # 截断过长的header
    if len(header) > width - 5:
        header = header[:width - 8] + "..."

    line_info = f"Line {result.line_number}"
    if result.cwd:
        # 显示相对路径（如果可能）
        try:
            cwd_rel = Path(result.cwd).relative_to(Path.cwd())
            line_info += f" in {cwd_rel}"
        except ValueError:
            line_info += f" in {Path(result.cwd).name}"

    formatted = f"{header}\n"
    formatted += f"  {line_info}\n"
    formatted += f"  {result.snippet}\n"

    return formatted


# 导出
__all__ = [
    'SearchableRecordType',
    'SessionSearchOptions',
    'SessionSearchReport',
    'SessionSearchResult',
    'format_search_result',
    'parse_since_spec',
    'search_session_history',
]
