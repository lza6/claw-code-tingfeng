"""`udiff_parser` 的分支覆盖补充测试（W2）。

现有 `test_udiff_parser.py` 覆盖主路径。本文件专门打**错误分支与边界**：

- 内容不以换行结尾
- 一个 fence 内含两个文件段（`+++` 连续出现）—— 这里发现过一个真实 bug：
  第 2 段起的文件名没剥离 `b/` 前缀，会写到 `b/b.py` 这样的错误路径
- 空 hunk / 重复 hunk 的去重
- 不匹配 / 部分成功各自的消息形态
- 纯新建（before 为空）走追加分支
- 缺少 `diff_match_patch` 时的 difflib 回退

这些分支决定了"模型给的 diff 有瑕疵时，究竟是报错、还是静默改错文件"。
"""
from __future__ import annotations

import builtins

import pytest

from src.tools_runtime import udiff_parser
from src.tools_runtime.udiff_parser import (
    apply_hunks,
    find_diffs,
    hunk_to_before_after,
)


class TestFindDiffsEdges:
    def test_content_without_trailing_newline(self):
        """find_diffs 会补齐末尾换行，不应因此丢块。"""
        text = """```diff
--- a/f.py
+++ b/f.py
@@ -1 +1 @@
-a
+b
```"""

        edits = list(find_diffs(text))

        assert len(edits) == 1
        assert edits[0][0] == "f.py"

    def test_two_file_sections_inside_one_fence(self):
        """同一 fence 内连续两个 `+++` 段应拆成两个编辑，且都剥离 `b/` 前缀。"""
        text = """```diff
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-x
+y
--- a/b.py
+++ b/b.py
@@ -1 +1 @@
-p
+q
```
"""

        edits = list(find_diffs(text))

        assert len(edits) == 2
        assert [e[0] for e in edits] == ["a.py", "b.py"]

    def test_plain_a_prefix_without_dev_null(self):
        """`a/` 与 `b/` 都在时，文件名取 b/ 去掉前缀。"""
        text = """```diff
--- a/x.py
+++ b/x.py
@@ -1 +1 @@
-a
+b
```
"""

        edits = list(find_diffs(text))

        assert edits[0][0] == "x.py"


class TestFindDiffsHeaderVariants:
    def test_headers_without_a_b_prefix_use_raw_name(self):
        """`--- foo` / `+++ bar` 没有 git 前缀时，文件名原样使用。"""
        text = """```diff
--- foo.txt
+++ bar.txt
@@ -1 +1 @@
-a
+b
```
"""

        edits = list(find_diffs(text))

        assert edits[0][0] == "bar.txt"

    def test_blank_line_inside_block_is_skipped(self):
        """块内空行（长度 < 2）不参与 hunk 结构判断，也不应崩。"""
        text = """```diff
--- a/f.py
+++ b/f.py
@@ -1 +1 @@
-a

+b
```
"""

        edits = list(find_diffs(text))

        assert len(edits) == 1
        assert edits[0][0] == "f.py"

    def test_blank_separator_between_two_sections(self):
        """两段之间有空行时，第一段的尾部空行要一起裁掉。"""
        text = """```diff
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-a
+b

--- a/c.py
+++ b/c.py
@@ -1 +1 @@
-x
+y
```
"""

        edits = list(find_diffs(text))

        assert [e[0] for e in edits] == ["a.py", "c.py"]


class TestHunkToBeforeAfterEdges:
    def test_short_line_without_newline_is_context(self):
        """长度 < 3 的行（无换行的单字符）按上下文处理。"""
        before, after = hunk_to_before_after(["a", "-b\n", "+c\n"], lines=True)

        assert before == ["a", "b\n"]
        assert after == ["a", "c\n"]

    def test_empty_hunk_yields_empty_strings(self):
        before, after = hunk_to_before_after([])

        assert before == ""
        assert after == ""


class TestApplyHunksEdges:
    def test_empty_hunk_list_is_noop(self):
        assert apply_hunks("abc\n", []) == "abc\n"

    def test_hunk_that_normalizes_to_empty_is_skipped(self):
        assert apply_hunks("abc\n", [("f", [])]) == "abc\n"

    def test_duplicate_hunks_applied_once(self):
        """同一 hunk 出现两次只应用一次，否则会重复插入。"""
        hunk = ["-a\n", "+b\n"]

        out = apply_hunks("a\n", [("f", hunk), ("f", list(hunk))])

        assert out == "b\n"

    def test_no_match_error_names_the_construct(self):
        hunk = ["-not-there\n", "+replacement\n"]

        with pytest.raises(ValueError) as ei:
            apply_hunks("something else\n", [("f", hunk)])

        assert "UnifiedDiffNoMatch" in str(ei.value)
        assert "not-there" in str(ei.value)

    def test_partial_success_mentions_note(self):
        """一个能应用、一个不能 —— 报错但要说明"有些已经应用"。"""
        ok = ["-a\n", "+b\n"]
        bad = ["-missing-line\n", "+x\n"]

        with pytest.raises(ValueError) as ei:
            apply_hunks("a\n", [("f", ok), ("f", bad)])

        msg = str(ei.value)
        assert "UnifiedDiffNoMatch" in msg
        assert "some hunks did apply successfully" in msg

    def test_append_to_empty_before(self):
        """before 为空 = 新建/追加，直接拼接。"""
        hunk = ["+hello\n", "+world\n"]

        out = apply_hunks("", [("new.py", hunk)])

        assert out == "hello\nworld\n"

    def test_insert_into_existing_content(self):
        hunk = [" existing\n", "+added\n"]

        out = apply_hunks("existing\n", [("f", hunk)])

        assert out == "existing\nadded\n"


class TestProgressiveContextDropping:
    def test_applies_when_context_lines_are_wrong(self):
        """上下文行对不上、但 change 行能定位时，应裁剪上下文后应用（策略 2）。"""
        content = """header
line1
line2
footer
"""
        hunk = [
            """ context-that-does-not-exist
""",
            """-line1
""",
            """+LINE1
""",
            """ another-wrong-context
""",
        ]

        out = apply_hunks(content, [("f", hunk)])

        assert "LINE1" in out
        assert "line1" not in out


class TestDiffLinesFallback:
    def test_falls_back_to_difflib_without_diff_match_patch(self, monkeypatch):
        """装有 diff_match_patch 时走它；没有则必须回退到 difflib 而不是崩。"""

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "diff_match_patch":
                raise ImportError("simulated absence")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        out = udiff_parser._diff_lines("a\n", "b\n")

        joined = "".join(out)
        assert "-a" in joined
        assert "+b" in joined
