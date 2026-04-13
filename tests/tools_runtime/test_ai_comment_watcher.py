"""Tests for src.tools_runtime.ai_comment_watcher — AICommentWatcher"""
from __future__ import annotations

import tempfile
from pathlib import Path


class TestAICommentDetection:
    """AI comment pattern matching tests."""

    def test_python_modify_comment(self):
        from src.tools_runtime.ai_comment_watcher import AICommentWatcher
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.py"
            f.write_text(
                "def foo():\n"
                "    x = 1\n"
                "    # ai! refactor this function\n"
                "    return x\n"
            )
            watcher = AICommentWatcher(tmpdir)
            comments = watcher.extract_comments(f)
            assert len(comments) == 1
            assert comments[0].action == "modify"
            assert "refactor" in comments[0].content.lower()

    def test_python_ask_comment(self):
        from src.tools_runtime.ai_comment_watcher import AICommentWatcher
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.py"
            f.write_text(
                "class Foo:\n"
                "    # AI? what does this class do?\n"
                "    pass\n"
            )
            watcher = AICommentWatcher(tmpdir)
            comments = watcher.extract_comments(f)
            assert len(comments) == 1
            assert comments[0].action == "ask"

    def test_javascript_comment(self):
        from src.tools_runtime.ai_comment_watcher import AICommentWatcher
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "app.js"
            f.write_text(
                "function test() {\n"
                "    // ai! add error handling\n"
                "    console.log('hello');\n"
                "}\n"
            )
            watcher = AICommentWatcher(tmpdir)
            comments = watcher.extract_comments(f)
            assert len(comments) == 1
            assert comments[0].action == "modify"

    def test_no_ai_comments(self):
        from src.tools_runtime.ai_comment_watcher import AICommentWatcher
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "clean.py"
            f.write_text("x = 1\ny = 2\nprint(x + y)\n")
            watcher = AICommentWatcher(tmpdir)
            comments = watcher.extract_comments(f)
            assert len(comments) == 0

    def test_code_context_extraction(self):
        from src.tools_runtime.ai_comment_watcher import AICommentWatcher
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.py"
            f.write_text(
                "line1\nline2\nline3\n"
                "# ai! fix this\n"
                "line5\nline6\nline7\n"
            )
            watcher = AICommentWatcher(tmpdir)
            comments = watcher.extract_comments(f)
            assert len(comments) == 1
            assert "line3" in comments[0].code_context
            assert "fix this" in comments[0].code_context


class TestAICommentDataclass:
    """AIComment dataclass tests."""

    def test_ai_comment_creation(self):
        from src.tools_runtime.ai_comment_watcher import AIComment
        c = AIComment(
            file_path=Path("test.py"),
            line_number=10,
            content="refactor this",
            action="modify",
            code_context="def foo():\n    pass",
        )
        assert c.line_number == 10
        assert c.action == "modify"


class TestFormatCommentsForLLM:
    """LLM formatting tests."""

    def test_empty_comments(self):
        from src.tools_runtime.ai_comment_watcher import format_comments_for_llm
        assert format_comments_for_llm([]) == ""

    def test_single_comment(self):
        from src.tools_runtime.ai_comment_watcher import AIComment, format_comments_for_llm
        comments = [AIComment(
            file_path=Path("/proj/test.py"),
            line_number=5,
            content="add error handling",
            action="modify",
            code_context="def foo(): pass",
        )]
        result = format_comments_for_llm(comments)
        assert "修改代码" in result
        assert "add error handling" in result
        assert "test.py" in result

    def test_ask_action(self):
        from src.tools_runtime.ai_comment_watcher import AIComment, format_comments_for_llm
        comments = [AIComment(
            file_path=Path("test.py"),
            line_number=3,
            content="what is this?",
            action="ask",
        )]
        result = format_comments_for_llm(comments)
        assert "回答问题" in result


class TestSupportedExtensions:
    """File extension filtering tests."""

    def test_supported_py(self):
        from src.tools_runtime.ai_comment_watcher import AICommentWatcher
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "x.py"
            f.write_text("# placeholder\n")
            assert AICommentWatcher(tmpdir).is_supported_file(f) is True

    def test_unsupported_txt(self):
        from src.tools_runtime.ai_comment_watcher import AICommentWatcher
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "notes.txt"
            f.write_text("some notes\n")
            assert AICommentWatcher(tmpdir).is_supported_file(f) is False
