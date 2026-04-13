"""Tests for Aider Integration Modules

Unit tests for modules ported from Aider.
"""
import pytest
from src.core import important_files, args_parser
from src.llm import exception_handler, message_handler, model_manager
from src.utils import diff_utils, file_patterns, urls, image_utils, deprecated_args
from src.rag import tree_sitter_syntax
from src.cli import spinner


class TestImportantFiles:
    """Tests for important_files module"""

    def test_is_important_package_json(self):
        assert important_files.is_important("package.json")

    def test_is_important_readme(self):
        assert important_files.is_important("README.md")

    def test_is_important_pyproject(self):
        assert important_files.is_important("pyproject.toml")

    def test_is_not_important_regular_file(self):
        assert not important_files.is_important("src/main.py")

    def test_is_config_file(self):
        assert important_files.is_config_file(".env")
        assert important_files.is_config_file("package.json")

    def test_is_documentation(self):
        assert important_files.is_documentation("README.md")
        assert important_files.is_documentation("CHANGELOG.md")

    def test_is_dependency_file(self):
        assert important_files.is_dependency_file("requirements.txt")
        assert important_files.is_dependency_file("package.json")


class TestArgsParser:
    """Tests for args_parser module"""

    def test_create_parser(self):
        parser = args_parser.create_parser()
        assert parser is not None

    def test_parse_empty_args(self):
        parser = args_parser.create_parser()
        args = parser.parse_args([])
        assert args is not None

    def test_validate_edit_format(self):
        assert args_parser.validate_edit_format("editblock")
        assert args_parser.validate_edit_format("wholefile")
        assert not args_parser.validate_edit_format("invalid_format")


class TestMessageHandler:
    """Tests for message_handler module"""

    def test_ensure_alternating_roles(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = message_handler.ensure_alternating_roles(messages)
        assert len(result) == 2

    def test_sanity_check_messages(self):
        # 必须最后一条是 user
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "again"},
        ]
        assert message_handler.sanity_check_messages(messages)

    def test_count_messages_by_role(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "again"},
        ]
        counts = message_handler.count_messages_by_role(messages)
        assert counts["user"] == 2
        assert counts["assistant"] == 1


class TestDiffUtils:
    """Tests for diff_utils module"""

    def test_create_progress_bar(self):
        bar = diff_utils.create_progress_bar(50)
        assert "█" in bar or "#" in bar
        assert "░" in bar or "=" in bar

    def test_diff_stats(self):
        old = "line1\nline2\nline3"
        new = "line1\nline2\nline3\nline4"
        stats = diff_utils.diff_stats(old, new)
        assert stats["added"] >= 0
        assert stats["removed"] >= 0


class TestFilePatterns:
    """Tests for file_patterns module"""

    def test_is_excluded_ds_store(self):
        # 使用完整的通配符路径
        assert file_patterns.is_excluded("**/.DS_Store")

    def test_is_excluded_examples(self):
        assert file_patterns.is_excluded("examples/")

    def test_is_gitignored_pycache(self):
        assert file_patterns.is_gitignored("__pycache__/test.py")

    def test_filter_files(self):
        files = ["README.md", "test.py", ".env"]
        filtered = file_patterns.filter_files(files)
        assert "README.md" in filtered
        assert ".env" in filtered


class TestURLs:
    """Tests for urls module"""

    def test_website_url(self):
        assert urls.WEBSITE == "https://aider.chat/"

    def test_github_issues_url(self):
        assert "github.com" in urls.GITHUB_ISSUES

    def test_get_doc_url(self):
        url = urls.get_doc_url("edit_formats")
        assert url is not None


class TestImageUtils:
    """Tests for image_utils module"""

    def test_is_image_file_png(self):
        assert image_utils.is_image_file("photo.png")

    def test_is_image_file_jpg(self):
        assert image_utils.is_image_file("photo.jpg")

    def test_is_not_image_file(self):
        assert not image_utils.is_image_file("test.py")

    def test_get_image_type(self):
        assert image_utils.get_image_type("photo.png") == "png"
        assert image_utils.get_image_type("photo.jpg") == "jpg"

    def test_is_pdf(self):
        assert image_utils.is_pdf("doc.pdf")


class TestDeprecatedArgs:
    """Tests for deprecated_args module"""

    def test_is_deprecated_model_arg(self):
        assert deprecated_args.is_deprecated_model_arg("--opus")
        assert deprecated_args.is_deprecated_model_arg("--sonnet")
        assert deprecated_args.is_deprecated_model_arg("--haiku")


class TestTreeSitterSyntax:
    """Tests for tree_sitter_syntax module"""

    def test_get_language(self):
        assert tree_sitter_syntax.get_language("test.py") == "python"
        assert tree_sitter_syntax.get_language("test.js") == "javascript"

    def test_get_supported_languages(self):
        langs = tree_sitter_syntax.get_supported_languages()
        assert "python" in langs
        assert "javascript" in langs


class TestSpinner:
    """Tests for spinner module"""

    def test_spinner_creation(self):
        s = spinner.Spinner("Test")
        assert s is not None
        assert s.text == "Test"

    def test_waiting_spinner_creation(self):
        s = spinner.WaitingSpinner("Test")
        assert s is not None


class TestModelManager:
    """Tests for model_manager module"""

    def test_resolve_alias(self):
        mm = model_manager.get_model_manager()
        assert mm.resolve_alias("sonnet") == "claude-sonnet-4-5"
        assert mm.resolve_alias("opus") == "claude-opus-4-6"

    def test_list_models(self):
        mm = model_manager.get_model_manager()
        models = mm.list_models()
        assert len(models) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])