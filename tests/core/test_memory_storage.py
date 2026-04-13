"""测试 MemoryStorage — 确保异步 I/O 操作正确"""
import pytest

from src.memory.storage import MemoryStorage
from src.memory.models import MemoryEntry, MemoryType


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path / "memory"


@pytest.fixture
def storage(tmp_dir):
    return MemoryStorage(memory_dir=tmp_dir)


@pytest.mark.asyncio
async def test_save_and_load_entries(storage):
    entry = MemoryEntry(
        content="test memory content",
        memory_type=MemoryType.SEMANTIC,
        tags=["test"],
    )
    await storage.save_entries([entry])
    loaded = await storage.load_entries()
    assert len(loaded) == 1
    assert loaded[0].content == "test memory content"


@pytest.mark.asyncio
async def test_load_entries_empty_file(storage):
    # 文件不存在时应返回空列表
    loaded = await storage.load_entries()
    assert loaded == []


@pytest.mark.asyncio
async def test_save_and_load_patterns(storage):
    from src.memory.models import SemanticPattern
    pattern = SemanticPattern(
        name="test pattern",
        category="code_quality",
        pattern="test_regex",
        problem="test problem",
        solution="test solution",
    )
    await storage.save_patterns([pattern])
    loaded = await storage.load_patterns()
    assert len(loaded) == 1
    assert loaded[0].name == "test pattern"


@pytest.mark.asyncio
async def test_load_patterns_empty(storage):
    loaded = await storage.load_patterns()
    assert loaded == []


@pytest.mark.asyncio
async def test_save_and_load_episodic(storage):
    from src.memory.models import EpisodicMemory
    episodic = EpisodicMemory(
        skill_used="test_skill",
        situation="test situation",
        root_cause="test root cause",
        solution="test fix",
        lesson="test lesson",
    )
    await storage.save_episodic(episodic)
    loaded = await storage.load_episodic(episodic.id)
    assert loaded is not None
    assert loaded.skill_used == "test_skill"
    assert loaded.solution == "test fix"


@pytest.mark.asyncio
async def test_load_nonexistent_episodic(storage):
    result = await storage.load_episodic("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_save_and_load_working(storage):
    from src.memory.models import WorkingMemory
    working = WorkingMemory()
    working.data = {"key": "value", "count": 42}
    await storage.save_working(working)
    loaded = await storage.load_working()
    assert loaded.data == {"key": "value", "count": 42}


@pytest.mark.asyncio
async def test_storage_size(storage):
    # 新创建的存储目录大小为 0
    size = await storage.get_storage_size()
    assert size == 0

    # 保存数据后应增加
    entry = MemoryEntry(
        content="some content",
        memory_type=MemoryType.SEMANTIC,
    )
    await storage.save_entries([entry])
    size = await storage.get_storage_size()
    assert size > 0
