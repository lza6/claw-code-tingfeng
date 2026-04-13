import pytest
import asyncio
from pathlib import Path
import tempfile
from src.core.patch.atomic_patcher import AtomicPatcher
from src.core.patch.models import AtomicChange, PatchOperation, PatchResult

@pytest.fixture
def patcher(tmp_path):
    return AtomicPatcher(base_path=tmp_path)

@pytest.mark.asyncio
async def test_atomic_patcher_basic_insert(patcher, tmp_path):
    file_path = Path("test.py")
    full_path = tmp_path / file_path
    full_path.write_text("x = 1\n", encoding="utf-8")

    change = AtomicChange(
        op=PatchOperation.INSERT,
        path=file_path,
        content="y = 2\n"
    )

    results = await patcher.apply_changes([change])
    assert results[0].success
    assert full_path.read_text(encoding="utf-8") == "x = 1\ny = 2\n"

@pytest.mark.asyncio
async def test_atomic_patcher_search_replace_perfect(patcher, tmp_path):
    file_path = Path("app.py")
    full_path = tmp_path / file_path
    content = """def hello():
    print("hello world")
    return True
"""
    full_path.write_text(content, encoding="utf-8")

    # Aider 风格的 SEARCH/REPLACE 块
    sr_content = """print("hello world")
=======
print("hello clawd")"""

    change = AtomicChange(
        op=PatchOperation.SEARCH_REPLACE,
        path=file_path,
        content=sr_content
    )

    results = await patcher.apply_changes([change])
    assert results[0].success

    expected = """def hello():
    print("hello clawd")
    return True
"""
    assert full_path.read_text(encoding="utf-8") == expected

@pytest.mark.asyncio
async def test_atomic_patcher_search_replace_fuzzy_whitespace(patcher, tmp_path):
    file_path = Path("indent.py")
    full_path = tmp_path / file_path
    content = """class MyClass:
    def method(self):
        # some comment
        do_work()
"""
    full_path.write_text(content, encoding="utf-8")

    # 模拟 LLM 丢失了前导缩进
    sr_content = """# some comment
do_work()
=======
# updated comment
do_new_work()"""

    change = AtomicChange(
        op=PatchOperation.SEARCH_REPLACE,
        path=file_path,
        content=sr_content
    )

    results = await patcher.apply_changes([change])
    assert results[0].success

    # 验证缩进是否被正确保持
    expected = """class MyClass:
    def method(self):
        # updated comment
        do_new_work()
"""
    assert full_path.read_text(encoding="utf-8") == expected

@pytest.mark.asyncio
async def test_atomic_patcher_transaction_rollback(patcher, tmp_path):
    file1 = Path("f1.py")
    file2 = Path("f2.py")
    (tmp_path / file1).write_text("v1 = 1\n", encoding="utf-8")
    (tmp_path / file2).write_text("v2 = 2\n", encoding="utf-8")

    changes = [
        AtomicChange(op=PatchOperation.REPLACE, path=file1, line_start=0, line_end=1, content="v1 = 10\n"),
        AtomicChange(op=PatchOperation.REPLACE, path=file2, line_start=0, line_end=1, content="invalid python code ((((("), # 这会触发语法校验失败
    ]

    # 应该失败并回滚
    results = await patcher.apply_changes(changes, use_transaction=True)

    assert not results[-1].success
    assert "语法错误" in results[-1].error_message

    # 验证 file1 也没有被修改（回滚生效）
    assert (tmp_path / file1).read_text(encoding="utf-8") == "v1 = 1\n"
    assert (tmp_path / file2).read_text(encoding="utf-8") == "v2 = 2\n"

@pytest.mark.asyncio
async def test_atomic_patcher_dotdotdot_syntax(patcher, tmp_path):
    file_path = Path("dots.py")
    full_path = tmp_path / file_path
    content = """def long_function():
    print("start")
    # line 1
    # line 2
    # line 3
    print("end")
"""
    full_path.write_text(content, encoding="utf-8")

    sr_content = """def long_function():
    ...
    print("end")
=======
def long_function():
    print("middle")
    print("end")"""

    change = AtomicChange(
        op=PatchOperation.SEARCH_REPLACE,
        path=file_path,
        content=sr_content
    )

    results = await patcher.apply_changes([change])
    assert results[0].success

    # 注意: try_dotdotdots 的实现是简单的字符串替换，
    # 这里 ... 匹配了中间的所有内容
    assert "print(\"middle\")" in full_path.read_text(encoding="utf-8")
    assert "line 1" not in full_path.read_text(encoding="utf-8")

@pytest.mark.asyncio
async def test_atomic_patcher_syntax_error_protection(patcher, tmp_path):
    file_path = Path("broken.py")
    full_path = tmp_path / file_path
    full_path.write_text("x = 1\n", encoding="utf-8")

    change = AtomicChange(
        op=PatchOperation.REPLACE,
        path=file_path,
        line_start=0,
        line_end=1,
        content="if True:\n    pass\n  unindented_error\n" # 缩进错误
    )

    results = await patcher.apply_changes([change])
    assert not results[0].success
    assert "语法错误" in results[0].error_message
    # 文件内容应保持不变
    assert full_path.read_text(encoding="utf-8") == "x = 1\n"
