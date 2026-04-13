"""SessionManager 单元测试 — 验证会话管理、持久化与加载"""
import pytest
import os
import json
import shutil
from pathlib import Path
from src.memory.session_manager import (
    SessionManager,
    Session,
    SessionStatus,
    Message,
    FileSessionStorage,
    create_session,
    get_session,
    save_session
)

@pytest.fixture
def temp_session_dir(tmp_path):
    """创建临时会话存储目录"""
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    # 模拟环境变量
    os.environ["SESSION_STORAGE_PATH"] = str(session_dir)
    yield session_dir
    # 清理环境变量和目录
    if "SESSION_STORAGE_PATH" in os.environ:
        del os.environ["SESSION_STORAGE_PATH"]
    # 重置 SessionManager 实例以确保测试隔离
    SessionManager._instance = None

@pytest.mark.asyncio
async def test_session_creation_and_persistence(temp_session_dir):
    """测试会话创建与持久化"""
    session_id = "test_session_123"
    title = "Test Session"
    user_id = "user_456"

    session = await create_session(session_id, user_id=user_id, title=title)

    assert session.session_id == session_id
    assert session.user_id == user_id
    assert session.title == title
    assert session.status == SessionStatus.ACTIVE

    # 验证文件是否存在
    file_path = temp_session_dir / f"{session_id}.json"
    assert file_path.exists()

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["session_id"] == session_id
        assert data["user_id"] == user_id
        assert data["title"] == title

@pytest.mark.asyncio
async def test_add_message_and_save(temp_session_dir):
    """测试添加消息并保存"""
    session_id = "msg_session"
    session = await create_session(session_id)

    msg = session.add_message("user", "Hello World", metadata={"key": "value"})
    assert len(session.messages) == 1
    assert session.messages[0].content == "Hello World"
    assert session.messages[0].role == "user"
    assert session.messages[0].metadata == {"key": "value"}

    await save_session(session)

    # 重新加载验证
    loaded_session = await get_session(session_id)
    assert loaded_session is not None
    assert len(loaded_session.messages) == 1
    assert loaded_session.messages[0].content == "Hello World"
    assert loaded_session.messages[0].metadata == {"key": "value"}

@pytest.mark.asyncio
async def test_list_and_delete_sessions(temp_session_dir):
    """测试列出和删除会话"""
    await create_session("s1", title="Session 1")
    await create_session("s2", title="Session 2", user_id="user_1")

    sessions = await SessionManager.list_sessions()
    assert len(sessions) >= 2

    # 测试过滤
    user_sessions = await SessionManager.list_sessions(user_id="user_1")
    assert len(user_sessions) == 1
    assert user_sessions[0].session_id == "s2"

    # 测试删除
    success = await SessionManager.delete_session("s1")
    assert success is True
    assert not (temp_session_dir / "s1.json").exists()

    sessions_after_delete = await SessionManager.list_sessions()
    assert len(sessions_after_delete) == 1
    assert sessions_after_delete[0].session_id == "s2"

def test_session_to_from_dict():
    """测试 Session 对象与字典之间的转换"""
    session = Session(session_id="d1", title="Dict Test")
    session.add_message("assistant", "How can I help?")

    data = session.to_dict()
    assert data["session_id"] == "d1"
    assert len(data["messages"]) == 1
    assert data["messages"][0]["role"] == "assistant"

    restored = Session.from_dict(data)
    assert restored.session_id == "d1"
    assert restored.title == "Dict Test"
    assert len(restored.messages) == 1
    assert restored.messages[0].content == "How can I help?"

@pytest.mark.asyncio
async def test_get_messages_limit():
    """测试获取消息时的限制"""
    session = Session(session_id="limit_test")
    for i in range(10):
        session.add_message("user", f"msg {i}")

    assert len(session.get_messages()) == 10
    assert len(session.get_messages(limit=3)) == 3
    assert session.get_messages(limit=3)[0].content == "msg 7"
    assert session.get_messages(limit=3)[2].content == "msg 9"
