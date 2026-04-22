import os
from pathlib import Path

# Resolve paths relative to script location
script_dir = Path(__file__).parent if "__file__" in globals() else Path.cwd()
project_root = Path(__file__).parent.parent
skills_dir = project_root / "skills"

def write_skill_md(skill_dir: Path):
    """Create a basic SKILL.md if it doesn't exist."""
    md_path = skill_dir / "SKILL.md"
    if md_path.exists():
        return  # Skip if already present

    content = [
        "---\n",
        f"name: {skill_dir.name}\n",
        f"description: Auto-generated description for {skill_dir.name}\n",
        "---\n",
        "\n## Overview\n\nAuto-generated overview.\n",
        "\n## When to Use\n\nAutomation.\n",
        "\n## Implementation\n\nDetails.\n",
        "\n## Tests\n\nUnit tests.\n",
    ]

    with open(md_path, "w", encoding="utf-8") as f:
        f.writelines(content)

if __name__ == "__main__":
    for entry in skills_dir.iterdir():
        if entry.is_dir():
            write_skill_md(entry)