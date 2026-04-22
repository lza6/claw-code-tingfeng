"""Path Utilities for Clawd Code

Provides consistent path resolution for various Clawd Code directories
including user home, project roots, state directories, and skills.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def codex_home() -> str:
    """Get Codex CLI home directory (~/.codex/).
    
    Uses CODEX_HOME environment variable or defaults to ~/.codex.
    
    Returns:
        Absolute path to Codex home directory
    """
    return os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))


def codex_config_path() -> str:
    """Get Codex config file path (~/.codex/config.toml)."""
    return str(Path(codex_home()) / "config.toml")


def codex_prompts_dir() -> str:
    """Get Codex prompts directory (~/.codex/prompts/)."""
    return str(Path(codex_home()) / "prompts")


def codex_agents_dir(codex_home_dir: str | None = None) -> str:
    """Get user-level Codex native agents directory (~/.codex/agents/)."""
    base = codex_home_dir or codex_home()
    return str(Path(base) / "agents")


def project_codex_agents_dir(project_root: str | None = None) -> str:
    """Get project-level Codex native agents directory (.codex/agents/)."""
    root = project_root or os.getcwd()
    return str(Path(root) / ".codex" / "agents")


def user_skills_dir() -> str:
    """Get user-level skills directory (~/.codex/skills/)."""
    return str(Path(codex_home()) / "skills")


def project_skills_dir(project_root: str | None = None) -> str:
    """Get project-level skills directory (.codex/skills/)."""
    root = project_root or os.getcwd()
    return str(Path(root) / ".codex" / "skills")


def legacy_user_skills_dir() -> str:
    """Get historical legacy user-level skills directory (~/.agents/skills/)."""
    return str(Path.home() / ".agents" / "skills")


@dataclass
class InstalledSkillDirectory:
    """Represents an installed skill directory."""
    name: str
    path: str
    scope: str  # "project" or "user"


def list_installed_skills(project_root: str | None = None) -> list[InstalledSkillDirectory]:
    """List all installed skill directories.
    
    Checks both user-level and project-level skill directories.
    
    Args:
        project_root: Project root directory (default: cwd)
        
    Returns:
        List of InstalledSkillDirectory objects
    """
    skills = []

    # Check user skills
    user_dir = Path(user_skills_dir())
    if user_dir.exists():
        for item in user_dir.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                skills.append(InstalledSkillDirectory(
                    name=item.name,
                    path=str(item),
                    scope="user",
                ))

    # Check project skills
    project_dir = Path(project_skills_dir(project_root))
    if project_dir.exists():
        for item in project_dir.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                # Avoid duplicates (project overrides user)
                skills = [s for s in skills if s.name != item.name]
                skills.append(InstalledSkillDirectory(
                    name=item.name,
                    path=str(item),
                    scope="project",
                ))

    return skills


def find_skill_root_overlap() -> list[dict[str, Any]]:
    """Find overlapping skill roots between user and project scopes.
    
    Returns:
        List of overlap reports with canonical_dir and overlapping dirs
    """
    user_skills = {s.name: s.path for s in list_installed_skills()}
    project_skills = {s.name: s.path for s in list_installed_skills()}

    overlaps = []
    for name in set(user_skills.keys()) & set(project_skills.keys()):
        overlaps.append({
            "canonical_dir": project_skills[name],  # Project wins
            "user_dir": user_skills[name],
            "project_dir": project_skills[name],
        })

    return overlaps


def omx_state_dir(project_root: str | None = None) -> str:
    """Get oh-my-codex state directory (.omx/state/)."""
    root = project_root or os.getcwd()
    return str(Path(root) / ".omx" / "state")


def omx_project_memory_path(project_root: str | None = None) -> str:
    """Get oh-my-codex project memory file (.omx/project-memory.json)."""
    root = project_root or os.getcwd()
    return str(Path(root) / ".omx" / "project-memory.json")


def omx_notepad_path(project_root: str | None = None) -> str:
    """Get oh-my-codex notepad file (.omx/notepad.md)."""
    root = project_root or os.getcwd()
    return str(Path(root) / ".omx" / "notepad.md")


def omx_plans_dir(project_root: str | None = None) -> str:
    """Get oh-my-codex plans directory (.omx/plans/)."""
    root = project_root or os.getcwd()
    return str(Path(root) / ".omx" / "plans")


def omx_logs_dir(project_root: str | None = None) -> str:
    """Get oh-my-codex logs directory (.omx/logs/)."""
    root = project_root or os.getcwd()
    return str(Path(root) / ".omx" / "logs")


def package_root() -> str:
    """Get the package root directory (where agents/, skills/, prompts/ live).
    
    Returns:
        Path to the installed package root
    """
    try:
        # If we're in a package, use __file__
        import src
        return str(Path(src.__file__).parent.parent)
    except (ImportError, AttributeError):
        # Fallback to current directory
        return os.getcwd()


def get_package_root() -> str:
    """Alias for package_root()."""
    return package_root()


def ensure_dir(path: str) -> None:
    """Ensure a directory exists, creating it if necessary."""
    Path(path).mkdir(parents=True, exist_ok=True)


def ensure_omx_dirs(project_root: str | None = None) -> None:
    """Ensure all .omx directories exist."""
    root = project_root or os.getcwd()
    base = Path(root) / ".omx"

    ensure_dir(str(base / "state"))
    ensure_dir(str(base / "plans"))
    ensure_dir(str(base / "logs"))


def is_inside_omx_project(path: str) -> bool:
    """Check if a path is inside an .omx project."""
    current = Path(path).resolve()
    while current != current.parent:
        if (current / ".omx").exists():
            return True
        current = current.parent
    return False


def find_project_root(start_path: str | None = None) -> str | None:
    """Find the root of the current project (directory containing .omx/)."""
    current = Path(start_path or os.getcwd()).resolve()

    while current != current.parent:
        if (current / ".omx").exists():
            return str(current)
        current = current.parent

    return None
