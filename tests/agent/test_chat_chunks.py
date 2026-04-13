import pytest
from src.agent.chat_chunks import ChatChunks

def test_chat_chunks_basic_operations():
    chunks = ChatChunks()

    # Test adding messages
    chunks.add_user_message("hello")
    chunks.add_assistant_message("hi there")
    assert len(chunks.cur) == 2
    assert chunks.cur[0]["role"] == "user"
    assert chunks.cur[1]["role"] == "assistant"

    # Test move_cur_to_done
    chunks.move_cur_to_done()
    assert len(chunks.cur) == 0
    assert len(chunks.done) == 2
    assert chunks.done[0]["content"] == "hello"

    # Test clear_cur and clear_reminder
    chunks.add_user_message("temp")
    chunks.reminder = [{"role": "system", "content": "remind"}]
    chunks.clear_cur()
    chunks.clear_reminder()
    assert len(chunks.cur) == 0
    assert len(chunks.reminder) == 0

def test_chat_chunks_all_messages_order():
    chunks = ChatChunks(
        system=[{"role": "system", "content": "s"}],
        examples=[{"role": "user", "content": "ex"}],
        done=[{"role": "user", "content": "d"}],
        repo=[{"role": "user", "content": "r"}],
        readonly_files=[{"role": "user", "content": "ro"}],
        chat_files=[{"role": "user", "content": "cf"}],
        cur=[{"role": "user", "content": "c"}],
        reminder=[{"role": "user", "content": "rem"}]
    )

    all_msgs = chunks.all_messages()
    assert len(all_msgs) == 8
    assert all_msgs[0]["content"] == "s"
    assert all_msgs[-1]["content"] == "rem"

    before_cur = chunks.messages_before_cur()
    assert len(before_cur) == 6
    assert before_cur[-1]["content"] == "cf"

    context = chunks.context_messages()
    assert len(context) == 3
    assert context[0]["content"] == "r"
    assert context[2]["content"] == "cf"

def test_chat_chunks_token_estimation():
    chunks = ChatChunks()
    chunks.add_user_message("12345678") # 8 chars -> ~2 tokens + 4 = 6

    # Test simple estimation
    count = chunks.token_count(None)
    assert count >= 6

    # Test with estimator mock
    class MockEstimator:
        def count_tokens(self, msgs):
            return 42

    assert chunks.token_count(MockEstimator()) == 42

def test_chat_chunks_summary_and_repr():
    chunks = ChatChunks(system=[{"role": "system", "content": "s"}])
    summary = chunks.summary()
    assert summary["system"] == 1
    assert summary["total"] == 1

    rep = repr(chunks)
    assert "system=1" in rep
    assert "total=1" in rep

def test_chat_chunks_cache_control():
    chunks = ChatChunks(system=[{"role": "system", "content": "s"}])
    chunks.add_cache_control_headers()

    # system should have cache control
    assert isinstance(chunks.system[0]["content"], list)
    assert chunks.system[0]["content"][0]["cache_control"]["type"] == "ephemeral"

    # Test cacheable_messages
    cacheable = chunks.cacheable_messages()
    assert len(cacheable) == 1

    # Test move forward with repo
    chunks.repo = [{"role": "user", "content": "repo data"}]
    chunks.add_cache_control_headers()
    assert isinstance(chunks.repo[0]["content"], list)
    assert chunks.repo[0]["content"][0]["cache_control"]["type"] == "ephemeral"

def test_chat_chunks_token_count_by_group():
    chunks = ChatChunks(system=[{"role": "system", "content": "sys"}])

    # Simple estimation
    counts = chunks.token_count_by_group(None)
    assert counts["system"] > 0
    assert "cur" not in counts or counts["cur"] == 0

    # Mock estimator
    class MockEstimator:
        def count_tokens(self, msgs):
            return len(msgs) * 10

    counts = chunks.token_count_by_group(MockEstimator())
    assert counts["system"] == 10
