"""Tests for path utilities."""

import os
import tempfile
from pathlib import Path
from src.core.utils.paths import (
    codex_home,
    codex_config_path,
    codex_prompts_dir,
    codex_agents_dir,
    project_codex_agents_dir,
    user_skills_dir,
    project_skills_dir,
    omx_state_dir,
    omx_project_memory_path,
    omx_notepad_path,
    omx_plans_dir,
    omx_logs_dir,
    list_installed_skills,
    ensure_dir,
    ensure_omx_dirs,
    find_project_root,
)


def normalize_path(path: str) -> str:
    """Normalize path separators for cross-platform comparison."""
    return path.replace("\\", "/")


def test_codex_home_default():
    """Test codex_home returns default path."""
    home = codex_home()
    assert home is not None
    assert ".codex" in home


def test_codex_home_env_override(monkeypatch):
    """Test CODEX_HOME environment variable override."""
    monkeypatch.setenv("CODEX_HOME", "/custom/path")
    home = codex_home()
    assert home == "/custom/path"


def test_codex_config_path():
    """Test codex_config_path returns valid path."""
    config_path = codex_config_path()
    assert config_path.endswith("config.toml")
    assert ".codex" in config_path


def test_codex_prompts_dir():
    """Test codex_prompts_dir returns valid path."""
    prompts_dir = codex_prompts_dir()
    assert normalize_path(prompts_dir).endswith("prompts")
    assert ".codex" in prompts_dir


def test_codex_agents_dir():
    """Test codex_agents_dir returns valid path."""
    agents_dir = codex_agents_dir()
    assert normalize_path(agents_dir).endswith("agents")
    assert ".codex" in agents_dir


def test_project_codex_agents_dir():
    """Test project_codex_agents_dir with custom root."""
    root = "/tmp/test_project"
    agents_dir = project_codex_agents_dir(root)
    assert normalize_path(agents_dir) == "/tmp/test_project/.codex/agents"


def test_user_skills_dir():
    """Test user_skills_dir returns valid path."""
    skills_dir = user_skills_dir()
    assert normalize_path(skills_dir).endswith("skills")
    assert ".codex" in skills_dir


def test_project_skills_dir():
    """Test project_skills_dir with custom root."""
    root = "/tmp/test_project"
    skills_dir = project_skills_dir(root)
    assert normalize_path(skills_dir) == "/tmp/test_project/.codex/skills"


def test_omx_state_dir():
    """Test omx_state_dir returns valid path."""
    state_dir = omx_state_dir()
    assert normalize_path(state_dir).endswith(".omx/state")


def test_omx_project_memory_path():
    """Test omx_project_memory_path returns valid path."""
    path = omx_project_memory_path()
    assert normalize_path(path).endswith(".omx/project-memory.json")


def test_omx_notepad_path():
    """Test omx_notepad_path returns valid path."""
    path = omx_notepad_path()
    assert normalize_path(path).endswith(".omx/notepad.md")


def test_omx_plans_dir():
    """Test omx_plans_dir returns valid path."""
    plans_dir = omx_plans_dir()
    assert normalize_path(plans_dir).endswith(".omx/plans")


def test_omx_logs_dir():
    """Test omx_logs_dir returns valid path."""
    logs_dir = omx_logs_dir()
    assert normalize_path(logs_dir).endswith(".omx/logs")


def test_ensure_dir():
    """Test ensure_dir creates directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = os.path.join(tmpdir, "test_subdir")
        assert not os.path.exists(test_dir)
        ensure_dir(test_dir)
        assert os.path.exists(test_dir)
        assert os.path.isdir(test_dir)


def test_ensure_omx_dirs():
    """Test ensure_omx_dirs creates all .omx subdirectories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Clean up any existing .omx
        omx_base = Path(tmpdir) / ".omx"
        if omx_base.exists():
            import shutil
            shutil.rmtree(omx_base)
        
        ensure_omx_dirs(tmpdir)
        
        assert (omx_base / "state").exists()
        assert (omx_base / "plans").exists()
        assert (omx_base / "logs").exists()


def test_list_installed_skills_empty():
    """Test list_installed_skills with no skills."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Temporarily change home to avoid picking up real skills
        original_home = os.environ.get("CODEX_HOME")
        try:
            os.environ["CODEX_HOME"] = tmpdir
            skills = list_installed_skills(tmpdir)
            assert isinstance(skills, list)
        finally:
            if original_home is not None:
                os.environ["CODEX_HOME"] = original_home
            else:
                os.environ.pop("CODEX_HOME", None)


def test_find_project_root():
    """Test find_project_root finds .omx directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create .omx in tmpdir
        omx_dir = Path(tmpdir) / ".omx"
        omx_dir.mkdir()
        
        # Change to tmpdir and find
        original_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            root = find_project_root()
            # Normalize paths for comparison - just check if it ends with our temp dir name
            assert root is not None
            tmpdir_name = Path(tmpdir).name
            assert root.endswith(tmpdir_name) or normalize_path(root).endswith(normalize_path(tmpdir_name))
        finally:
            os.chdir(original_cwd)


def test_find_project_root_not_found():
    """Test find_project_root returns None when no .omx found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        original_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            root = find_project_root()
            assert root is None
        finally:
            os.chdir(original_cwd)
