import pytest
import re
from pathlib import Path
from src.workflow.version_manager import VersionManager
from src.workflow.hotfix_manager import HotfixManager
from src.workflow.models import TechDebtPriority

def test_version_manager_changelog_enhancement(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('version = "1.0.0"', encoding='utf-8')

    vm = VersionManager(root=tmp_path)

    categories = {
        'added': ['New feature A'],
        'fixed': ['Bug B'],
        'performance': ['Faster C']
    }

    vm.update_changelog("1.1.0", categories)

    changelog = tmp_path / "CHANGELOG.md"
    assert changelog.exists()

    content = changelog.read_text(encoding='utf-8')
    assert "## [1.1.0]" in content
    assert "### Added" in content
    assert "- New feature A" in content
    assert "### Fixed" in content
    assert "- Bug B" in content
    assert "### Performance" in content
    assert "- Faster C" in content

def test_hotfix_manager_bypass_and_cleanup(tmp_path):
    hm = HotfixManager(root=tmp_path)

    assert hm.bypass_tdd is False

    hm.enable("HF-001")
    assert hm.bypass_tdd is True

    # Test annotation
    code = "def foo(): pass"
    annotated = hm.annotate(code, file_ext=".py")
    assert "FIXME-[HF-001]" in annotated

    # Test file cleanup
    test_file = tmp_path / "test.py"
    test_file.write_text(annotated, encoding='utf-8')

    # Apply hotfix applied record
    hm.record_hotfix_applied(test_file)
    assert test_file in hm._hotfixed_files

    # Disable and check event data (simulated)
    hm.disable()
    assert hm.bypass_tdd is False

    # Cleanup
    test_file.write_text(annotated, encoding='utf-8') # restore
    cleaned = hm.cleanup_fixme_annotations(test_file, "HF-001")
    assert cleaned is True
    assert "FIXME" not in test_file.read_text()
    assert "def foo(): pass" in test_file.read_text()
