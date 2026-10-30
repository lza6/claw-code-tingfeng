from pathlib import Path

import pytest

from src.core.patch.atomic_patcher import AtomicPatcher
from src.core.patch.models import AtomicChange, PatchOperation


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


# ===========================================================================
# 事务语义 (commit / rollback)
#
# 背景: AtomicPatcher.commit() / rollback() 曾被 agent_loop 与 apply_changes
# 调用，但类里根本没有这两个方法 —— 任何文件编辑都会抛 AttributeError。
# 以下用例锁定该回归。
# ===========================================================================

@pytest.mark.asyncio
async def test_rollback_restores_original_content(patcher, tmp_path):
    """rollback 必须把文件恢复成事务开始时的内容"""
    file_path = Path("r.py")
    full_path = tmp_path / file_path
    full_path.write_text("original = True\n", encoding="utf-8")

    await patcher.begin_transaction([file_path])
    full_path.write_text("mutated = True\n", encoding="utf-8")
    patcher.rollback()

    assert full_path.read_text(encoding="utf-8") == "original = True\n"


@pytest.mark.asyncio
async def test_commit_discards_backup(patcher, tmp_path):
    """commit 之后 rollback 不应再改动文件"""
    file_path = Path("c.py")
    full_path = tmp_path / file_path
    full_path.write_text("v1\n", encoding="utf-8")

    await patcher.begin_transaction([file_path])
    full_path.write_text("v2\n", encoding="utf-8")
    patcher.commit()
    patcher.rollback()

    assert full_path.read_text(encoding="utf-8") == "v2\n"


@pytest.mark.asyncio
async def test_commit_clears_backup_state(patcher, tmp_path):
    """commit 应清空备份，避免备份字典在长会话中无限增长"""
    file_path = Path("g.py")
    (tmp_path / file_path).write_text("x\n", encoding="utf-8")

    await patcher.begin_transaction([file_path])
    assert patcher._backups, "begin_transaction 应产生备份"
    patcher.commit()
    assert not patcher._backups, "commit 后备份应被清空"


# ===========================================================================
# Unified diff 应用 (apply_patch)
#
# 背景: self_healing/engine.py 调用 patcher.apply_patch(file, patch)，但该方法
# 不存在，异常被 except 吞掉 → CODE_PATCH 自愈策略静默失效。
# ===========================================================================

@pytest.fixture
def diff_fixture(tmp_path):
    """返回 (patcher, 文件路径, 初始内容)"""
    file_path = Path("m.py")
    full_path = tmp_path / file_path
    original = "def f():\n    return 1\n\ndef g():\n    return 2\n"
    full_path.write_text(original, encoding="utf-8")
    return AtomicPatcher(base_path=tmp_path), file_path, full_path, original


UNIFIED_DIFF = """--- a/m.py
+++ b/m.py
@@ -1,2 +1,2 @@
 def f():
-    return 1
+    return 100
"""


def test_apply_patch_applies_unified_diff(diff_fixture):
    """标准 unified diff 应被正确应用"""
    patcher, file_path, full_path, _ = diff_fixture

    assert patcher.apply_patch(file_path, UNIFIED_DIFF) is True
    assert full_path.read_text(encoding="utf-8") == (
        "def f():\n    return 100\n\ndef g():\n    return 2\n"
    )


def test_apply_patch_rejects_unmatched_context(diff_fixture):
    """上下文不匹配时必须失败，且不得改动文件"""
    patcher, file_path, full_path, original = diff_fixture

    mismatched = """@@ -1,2 +1,2 @@
 def does_not_exist():
-    return 1
+    return 999
"""
    assert patcher.apply_patch(file_path, mismatched) is False
    assert full_path.read_text(encoding="utf-8") == original


def test_apply_patch_rejects_syntax_breaking_result(diff_fixture):
    """补丁结果语法不合法时必须失败，且不得改动文件"""
    patcher, file_path, full_path, original = diff_fixture

    broken = """@@ -1,2 +1,2 @@
 def f():
-    return 1
+    return (((
"""
    assert patcher.apply_patch(file_path, broken) is False
    assert full_path.read_text(encoding="utf-8") == original


def test_apply_patch_returns_false_for_missing_file(diff_fixture):
    """目标文件不存在时应返回 False 而非抛异常"""
    patcher, _, _, _ = diff_fixture

    assert patcher.apply_patch(Path("does_not_exist.py"), UNIFIED_DIFF) is False


def test_apply_patch_returns_false_when_no_hunk(tmp_path):
    """没有 @@ 头部的文本不应被当作补丁接受"""
    patcher = AtomicPatcher(base_path=tmp_path)
    (tmp_path / "n.py").write_text("x = 1\n", encoding="utf-8")

    assert patcher.apply_patch(Path("n.py"), "这不是一个 diff\n") is False
    assert (tmp_path / "n.py").read_text(encoding="utf-8") == "x = 1\n"


def test_apply_patch_handles_multiple_hunks(tmp_path):
    """多个 hunk 应各自独立定位并全部生效"""
    patcher = AtomicPatcher(base_path=tmp_path)
    f = tmp_path / "multi.py"
    f.write_text(
        "a = 1\nb = 2\nc = 3\n" + "\n" * 8 + "d = 4\ne = 5\n",
        encoding="utf-8",
    )

    diff = """@@ -1,2 +1,2 @@
 a = 1
-b = 2
+b = 20
@@ -11,2 +11,2 @@
 d = 4
-e = 5
+e = 50
"""
    assert patcher.apply_patch(Path("multi.py"), diff) is True
    content = f.read_text(encoding="utf-8")
    assert "b = 20" in content and "e = 50" in content
    assert "b = 2\n" not in content and "e = 5\n" not in content


@pytest.mark.asyncio
async def test_diff_operation_via_apply_changes(patcher, tmp_path):
    """DIFF 操作经 apply_changes 通路也应可用（此前会调不存在的 _apply_diff_hunks）"""
    file_path = Path("via.py")
    full_path = tmp_path / file_path
    full_path.write_text("x = 1\ny = 2\n", encoding="utf-8")

    change = AtomicChange(
        op=PatchOperation.DIFF,
        path=file_path,
        content="@@ -1,2 +1,2 @@\n x = 1\n-y = 2\n+y = 20\n",
    )

    results = await patcher.apply_changes([change])

    assert results[0].success, results[0].error_message
    assert full_path.read_text(encoding="utf-8") == "x = 1\ny = 20\n"
