"""会话压缩算法 — 从 Rust compact.rs 移植

智能压缩长会话，保留最近消息，将旧消息摘要化。
支持增量重压缩（保留之前的摘要上下文）。

核心算法:
1. 估算当前会话 token 数
2. 超过阈值时触发压缩
3. 提取用户请求、待办事项、关键文件、工具名、时间线
4. 生成 XML 格式摘要
5. 增量合并新旧摘要
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

# ==================== 常量 ====================

COMPACT_CONTINUATION_PREAMBLE = (
    'This session is being continued from a previous conversation '
    'that was compacted to reduce token usage.'
)
COMPACT_RECENT_MESSAGES_NOTE = 'Recent messages are preserved verbatim.'
COMPACT_DIRECT_RESUME_INSTRUCTION = 'Continue the conversation from where it left off.'

_DEFAULT_PRESERVE_RECENT = 4
_DEFAULT_MAX_ESTIMATED_TOKENS = 10_000

# 文件扩展名白名单（用于提取关键文件）
_INTERESTING_EXTENSIONS = frozenset({
    '.py', '.rs', '.ts', '.tsx', '.js', '.jsx', '.go', '.java',
    '.json', '.md', '.yaml', '.yml', '.toml', '.cfg', '.ini',
    '.sh', '.bash', '.zsh', '.fish', '.ps1', '.bat', '.cmd',
})

# 待办事项关键词
_PENDING_KEYWORDS = frozenset({
    'todo', 'next', 'pending', 'follow up', 'remaining',
    '待办', '下一步', '待处理', '后续', '未完成',
})


# ==================== 数据模型 ====================

class MessageRole(str, Enum):
    """消息角色"""
    SYSTEM = 'system'
    USER = 'user'
    ASSISTANT = 'assistant'
    TOOL = 'tool'


@dataclass
class ContentBlock:
    """内容块 — 支持文本/工具调用/工具结果"""
    block_type: str  # 'text' | 'tool_use' | 'tool_result'
    text: str = ''
    tool_use_id: str = ''
    tool_name: str = ''
    tool_input: str = ''
    is_error: bool = False

    def to_dict(self) -> dict:
        return {
            'type': self.block_type,
            **({'text': self.text} if self.block_type == 'text' else {}),
            **({'tool_use_id': self.tool_use_id, 'name': self.tool_name, 'input': self.tool_input}
               if self.block_type == 'tool_use' else {}),
            **({'tool_use_id': self.tool_use_id, 'tool_name': self.tool_name,
                'output': self.text, 'is_error': self.is_error}
               if self.block_type == 'tool_result' else {}),
        }


@dataclass
class ConversationMessage:
    """对话消息"""
    role: MessageRole
    blocks: list[ContentBlock] = field(default_factory=list)

    @classmethod
    def user_text(cls, text: str) -> ConversationMessage:
        return cls(role=MessageRole.USER, blocks=[ContentBlock(block_type='text', text=text)])

    @classmethod
    def assistant_text(cls, text: str) -> ConversationMessage:
        return cls(role=MessageRole.ASSISTANT, blocks=[ContentBlock(block_type='text', text=text)])

    @classmethod
    def tool_result(cls, tool_use_id: str, tool_name: str, output: str, is_error: bool = False) -> ConversationMessage:
        return cls(
            role=MessageRole.TOOL,
            blocks=[ContentBlock(
                block_type='tool_result',
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                text=output,
                is_error=is_error,
            )],
        )

    @classmethod
    def system(cls, text: str) -> ConversationMessage:
        return cls(role=MessageRole.SYSTEM, blocks=[ContentBlock(block_type='text', text=text)])

    def first_text(self) -> str:
        """获取第一个非空文本块内容"""
        for block in self.blocks:
            if block.block_type == 'text' and block.text.strip():
                return block.text
        return ''

    def all_text(self) -> str:
        """获取所有文本内容拼接"""
        parts = []
        for block in self.blocks:
            if block.text:
                parts.append(block.text)
            if block.tool_name:
                parts.append(f'[{block.tool_name}]')
        return ' '.join(parts)


@dataclass
class Session:
    """会话数据 — 消息列表"""
    version: int = 1
    messages: list[ConversationMessage] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            'version': self.version,
            'messages': [
                {
                    'role': m.role.value,
                    'blocks': [b.to_dict() for b in m.blocks],
                }
                for m in self.messages
            ],
        }

    @classmethod
    def from_json(cls, data: dict) -> Session:
        messages = []
        for m_data in data.get('messages', []):
            blocks = []
            for b_data in m_data.get('blocks', []):
                bt = b_data.get('type', 'text')
                blocks.append(ContentBlock(
                    block_type=bt,
                    text=b_data.get('text', b_data.get('output', '')),
                    tool_use_id=b_data.get('tool_use_id', ''),
                    tool_name=b_data.get('name', b_data.get('tool_name', '')),
                    tool_input=b_data.get('input', ''),
                    is_error=b_data.get('is_error', False),
                ))
            messages.append(ConversationMessage(
                role=MessageRole(m_data.get('role', 'user')),
                blocks=blocks,
            ))
        return cls(version=data.get('version', 1), messages=messages)


@dataclass
class CompactionConfig:
    """压缩配置"""
    preserve_recent_messages: int = _DEFAULT_PRESERVE_RECENT
    max_estimated_tokens: int = _DEFAULT_MAX_ESTIMATED_TOKENS


@dataclass
class CompactionResult:
    """压缩结果"""
    summary: str = ''
    formatted_summary: str = ''
    compacted_session: Session | None = None
    removed_message_count: int = 0


# ==================== Token 估算 ====================

def estimate_message_tokens(message: ConversationMessage) -> int:
    """估算单条消息的 token 数（轻量级启发式: chars/4+1）"""
    total = 0
    for block in message.blocks:
        text = block.text or ''
        total += len(text) // 4 + 1
        if block.tool_name:
            total += len(block.tool_name) // 4 + 1
        if block.tool_input:
            total += len(block.tool_input) // 4 + 1
    return total


def estimate_session_tokens(session: Session) -> int:
    """估算整个会话的 token 数"""
    return sum(estimate_message_tokens(m) for m in session.messages)


# ==================== XML 工具函数 ====================

def _extract_tag_block(content: str, tag: str) -> str | None:
    """提取 XML 标签内容"""
    pattern = rf'<{tag}>(.*?)</{tag}>'
    match = re.search(pattern, content, re.DOTALL)
    return match.group(1).strip() if match else None


def _strip_tag_block(content: str, tag: str) -> str:
    """移除 XML 标签块"""
    pattern = rf'<{tag}>[\s\S]*?</{tag}>'
    return re.sub(pattern, '', content).strip()


def _truncate(text: str, max_chars: int) -> str:
    """在字符边界截断文本"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + '\u2026'  # …


def _collapse_blank_lines(text: str) -> str:
    """合并连续空行"""
    return re.sub(r'\n{3,}', '\n\n', text).strip()


# ==================== 摘要提取 ====================

def _extract_existing_summary(message: ConversationMessage) -> str | None:
    """从已有的压缩系统消息中提取原始摘要"""
    text = message.first_text()
    if not text or COMPACT_CONTINUATION_PREAMBLE not in text:
        return None

    summary = text
    # 去掉前导 preamble
    summary = summary.replace(COMPACT_CONTINUATION_PREAMBLE, '').strip()
    # 去掉尾部指令
    summary = summary.replace(COMPACT_RECENT_MESSAGES_NOTE, '').strip()
    summary = summary.replace(COMPACT_DIRECT_RESUME_INSTRUCTION, '').strip()

    if not summary.strip():
        return None
    return summary


def _extract_summary_highlights(summary: str) -> list[str]:
    """提取摘要中的高亮部分（不含时间线）"""
    lines = summary.split('\n')
    highlights = []
    in_timeline = False
    for line in lines:
        if '- Key timeline:' in line or '- 关键时间线:' in line:
            in_timeline = True
            continue
        if in_timeline:
            continue
        if line.strip():
            highlights.append(line)
    return highlights


def _extract_summary_timeline(summary: str) -> list[str]:
    """提取摘要中的时间线部分"""
    lines = summary.split('\n')
    timeline = []
    in_timeline = False
    for line in lines:
        if '- Key timeline:' in line or '- 关键时间线:' in line:
            in_timeline = True
            timeline.append(line)
            continue
        if in_timeline and line.strip():
            timeline.append(line)
    return timeline


# ==================== 信息提取 ====================

def _collect_tool_names(messages: list[ConversationMessage]) -> list[str]:
    """收集所有工具名称（去重排序）"""
    names: set[str] = set()
    for msg in messages:
        for block in msg.blocks:
            if block.tool_name:
                names.add(block.tool_name)
    return sorted(names)


def _has_interesting_extension(candidate: str) -> bool:
    """检查文件路径是否有有趣的扩展名"""
    lower = candidate.lower()
    return any(lower.endswith(ext) for ext in _INTERESTING_EXTENSIONS)


def _extract_file_candidates(content: str) -> list[str]:
    """从文本中提取文件路径候选"""
    candidates = []
    for token in re.split(r'[\s,;:|]+', content):
        token = token.strip('`\'"()[]{}<>')
        if ('/' in token or '\\' in token) and _has_interesting_extension(token):
            candidates.append(token)
    return candidates


def _collect_key_files(messages: list[ConversationMessage], limit: int = 8) -> list[str]:
    """提取关键文件路径"""
    seen: set[str] = set()
    files: list[str] = []
    for msg in messages:
        for block in msg.blocks:
            for candidate in _extract_file_candidates(block.text or ''):
                if candidate not in seen:
                    seen.add(candidate)
                    files.append(candidate)
                    if len(files) >= limit:
                        return files
    return files


def _infer_pending_work(messages: list[ConversationMessage], limit: int = 3) -> list[str]:
    """推断待办事项（从最近的消息中反向搜索关键词）"""
    pending: list[str] = []
    for msg in reversed(messages):
        text = msg.all_text().lower()
        for keyword in _PENDING_KEYWORDS:
            if keyword in text:
                snippet = _truncate(msg.first_text(), 160)
                if snippet and snippet not in pending:
                    pending.append(snippet)
                    if len(pending) >= limit:
                        return pending
    return pending


def _infer_current_work(messages: list[ConversationMessage]) -> str:
    """推断当前正在做的工作"""
    for msg in reversed(messages):
        text = msg.first_text()
        if text and text.strip():
            return _truncate(text, 200)
    return ''


def _collect_recent_requests(messages: list[ConversationMessage], limit: int = 3) -> list[str]:
    """收集最近用户请求"""
    requests: list[str] = []
    for msg in reversed(messages):
        if msg.role == MessageRole.USER:
            text = msg.first_text()
            if text and text.strip():
                requests.append(_truncate(text, 160))
                if len(requests) >= limit:
                    break
    requests.reverse()
    return requests


# ==================== 摘要生成 ====================

def _summarize_messages(messages: list[ConversationMessage]) -> str:
    """将一组消息摘要化为 XML 格式"""
    user_count = sum(1 for m in messages if m.role == MessageRole.USER)
    assistant_count = sum(1 for m in messages if m.role == MessageRole.ASSISTANT)
    tool_count = sum(1 for m in messages if m.role == MessageRole.TOOL)

    tool_names = _collect_tool_names(messages)
    recent_requests = _collect_recent_requests(messages)
    pending_work = _infer_pending_work(messages)
    key_files = _collect_key_files(messages)
    current_work = _infer_current_work(messages)

    parts: list[str] = []
    parts.append('<summary>')
    parts.append(f'{len(messages)} earlier messages compacted (user={user_count}, assistant={assistant_count}, tool={tool_count})')

    if tool_names:
        parts.append(f'Tools used: {", ".join(tool_names[:10])}')

    if recent_requests:
        parts.append('Recent user requests:')
        for req in recent_requests:
            parts.append(f'  - {req}')

    if pending_work:
        parts.append('Pending work:')
        for pw in pending_work:
            parts.append(f'  - {pw}')

    if key_files:
        parts.append(f'Key files: {", ".join(key_files[:8])}')

    if current_work:
        parts.append(f'Current work: {current_work}')

    # 完整关键时间线
    parts.append('Key timeline:')
    for msg in messages:
        content = msg.first_text() if msg.role != MessageRole.TOOL else f'[{msg.blocks[0].tool_name if msg.blocks else "tool"}] {msg.first_text()}'
        content = _truncate(content, 160)
        if content.strip():
            parts.append(f'  {msg.role.value}: {content}')

    parts.append('</summary>')
    return '\n'.join(parts)


def _merge_compact_summaries(existing_summary: str, new_summary: str) -> str:
    """增量合并新旧摘要"""
    existing_highlights = _extract_summary_highlights(existing_summary)
    new_highlights = _extract_summary_highlights(new_summary)
    new_timeline = _extract_summary_timeline(new_summary)

    parts: list[str] = []
    parts.append('<summary>')

    if existing_highlights:
        parts.append('Previously compacted context:')
        for line in existing_highlights:
            parts.append(line)

    if new_highlights:
        parts.append('Newly compacted context:')
        for line in new_highlights:
            parts.append(line)

    if new_timeline:
        parts.extend(new_timeline)

    parts.append('</summary>')
    return '\n'.join(parts)


# ==================== 格式化 ====================

def format_compact_summary(summary: str) -> str:
    """清理原始摘要，生成人类可读的格式"""
    cleaned = _strip_tag_block(summary, 'analysis')
    summary_content = _extract_tag_block(cleaned, 'summary')
    if summary_content:
        cleaned = 'Summary:\n' + summary_content

    cleaned = _collapse_blank_lines(cleaned)
    return cleaned.strip()


# ==================== 核心算法 ====================

def should_compact(session: Session, config: CompactionConfig | None = None) -> bool:
    """判断会话是否需要压缩

    跳过已有的压缩摘要消息（第一条系统消息），仅评估实际内容。
    """
    if config is None:
        config = CompactionConfig()

    messages = session.messages
    if len(messages) <= config.preserve_recent_messages + 1:
        return False

    # 检查是否已有压缩摘要，如果有则跳过第一条系统消息
    eval_messages = messages
    if messages and messages[0].role == MessageRole.SYSTEM:
        first_text = messages[0].first_text()
        if first_text and COMPACT_CONTINUATION_PREAMBLE in first_text:
            eval_messages = messages[1:]

    total_tokens = sum(estimate_message_tokens(m) for m in eval_messages)
    return total_tokens > config.max_estimated_tokens


def compact_session(session: Session, config: CompactionConfig | None = None) -> CompactionResult:
    """压缩会话 — 主入口

    1. 检查是否需要压缩
    2. 分离已有摘要、待压缩消息、保留消息
    3. 生成新摘要
    4. 增量合并
    5. 构建压缩后的新会话
    """
    if config is None:
        config = CompactionConfig()

    if not should_compact(session, config):
        return CompactionResult(
            compacted_session=session,
            removed_message_count=0,
        )

    messages = session.messages
    preserve_count = config.preserve_recent_messages

    # 分离已有的压缩摘要（第一条系统消息）
    existing_summary: str | None = None
    start_idx = 0
    if messages and messages[0].role == MessageRole.SYSTEM:
        existing_summary = _extract_existing_summary(messages[0])
        if existing_summary is not None:
            start_idx = 1

    # 计算分割点
    keep_from = max(start_idx, len(messages) - preserve_count)
    removed_messages = messages[start_idx:keep_from]
    preserved_messages = messages[keep_from:]

    if not removed_messages:
        return CompactionResult(
            compacted_session=session,
            removed_message_count=0,
        )

    # 生成新摘要
    new_summary = _summarize_messages(removed_messages)

    # 增量合并
    if existing_summary:
        final_summary = _merge_compact_summaries(existing_summary, new_summary)
    else:
        final_summary = new_summary

    # 构建系统消息
    formatted = format_compact_summary(final_summary)
    parts = [COMPACT_CONTINUATION_PREAMBLE, '', formatted]
    if preserved_messages:
        parts.append('')
        parts.append(COMPACT_RECENT_MESSAGES_NOTE)
    parts.append('')
    parts.append(COMPACT_DIRECT_RESUME_INSTRUCTION)
    continuation_text = '\n'.join(parts)

    # 构建新会话
    new_messages: list[ConversationMessage] = [
        ConversationMessage.system(continuation_text),
    ]
    new_messages.extend(preserved_messages)

    new_session = Session(version=session.version, messages=new_messages)

    return CompactionResult(
        summary=final_summary,
        formatted_summary=formatted,
        compacted_session=new_session,
        removed_message_count=len(removed_messages),
    )
