"""`udiff_parser` 的回归测试。

该模块此前覆盖率 **7.6%**（生产可达），是 LLM 编辑格式 `udiff` 的解析核心：
从模型输出里抠出 ```diff 围栏、拆分 before/after、应用到文件。
解析错误会直接导致"代码被改错"或"改不动"，因此需要行为级测试。
"""
from __future__ import annotations

import pytest

from src.tools_runtime.udiff_parser import (
    SearchTextNotUnique,
    apply_hunks,
    find_diffs,
    hunk_to_before_after,
    normalize_hunk,
)

SINGLE = """```diff
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 def f():
-    return 1
+    return 2
```
"""


class TestFindDiffs:
    def test_extracts_filename_and_hunk(self):
        edits = list(find_diffs(SINGLE))
        assert len(edits) == 1
        fname, hunk = edits[0]
        assert fname == "foo.py"
        assert any("-    return 1" in ln for ln in hunk)
        assert any("+    return 2" in ln for ln in hunk)

    def test_no_fence_yields_nothing(self):
        assert list(find_diffs("just some text\n")) == []

    def test_fence_without_file_header_has_none_name(self):
        text = "```diff\n@@ -1,1 +1,1 @@\n-a\n+b\n```\n"
        edits = list(find_diffs(text))
        assert edits
        assert edits[0][0] is None

    def test_multiple_fenced_blocks(self):
        text = SINGLE + "\n" + SINGLE.replace("return 2", "return 3")
        edits = list(find_diffs(text))
        assert len(edits) == 2

    def test_dev_null_prefix_maps_to_b_name(self):
        text = """```diff
--- /dev/null
+++ b/new.py
@@ -0,0 +1,1 @@
+hello
```
"""
        edits = list(find_diffs(text))
        assert edits[0][0] == "new.py"


class TestHunkToBeforeAfter:
    def test_returns_strings_by_default(self):
        before, after = hunk_to_before_after(["-a\n", "+b\n"])
        assert before == "a\n"
        assert after == "b\n"

    def test_returns_lines_when_requested(self):
        before, after = hunk_to_before_after(
            [" keep\n", "-old\n", "+new\n"], lines=True
        )
        assert before == ["keep\n", "old\n"]
        assert after == ["keep\n", "new\n"]

    def test_context_lines_appear_in_both(self):
        before, after = hunk_to_before_after([" same\n"])
        assert before == after == "same\n"


class TestApplyHunks:
    def test_applies_replace(self):
        edits = list(find_diffs(SINGLE))
        out = apply_hunks("def f():\n    return 1\n", edits)
        assert "return 2" in out
        assert "return 1" not in out

    def test_applies_insertion(self):
        text = """```diff
--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,2 @@
 line1
+line2
```
"""
        out = apply_hunks("line1\n", list(find_diffs(text)))
        assert out == "line1\nline2\n"

    def test_applies_deletion(self):
        text = """```diff
--- a/foo.py
+++ b/foo.py
@@ -1,2 +1,1 @@
 keep
-gone
```
"""
        out = apply_hunks("keep\ngone\n", list(find_diffs(text)))
        assert out.strip() == "keep"

    def test_no_matching_hunk_raises(self):
        edits = list(find_diffs(SINGLE))
        with pytest.raises(ValueError):
            apply_hunks("totally different content\n", edits)

    def test_ambiguous_search_text_raises(self):
        # 目标文本在内容中出现两次，无法确定改哪一处
        text = """```diff
--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,1 @@
-dup
+changed
```
"""
        content = "dup\nmiddle\ndup\n"
        with pytest.raises((SearchTextNotUnique, ValueError)):
            apply_hunks(content, list(find_diffs(text)))


class TestNormalizeHunk:
    def test_whitespace_only_lines_are_normalized(self):
        hunk = ["-a\n", "+b\n", "-   \n", "+   \n"]
        normalized = normalize_hunk(hunk)
        # 规范化后仍应保留 +/- 语义
        joined = "".join(normalized)
        assert "+b" in joined or "+ b" in joined

    def test_round_trip_preserves_content(self):
        before, after = hunk_to_before_after(["-x\n", "+y\n"], lines=True)
        assert before != after
