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

    def test_transitive_closure_passes_space_separated_args(self):
        """依赖闭包必须把包名以**多个参数**传给 pip show

        真实事故：此前用 `",".join(...)` 拼成一个参数（`pip show a,b,c`），pip 当成
        「一个不存在的包名」→ 闭包永远为空、白名单只剩直接依赖 →
        打包版缺 `annotated_doc`（typer 的间接依赖），装到机器上双击没反应。
        """
        text = HOST_SCRIPT.read_text(encoding="utf-8")
        assert '",".join(sorted(frontier))' not in text, "不要把包名用逗号拼成单个 pip 参数"
        assert '"pip", "show", *chunk' in text or '"pip", "show", *sorted(frontier)' in text

    def test_bundle_self_check_runs_cli_with_bundled_python(self):
        """打包脚本必须用内嵌解释器自检（否则漏依赖只能等装到机器上才发现）"""
        text = HOST_SCRIPT.read_text(encoding="utf-8")
        assert "自检" in text
        assert '"import typer, rich, click' in text
        assert '"-m", "src", "--help"' in text
        assert "raise SystemExit" in text, "自检失败必须中断打包，不能只打印警告"

    def test_windows_optional_dep_in_whitelist(self):
        """loguru 的 win32_setctime 不在 pip Requires 里（只有 extra），必须显式带上"""
        text = HOST_SCRIPT.read_text(encoding="utf-8")
        assert "win32_setctime" in text

    def test_dist_info_copied_with_package(self):
        """dist-info 必须跟包一起复制：不少包 import 时用 importlib.metadata 读自身版本

        真实事故：`import anthropic` → `PackageNotFoundError: No package metadata
        was found for httpx2`（界面能开、一问就崩）。
        """
        text = HOST_SCRIPT.read_text(encoding="utf-8")
        assert "dist-info" in text
        assert "importlib.metadata" in text or "copied_di" in text

    def test_never_copy_pth_files(self):
        """venv 的 editable-install finder .pth 会把 sys.path 指回本机源码目录"""
        text = HOST_SCRIPT.read_text(encoding="utf-8")
        assert 'SP.glob("*.pth")' not in text, "不要复制 .pth（会引入 editable finder / pywin32 路径）"
        assert "不要复制 .pth" in text

    def test_all_runtime_dlls_copied(self):
        """顶层 *.dll 必须全量带（漏 python3.dll → C 扩展 DLL load failed）"""
        text = HOST_SCRIPT.read_text(encoding="utf-8")
        assert 'sys_base.glob("*.dll")' in text, "顶层 DLL 要全量复制，不能手写清单"
        assert "python3.dll" in text

    def test_selfcheck_auto_fills_missing_modules(self):
        """自检发现缺模块要自动从 venv 补齐（元数据闭包不可靠：anyio 的 METADATA 没有 Requires-Dist）"""
        text = HOST_SCRIPT.read_text(encoding="utf-8")
        assert "No module named" in text
        assert "补齐缺失依赖" in text
        assert "exceptiongroup" in text or "max_rounds" in text

    def test_lazy_import_deps_are_packed(self):
        """requirements 里声明、但代码延迟 import 的包必须显式纳入（AST 扫不到）

        漏了它们的表现是"命令存在，一用就缺包"：`clawd git undo/diff`、后台任务、LSP。
        """
        text = HOST_SCRIPT.read_text(encoding="utf-8")
        for pkg in ("celery", "redis", "git", "gitdb", "smmap", "pylsp", "jedi", "opentelemetry"):
            assert f'"{pkg}"' in text, f"bundle 白名单缺延迟 import 的依赖: {pkg}"
        # probe 里也要真的 import 一次，否则"带了但导不进"照样炸
        for pkg in ("celery", "redis", "git", "jedi", "pyflakes"):
            assert f'"{pkg}"' in text

    def test_selfcheck_executes_a_real_tool(self):
        """自检必须真实执行一次工具（FileReadTool）

        装机 E2E 里"让模型读文件"取决于模型愿不愿意调工具（不可控、不可复现），
        工具本体能不能跑是确定性事实，只能用打包后的解释器自己跑一次。
        """
        text = HOST_SCRIPT.read_text(encoding="utf-8")
        assert "FileReadTool(base_path=Path.cwd()).execute(" in text
        assert "工具链自检失败" in text


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
