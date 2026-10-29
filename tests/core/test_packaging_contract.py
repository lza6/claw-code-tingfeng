"""打包契约测试：`prompts/` 必须随发行物一起出去

真实发现（两次，都是"装出来才炸"）：
1. `pyproject.toml` 原来只 `include = ["src*"]` → wheel 里 `prompts/agents/*.md` 为 0 个，
   非 editable 安装下 `clawd review` 直接报「找不到角色模板」。
2. 桌面端 `scripts/prepare_host_bundle.py` 只拷 `src/` → 打包态的
   `python/python.exe -c "from src.agent.review_team import available_review_roles"`
   报 `ModuleNotFoundError: No module named 'prompts'`。

这两处都属于"源码里能用、装出来不能用"，所以用契约测试钉住。
"""

from __future__ import annotations

import re

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "pyproject.toml"
HOST_SCRIPT = REPO / "scripts" / "prepare_host_bundle.py"
PROMPTS_DIR = REPO / "prompts" / "agents"


class TestWheelPackaging:
    def test_pyproject_includes_prompts_package(self):
        text = PYPROJECT.read_text(encoding="utf-8")
        parts = text.split("[tool.setuptools.packages.find]", 1)
        assert len(parts) == 2, "找不到 [tool.setuptools.packages.find] 段"
        # include 行可能在段首注释之后，取该段前十行找 include 语句
        window = "\n".join(parts[1].splitlines()[:10])
        match = re.search(r"include\s*=\s*\[(.*?)\]", window, re.S)
        assert match, "include 语句缺失"
        assert "prompts*" in match.group(1)

    def test_pyproject_declares_markdown_package_data(self):
        text = PYPROJECT.read_text(encoding="utf-8")
        assert '"prompts.agents" = ["*.md"]' in text, "缺 prompts.agents 的 package-data"

    def test_review_role_templates_exist(self):
        from src.agent.review_team import DEFAULT_ROLES

        for role in DEFAULT_ROLES:
            assert (PROMPTS_DIR / f"{role}.md").is_file(), f"缺角色模板: {role}.md"

    def test_prompt_count_is_reasonable(self):
        md_files = list(PROMPTS_DIR.glob("*.md"))
        assert len(md_files) >= 30, f"角色模板疑似缺失，只有 {len(md_files)} 个"


class TestDesktopBundlePackaging:
    def test_host_bundle_script_copies_prompts(self):
        text = HOST_SCRIPT.read_text(encoding="utf-8")
        assert 'robocopy(ROOT / "prompts"' in text, "prepare_host_bundle 必须把 prompts/ 拷进 bundle"
        assert 'OUT / "prompts"' in text

    def test_host_bundle_script_has_cleanup_retry(self):
        """Windows 上杀软/索引器会短暂占用 site-packages 文件（WinError 32）"""
        text = HOST_SCRIPT.read_text(encoding="utf-8")
        assert "rmtree_with_retry" in text
        assert "PermissionError" in text


class TestPersonasPackaging:
    """角色库也要随发行物出去：桌面端选择器读 personas/ 目录"""

    def test_host_bundle_copies_personas(self):
        text = HOST_SCRIPT.read_text(encoding="utf-8")
        assert 'robocopy(ROOT / "personas"' in text
        assert 'OUT / "personas"' in text

    def test_repo_personas_dir_exists(self):
        personas_dir = REPO / "personas"
        assert personas_dir.is_dir()
        assert len(list(personas_dir.glob("*.md"))) >= 4
