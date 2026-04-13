import pytest
from pathlib import Path
import os
import tempfile
from src.utils.cache import LruCache
from src.utils.ignore_parser import IgnoreFilter
from src.tools_runtime.bash_tool import is_shell_command_read_only, BashTool
from src.core.settings import AgentSettings, ConfigSourceKind

class TestLruCache:
    def test_eviction(self):
        cache = LruCache(max_size=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        assert "a" not in cache
        assert "b" in cache
        assert "c" in cache
        assert cache.get("b") == 2
        cache.put("d", 4)
        assert "c" not in cache  # c was oldest after b was accessed
        assert "b" in cache
        assert "d" in cache

class TestIgnoreFilter:
    def test_hierarchical_ignore(self, tmp_path):
        root = tmp_path
        (root / ".gitignore").write_text("*.log\n!important.log")
        (root / "subdir").mkdir()
        (root / "subdir" / ".gitignore").write_text("secret.txt\n")
        
        filter = IgnoreFilter(root)
        
        assert filter.is_ignored("test.log") is True
        assert filter.is_ignored("important.log") is False
        assert filter.is_ignored("subdir/secret.txt") is True
        assert filter.is_ignored("subdir/other.txt") is False

class TestShellSecurity:
    @pytest.mark.parametrize("cmd, expected", [
        ("ls", True),
        ("ls -la", True),
        ("cat file.txt", True),
        ("grep pattern file.py", True),
        ("git status", True),
        ("git log", True),
        ("git remote", True),
        ("git remote add origin ...", False),
        ("rm -rf /", False),
        ("awk '{print $1}'", True),
        ("awk 'system(\"rm -rf /\")'", False),
        ("sed 's/a/b/'", True),
        ("sed -i 's/a/b/'", False),
        ("find . -name '*.py'", True),
        ("find . -delete", False),
        ("cat file.txt > out.txt", False),
        ("ls $(rm -rf /)", False),
    ])
    def test_read_only_detection(self, cmd, expected):
        assert is_shell_command_read_only(cmd) == expected

class TestSettingsSource:
    def test_source_tracking(self):
        # Test the logic of _track_sources
        # We can't easily avoid AgentSettings entirely as it's the class being tested.
        # But we can try to run it in a way that doesn't trigger pytest's inspection issues.
        
        # Mock environment
        os.environ["LLM_PROVIDER"] = "groq"
        
        try:
            settings = AgentSettings()
            # Explicitly call the tracking
            settings._track_sources()
            
            # Verify
            source = settings.get_source("llm_provider")
            assert source.kind == ConfigSourceKind.ENV
            assert source.env_key == "LLM_PROVIDER"
        finally:
            if "LLM_PROVIDER" in os.environ:
                del os.environ["LLM_PROVIDER"]
