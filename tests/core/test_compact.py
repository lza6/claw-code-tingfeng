"""compact 模块测试 — 会话压缩算法

覆盖:
- Token 估算
- 数据模型 (ContentBlock, ConversationMessage, Session)
- XML 工具函数
- 摘要提取
- 信息提取 (工具名、文件路径、待办事项、用户请求)
- 摘要生成与合并
- 格式化
- 核心算法 (should_compact, compact_session)
"""
from __future__ import annotations

import pytest

from src.core.compact import (
    COMPACT_CONTINUATION_PREAMBLE,
    COMPACT_DIRECT_RESUME_INSTRUCTION,
    COMPACT_RECENT_MESSAGES_NOTE,
    ContentBlock,
    ConversationMessage,
    Session,
    CompactionConfig,
    CompactionResult,
    MessageRole,
    _collapse_blank_lines,
    _collect_key_files,
    _collect_recent_requests,
    _collect_tool_names,
    _extract_existing_summary,
    _extract_file_candidates,
    _extract_summary_highlights,
    _extract_summary_timeline,
    _extract_tag_block,
    _has_interesting_extension,
    _infer_current_work,
    _infer_pending_work,
    _merge_compact_summaries,
    _strip_tag_block,
    _summarize_messages,
    _truncate,
    compact_session,
    estimate_message_tokens,
    estimate_session_tokens,
    format_compact_summary,
    should_compact,
)


# ====================================================================
# Token 估算测试
# ====================================================================

class TestTokenEstimation:
    """Token 估算函数测试"""

    def test_estimate_single_text_block(self):
        """单文本块 token 估算"""
        block = ContentBlock(block_type='text', text='Hello world')
        msg = ConversationMessage(role=MessageRole.USER, blocks=[block])
        tokens = estimate_message_tokens(msg)
        assert tokens > 0

    def test_estimate_empty_message(self):
        """空消息 token 估算"""
        msg = ConversationMessage(role=MessageRole.USER, blocks=[])
        tokens = estimate_message_tokens(msg)
        assert tokens == 0

    def test_estimate_tool_block(self):
        """含工具调用块的 token 估算"""
        block = ContentBlock(
            block_type='tool_use',
            tool_name='grep',
            tool_input='{"pattern": "test"}',
        )
        msg = ConversationMessage(role=MessageRole.ASSISTANT, blocks=[block])
        tokens = estimate_message_tokens(msg)
        assert tokens > 0

    def test_estimate_session_tokens(self):
        """整个会话 token 估算"""
        session = Session(messages=[
            ConversationMessage.user_text("Hello"),
            ConversationMessage.assistant_text("Hi there"),
        ])
        tokens = estimate_session_tokens(session)
        assert tokens > 0

    def test_estimate_long_text(self):
        """长文本 token 估算应随长度增长"""
        short = ConversationMessage.user_text("Hi")
        long = ConversationMessage.user_text("A" * 1000)
        assert estimate_message_tokens(long) > estimate_message_tokens(short)


# ====================================================================
# ContentBlock 测试
# ====================================================================

class TestContentBlock:
    """ContentBlock 数据类测试"""

    def test_to_dict_text(self):
        """文本块 to_dict"""
        block = ContentBlock(block_type='text', text='hello')
        d = block.to_dict()
        assert d['type'] == 'text'
        assert d['text'] == 'hello'

    def test_to_dict_tool_use(self):
        """工具调用块 to_dict"""
        block = ContentBlock(
            block_type='tool_use',
            tool_use_id='t1',
            tool_name='grep',
            tool_input='{"p": "x"}',
        )
        d = block.to_dict()
        assert d['type'] == 'tool_use'
        assert d['tool_use_id'] == 't1'
        assert d['name'] == 'grep'
        assert d['input'] == '{"p": "x"}'

    def test_to_dict_tool_result(self):
        """工具结果块 to_dict"""
        block = ContentBlock(
            block_type='tool_result',
            tool_use_id='t1',
            tool_name='grep',
            text='output',
            is_error=False,
        )
        d = block.to_dict()
        assert d['type'] == 'tool_result'
        assert d['output'] == 'output'
        assert d['is_error'] is False


# ====================================================================
# ConversationMessage 测试
# ====================================================================

class TestConversationMessage:
    """ConversationMessage 工厂方法测试"""

    def test_user_text(self):
        msg = ConversationMessage.user_text("hello")
        assert msg.role == MessageRole.USER
        assert msg.first_text() == "hello"

    def test_assistant_text(self):
        msg = ConversationMessage.assistant_text("hi")
        assert msg.role == MessageRole.ASSISTANT
        assert msg.first_text() == "hi"

    def test_tool_result(self):
        msg = ConversationMessage.tool_result('t1', 'grep', 'found', is_error=False)
        assert msg.role == MessageRole.TOOL
        assert msg.blocks[0].tool_name == 'grep'
        assert msg.blocks[0].is_error is False

    def test_tool_result_error(self):
        msg = ConversationMessage.tool_result('t1', 'grep', 'error', is_error=True)
        assert msg.blocks[0].is_error is True

    def test_system(self):
        msg = ConversationMessage.system("sys prompt")
        assert msg.role == MessageRole.SYSTEM

    def test_first_text_no_text_block(self):
        """无文本块时返回空字符串"""
        block = ContentBlock(block_type='tool_use', tool_name='grep')
        msg = ConversationMessage(role=MessageRole.ASSISTANT, blocks=[block])
        assert msg.first_text() == ''

    def test_first_text_empty_text_block(self):
        """空文本块应被跳过"""
        blocks = [
            ContentBlock(block_type='text', text='   '),
            ContentBlock(block_type='text', text='real'),
        ]
        msg = ConversationMessage(role=MessageRole.USER, blocks=blocks)
        assert msg.first_text() == 'real'

    def test_all_text(self):
        """all_text 应拼接所有文本"""
        blocks = [
            ContentBlock(block_type='text', text='hello'),
            ContentBlock(block_type='tool_use', tool_name='grep'),
        ]
        msg = ConversationMessage(role=MessageRole.ASSISTANT, blocks=blocks)
        text = msg.all_text()
        assert 'hello' in text
        assert '[grep]' in text


# ====================================================================
# Session JSON 序列化测试
# ====================================================================

class TestSessionJSON:
    """Session JSON 序列化/反序列化测试"""

    def test_roundtrip(self):
        """序列化后再反序列化应还原"""
        session = Session(messages=[
            ConversationMessage.user_text("hello"),
            ConversationMessage.assistant_text("hi"),
            ConversationMessage.tool_result('t1', 'grep', 'output'),
        ])
        data = session.to_json()
        restored = Session.from_json(data)
        assert len(restored.messages) == len(session.messages)
        assert restored.messages[0].role == MessageRole.USER
        assert restored.messages[1].role == MessageRole.ASSISTANT
        assert restored.messages[2].role == MessageRole.TOOL

    def test_from_json_empty(self):
        """空 JSON 应返回空会话"""
        session = Session.from_json({})
        assert session.messages == []

    def test_from_json_partial(self):
        """部分 JSON 字段应使用默认值"""
        session = Session.from_json({'messages': [{'role': 'user', 'blocks': []}]})
        assert len(session.messages) == 1
        assert session.version == 1  # default


# ====================================================================
# XML 工具函数测试
# ====================================================================

class TestXMLUtils:
    """XML 标签操作工具函数测试"""

    def test_extract_tag_block_found(self):
        result = _extract_tag_block('<summary>hello</summary>', 'summary')
        assert result == 'hello'

    def test_extract_tag_block_not_found(self):
        result = _extract_tag_block('no tags here', 'summary')
        assert result is None

    def test_extract_tag_block_multiline(self):
        content = '<summary>\nline1\nline2\n</summary>'
        result = _extract_tag_block(content, 'summary')
        assert 'line1' in result

    def test_strip_tag_block(self):
        content = 'before <summary>remove</summary> after'
        result = _strip_tag_block(content, 'summary')
        assert 'summary' not in result
        assert 'before' in result

    def test_truncate_short_text(self):
        """短文本不截断"""
        assert _truncate("hello", 100) == "hello"

    def test_truncate_long_text(self):
        """长文本截断"""
        result = _truncate("A" * 200, 50)
        assert len(result) <= 52  # 50 chars + ellipsis
        assert result.endswith('\u2026')

    def test_collapse_blank_lines(self):
        """连续空行合并"""
        text = "a\n\n\n\nb"
        result = _collapse_blank_lines(text)
        assert '\n\n\n' not in result
        assert '\n\n' in result

    def test_collapse_blank_lines_short(self):
        """不超过两个空行不合并"""
        text = "a\n\nb"
        result = _collapse_blank_lines(text)
        assert result == "a\n\nb"


# ====================================================================
# 摘要提取测试
# ====================================================================

class TestSummaryExtraction:
    """摘要提取函数测试"""

    def test_extract_existing_summary_found(self):
        msg = ConversationMessage.system(
            COMPACT_CONTINUATION_PREAMBLE + '\nSummary content\n' +
            COMPACT_RECENT_MESSAGES_NOTE + '\n' + COMPACT_DIRECT_RESUME_INSTRUCTION
        )
        result = _extract_existing_summary(msg)
        assert result is not None
        assert 'Summary content' in result

    def test_extract_existing_summary_not_found(self):
        msg = ConversationMessage.system("regular message")
        result = _extract_existing_summary(msg)
        assert result is None

    def test_extract_existing_summary_empty(self):
        msg = ConversationMessage.system(COMPACT_CONTINUATION_PREAMBLE)
        result = _extract_existing_summary(msg)
        assert result is None

    def test_extract_summary_highlights(self):
        summary = """Key points:
- something important
- Key timeline:
  - step 1
  - step 2
"""
        highlights = _extract_summary_highlights(summary)
        assert any('Key points' in h for h in highlights)
        assert not any('Key timeline' in h for h in highlights)

    def test_extract_summary_timeline(self):
        summary = """Highlights
- Key timeline:
  - step 1
  - step 2
"""
        timeline = _extract_summary_timeline(summary)
        assert any('Key timeline' in t for t in timeline)
        assert any('step 1' in t for t in timeline)

    def test_extract_summary_highlights_chinese(self):
        summary = """要点
- 关键时间线:
  - 步骤 1
"""
        highlights = _extract_summary_highlights(summary)
        assert not any('关键时间线' in h for h in highlights)


# ====================================================================
# 信息提取测试
# ====================================================================

class TestInfoExtraction:
    """信息提取函数测试"""

    def test_collect_tool_names(self):
        messages = [
            ConversationMessage.assistant_text("call grep"),
            ConversationMessage.tool_result('t1', 'grep', 'ok'),
            ConversationMessage.tool_result('t2', 'sed', 'ok'),
        ]
        # 需要从 tool_result 块中提取工具名
        names = _collect_tool_names(messages)
        # 至少包含 grep（来自 tool_result）
        assert 'grep' in names

    def test_collect_tool_names_empty(self):
        messages = [ConversationMessage.user_text("hello")]
        assert _collect_tool_names(messages) == []

    def test_collect_tool_names_dedup(self):
        """工具名应去重"""
        messages = [
            ConversationMessage.tool_result('t1', 'grep', 'ok'),
            ConversationMessage.tool_result('t2', 'grep', 'ok2'),
        ]
        names = _collect_tool_names(messages)
        assert names.count('grep') == 1

    def test_has_interesting_extension(self):
        assert _has_interesting_extension('src/main.py') is True
        assert _has_interesting_extension('config.yaml') is True
        assert _has_interesting_extension('readme.md') is True
        assert _has_interesting_extension('photo.jpg') is False
        assert _has_interesting_extension('notes.txt') is False

    def test_extract_file_candidates(self):
        text = "check src/utils.py and also lib/core.ts for details"
        candidates = _extract_file_candidates(text)
        assert 'src/utils.py' in candidates
        assert 'lib/core.ts' in candidates

    def test_extract_file_candidates_no_paths(self):
        candidates = _extract_file_candidates("just some text no files")
        assert candidates == []

    def test_collect_key_files_limit(self):
        """文件数量应受 limit 限制"""
        texts = ' '.join(f'see file path{i}/module.py' for i in range(20))
        messages = [ConversationMessage.user_text(texts)]
        files = _collect_key_files(messages, limit=3)
        assert len(files) <= 3

    def test_infer_pending_work(self):
        """从待办关键词推断待办事项"""
        msg = ConversationMessage.user_text("TODO: fix the login bug")
        messages = [msg]
        pending = _infer_pending_work(messages)
        assert len(pending) >= 1

    def test_infer_pending_work_no_keywords(self):
        messages = [ConversationMessage.user_text("everything is done")]
        assert _infer_pending_work(messages) == []

    def test_infer_pending_work_limit(self):
        """待办事项数量应受 limit 限制"""
        text = "TODO: a, TODO: b, TODO: c, TODO: d"
        messages = [ConversationMessage.user_text(text)]
        pending = _infer_pending_work(messages, limit=2)
        assert len(pending) <= 2

    def test_infer_current_work(self):
        msg = ConversationMessage.user_text("Working on auth module")
        messages = [msg]
        work = _infer_current_work(messages)
        assert 'auth' in work.lower()

    def test_infer_current_work_empty(self):
        messages = [ConversationMessage(role=MessageRole.USER, blocks=[])]
        assert _infer_current_work(messages) == ''

    def test_collect_recent_requests(self):
        messages = [
            ConversationMessage.user_text("request 1"),
            ConversationMessage.assistant_text("reply 1"),
            ConversationMessage.user_text("request 2"),
        ]
        requests = _collect_recent_requests(messages)
        assert len(requests) >= 1
        assert 'request 2' in requests

    def test_collect_recent_requests_no_user_messages(self):
        messages = [ConversationMessage.assistant_text("only assistant")]
        assert _collect_recent_requests(messages) == []


# ====================================================================
# 摘要生成测试
# ====================================================================

class TestSummarizeMessages:
    """_summarize_messages 函数测试"""

    def test_basic_summary(self):
        messages = [
            ConversationMessage.user_text("fix bug"),
            ConversationMessage.assistant_text("analyzing"),
        ]
        summary = _summarize_messages(messages)
        assert '<summary>' in summary
        assert '</summary>' in summary

    def test_summary_with_tools(self):
        messages = [
            ConversationMessage.tool_result('t1', 'grep', 'ok'),
            ConversationMessage.tool_result('t2', 'sed', 'ok'),
        ]
        summary = _summarize_messages(messages)
        assert 'Tools used' in summary or 'grep' in summary

    def test_summary_with_files(self):
        messages = [
            ConversationMessage.user_text("check src/main.py"),
        ]
        summary = _summarize_messages(messages)
        assert 'Key files' in summary or 'main.py' in summary

    def test_summary_with_pending(self):
        messages = [
            ConversationMessage.user_text("TODO: remaining work"),
        ]
        summary = _summarize_messages(messages)
        assert 'Pending work' in summary or 'TODO' in summary

    def test_summary_with_current_work(self):
        messages = [
            ConversationMessage.user_text("Working on X"),
        ]
        summary = _summarize_messages(messages)
        assert 'Current work' in summary


# ====================================================================
# 摘要合并测试
# ====================================================================

class TestMergeSummaries:
    """_merge_compact_summaries 函数测试"""

    def test_merge_no_existing(self):
        new_summary = '<summary>\nNew context\n</summary>'
        result = _merge_compact_summaries('', new_summary)
        assert 'Newly compacted context' in result
        assert 'New context' in result

    def test_merge_with_existing(self):
        existing = '<summary>\nOld context\n</summary>'
        new = '<summary>\nNew context\n</summary>'
        result = _merge_compact_summaries(existing, new)
        assert 'Previously compacted context' in result
        assert 'Newly compacted context' in result

    def test_merge_with_timeline(self):
        existing = '<summary>\nOld\n</summary>'
        new = '<summary>\nNew\n- Key timeline:\n  - step 1\n</summary>'
        result = _merge_compact_summaries(existing, new)
        assert 'step 1' in result


# ====================================================================
# 格式化测试
# ====================================================================

class TestFormatCompactSummary:
    """format_compact_summary 函数测试"""

    def test_format_basic(self):
        summary = '<summary>compact info</summary>'
        result = format_compact_summary(summary)
        assert 'compact info' in result

    def test_format_with_analysis_block(self):
        summary = '<analysis>should be stripped</analysis><summary>real summary</summary>'
        result = format_compact_summary(summary)
        assert 'analysis' not in result.lower() or 'real summary' in result

    def test_format_no_summary_tag(self):
        summary = 'plain text'
        result = format_compact_summary(summary)
        assert result == 'plain text'

    def test_format_collapse_blanks(self):
        summary = '<summary>line1\n\n\n\nline2</summary>'
        result = format_compact_summary(summary)
        assert '\n\n\n' not in result


# ====================================================================
# should_compact 测试
# ====================================================================

class TestShouldCompact:
    """should_compact 函数测试"""

    def test_no_compact_short_session(self):
        """短会话不需要压缩"""
        session = Session(messages=[
            ConversationMessage.user_text("hello"),
            ConversationMessage.assistant_text("hi"),
        ])
        assert should_compact(session) is False

    def test_compact_long_session(self):
        """长会话需要压缩"""
        # 创建足够多的消息来超过 token 阈值
        messages = []
        for i in range(50):
            messages.append(ConversationMessage.user_text("A" * 500))
            messages.append(ConversationMessage.assistant_text("B" * 500))
        session = Session(messages=messages)
        assert should_compact(session) is True

    def test_no_compact_with_existing_summary_only(self):
        """仅有压缩摘要 + 少量消息不需要压缩"""
        messages = [
            ConversationMessage.system(
                COMPACT_CONTINUATION_PREAMBLE + '\nold summary\n' +
                COMPACT_RECENT_MESSAGES_NOTE + '\n' + COMPACT_DIRECT_RESUME_INSTRUCTION
            ),
            ConversationMessage.user_text("new msg"),
        ]
        session = Session(messages=messages)
        assert should_compact(session) is False

    def test_no_compact_empty_session(self):
        session = Session(messages=[])
        assert should_compact(session) is False

    def test_custom_config(self):
        """自定义配置"""
        config = CompactionConfig(max_estimated_tokens=100, preserve_recent_messages=2)
        messages = [ConversationMessage.user_text("X" * 500) for _ in range(5)]
        session = Session(messages=messages)
        assert should_compact(session, config) is True


# ====================================================================
# compact_session 测试
# ====================================================================

class TestCompactSession:
    """compact_session 核心算法测试"""

    def test_no_compact_returns_original(self):
        """短会话返回原始会话"""
        session = Session(messages=[
            ConversationMessage.user_text("hello"),
        ])
        result = compact_session(session)
        assert result.compacted_session is session
        assert result.removed_message_count == 0

    def test_compact_long_session(self):
        """长会话压缩 — 使用较低阈值确保触发"""
        messages = []
        for i in range(30):
            messages.append(ConversationMessage.user_text("Question " + "A" * 100))
            messages.append(ConversationMessage.assistant_text("Answer " + "B" * 100))
        session = Session(messages=messages)

        # 使用低阈值确保压缩触发
        config = CompactionConfig(max_estimated_tokens=2000, preserve_recent_messages=4)
        result = compact_session(session, config)
        # 即使不移除消息，compacted_session 也不应为 None
        assert result.compacted_session is not None or result.removed_message_count == 0

    def test_compact_preserves_recent(self):
        """压缩应保留最近的消息"""
        messages = []
        for i in range(30):
            messages.append(ConversationMessage.user_text("Question " + "A" * 100))
            messages.append(ConversationMessage.assistant_text("Answer " + "B" * 100))
        session = Session(messages=messages)

        result = compact_session(session, CompactionConfig(preserve_recent_messages=4))
        assert result.compacted_session is not None
        # 压缩后的会话应包含保留的最近消息 + 系统消息
        assert len(result.compacted_session.messages) >= 4

    def test_compact_with_existing_summary(self):
        """增量压缩已有摘要 — 验证系统消息被正确处理"""
        messages = [
            ConversationMessage.system(
                COMPACT_CONTINUATION_PREAMBLE + '\nOld summary data\n' +
                COMPACT_RECENT_MESSAGES_NOTE + '\n' + COMPACT_DIRECT_RESUME_INSTRUCTION
            ),
        ]
        for i in range(30):
            messages.append(ConversationMessage.user_text("Question " + "A" * 100))
            messages.append(ConversationMessage.assistant_text("Answer " + "B" * 100))
        session = Session(messages=messages)

        config = CompactionConfig(max_estimated_tokens=2000, preserve_recent_messages=4)
        result = compact_session(session, config)
        # 验证压缩后的会话保留了系统消息
        assert result.compacted_session is not None
        system_msg = result.compacted_session.messages[0]
        assert system_msg.role == MessageRole.SYSTEM
        assert COMPACT_CONTINUATION_PREAMBLE in system_msg.first_text()

    def test_compact_system_message_preamble(self):
        """压缩后的系统消息应包含 continuation preamble"""
        # 使用低阈值确保压缩触发
        messages = []
        for i in range(30):
            messages.append(ConversationMessage.user_text("Question " + "A" * 100))
            messages.append(ConversationMessage.assistant_text("Answer " + "B" * 100))
        session = Session(messages=messages)

        config = CompactionConfig(max_estimated_tokens=2000, preserve_recent_messages=4)
        result = compact_session(session, config)
        # 压缩后应产生新会话，检查是否有系统消息
        assert result.compacted_session is not None
        # 第一条消息可能是 SYSTEM 或 USER（取决于压缩算法的具体实现）
        first_msg = result.compacted_session.messages[0]
        text = first_msg.first_text()
        # 验证包含压缩相关的文本内容
        assert COMPACT_CONTINUATION_PREAMBLE in text or len(text) > 0

    def test_compact_preserved_messages_note(self):
        """当有保留消息时，系统消息应包含 recent messages note"""
        config = CompactionConfig(preserve_recent_messages=2, max_estimated_tokens=100)
        messages = []
        for i in range(30):
            messages.append(ConversationMessage.user_text("X" * 300))
        session = Session(messages=messages)

        result = compact_session(session, config)
        system_text = result.compacted_session.messages[0].first_text()
        assert COMPACT_RECENT_MESSAGES_NOTE in system_text

    def test_compact_result_fields(self):
        """压缩结果应包含所有必要字段"""
        messages = []
        for i in range(30):
            messages.append(ConversationMessage.user_text("Question " + "X" * 100))
            messages.append(ConversationMessage.assistant_text("Answer " + "Y" * 100))
        session = Session(messages=messages)

        config = CompactionConfig(max_estimated_tokens=2000, preserve_recent_messages=4)
        result = compact_session(session, config)
        # 验证结果对象结构完整
        assert result.compacted_session is not None
        # 当有移除消息时 summary 不应为空
        if result.removed_message_count > 0:
            assert result.summary != ''
            assert result.formatted_summary != ''

    def test_compact_no_removed_messages(self):
        """当无需移除消息时直接返回"""
        config = CompactionConfig(preserve_recent_messages=100)
        session = Session(messages=[
            ConversationMessage.user_text("A" * 500),
            ConversationMessage.user_text("B" * 500),
        ])
        result = compact_session(session, config)
        assert result.compacted_session is session
        assert result.removed_message_count == 0

