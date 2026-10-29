"""领域原生工具 + 世界模型自动预热测试（不走 MCP，纯进程内）"""

from __future__ import annotations

import json
import time

from pathlib import Path

import pytest

from src.brain import warmup
from src.tools_runtime.domain_tools import ProjectMapTool, WorldModelTool, get_domain_tools


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "core.py").write_text(
        "def helper():\n    return 1\n\n\ndef entry():\n    return helper()\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg" / "user.py").write_text(
        "from pkg.core import helper\n\n\ndef run():\n    return helper()\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    return tmp_path


# ==========================================================================
# 自动预热
# ==========================================================================


class TestWarmup:
    def test_blocking_warm_becomes_ready(self, repo: Path):
        state = warmup.ensure_warm(repo, blocking=True)

        assert state.state == "ready", f"预热失败: {state.error}"
        assert warmup.is_ready(repo) is True
        assert warmup.get_model(repo) is not None

    def test_status_reports_ready_and_elapsed(self, repo: Path):
        warmup.ensure_warm(repo, blocking=True)
        status = warmup.warm_status(repo)

        assert status["state"] == "ready"
        assert status["indexed"] is True
        assert status["elapsed_s"] >= 0

    def test_ensure_warm_is_idempotent(self, repo: Path):
        first = warmup.ensure_warm(repo, blocking=True)
        started1 = first.started_at
        second = warmup.ensure_warm(repo, blocking=True)

        assert second is first
        assert second.started_at == started1  # 未重新索引

    def test_non_blocking_returns_immediately(self, repo: Path):
        """非阻塞预热必须立刻返回（不能把启动卡住）"""
        t0 = time.perf_counter()
        state = warmup.ensure_warm(repo, blocking=False)
        elapsed = time.perf_counter() - t0

        assert elapsed < 2.0
        assert state.state in ("indexing", "ready")

    def test_get_model_does_not_trigger_indexing(self, tmp_path: Path):
        """未预热时 get_model 返回 None，且不启动索引"""
        fresh = tmp_path / "fresh"
        fresh.mkdir()
        (fresh / "a.py").write_text("x = 1\n", encoding="utf-8")

        assert warmup.get_model(fresh) is None
        assert warmup.warm_status(fresh)["state"] == "idle"


# ==========================================================================
# WorldModelTool
# ==========================================================================


class TestWorldModelTool:
    def test_stats_after_warmup(self, repo: Path):
        warmup.ensure_warm(repo, blocking=True)
        tool = WorldModelTool(repo)

        result = tool.execute(action="stats")

        assert result.success is True, result.error
        payload = json.loads(result.output)
        assert "node_count" in payload
        assert payload["warmup"]["state"] == "ready"

    def test_stats_without_warmup_reports_indexing_not_hang(self, tmp_path: Path):
        """未预热且不等待时：如实返回状态，绝不阻塞"""
        fresh = tmp_path / "cold"
        fresh.mkdir()
        (fresh / "a.py").write_text("x = 1\n", encoding="utf-8")
        tool = WorldModelTool(fresh)

        t0 = time.perf_counter()
        result = tool.execute(action="stats")
        elapsed = time.perf_counter() - t0

        assert elapsed < 2.0
        assert result.success is False
        assert "未就绪" in result.error
        assert result.metadata["state"] in ("idle", "indexing")

    def test_context_returns_architecture_info(self, repo: Path):
        warmup.ensure_warm(repo, blocking=True)
        tool = WorldModelTool(repo)

        result = tool.execute(action="context", file_path="pkg/user.py")

        assert result.success is True, result.error
        data = json.loads(result.output)
        assert data["file"].endswith("user.py")
        assert "upstream" in data and "downstream" in data and "patterns" in data

    def test_context_requires_file_path(self, repo: Path):
        result = WorldModelTool(repo).execute(action="context")
        assert result.success is False
        assert "file_path" in result.error

    def test_context_rejects_path_traversal(self, repo: Path):
        result = WorldModelTool(repo).execute(action="context", file_path="../../etc/passwd")
        assert result.success is False
        assert "越界" in result.error

    def test_context_rejects_missing_file(self, repo: Path):
        result = WorldModelTool(repo).execute(action="context", file_path="pkg/nope.py")
        assert result.success is False
        assert "不存在" in result.error

    def test_predict_returns_file_list(self, repo: Path):
        warmup.ensure_warm(repo, blocking=True)
        tool = WorldModelTool(repo)

        result = tool.execute(action="predict", current_file="pkg/user.py", depth=1)

        assert result.success is True, result.error
        data = json.loads(result.output)
        assert data["current_file"] == "pkg/user.py"
        assert isinstance(data["predicted"], list)

    def test_predict_requires_current_file(self, repo: Path):
        result = WorldModelTool(repo).execute(action="predict")
        assert result.success is False
        assert "current_file" in result.error

    def test_unknown_action_is_explicit_error(self, repo: Path):
        result = WorldModelTool(repo).execute(action="nonsense")
        assert result.success is False
        assert "未知 action" in result.error

    def test_risk_kind_is_read(self):
        assert WorldModelTool.risk_kind == "read"


# ==========================================================================
# ProjectMapTool（不依赖世界模型索引）
# ==========================================================================


class TestProjectMapTool:
    def test_returns_map_without_world_model(self, repo: Path):
        """项目图谱是轻量路径：世界模型没预热也能用"""
        tool = ProjectMapTool(repo)

        result = tool.execute()

        assert result.success is True, result.error
        assert result.output.strip()
        assert result.metadata["file_count"] >= 2

    def test_subpath_narrows_scope(self, repo: Path):
        result = ProjectMapTool(repo).execute(subpath="pkg")
        assert result.success is True
        # pkg/ 下共 3 个 .py：__init__.py / core.py / user.py（README.md 不在范围内）
        assert result.metadata["file_count"] == 3

    def test_subpath_traversal_rejected(self, repo: Path):
        result = ProjectMapTool(repo).execute(subpath="../")
        assert result.success is False
        assert "未找到" in result.error

    def test_empty_repo_is_explicit_error(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = ProjectMapTool(empty).execute()
        assert result.success is False
        assert "未找到" in result.error

    def test_max_files_respected(self, repo: Path):
        result = ProjectMapTool(repo).execute(max_files=1)
        assert result.metadata["file_count"] == 1


# ==========================================================================
# 装配
# ==========================================================================


class TestGetDomainTools:
    def test_returns_domain_and_capability_tools_bound_to_workdir(self, repo: Path):
        """领域工具 + 内置能力工具（状态/记忆/追踪/团队）都要装配进引擎

        v0.80.0 起把这四个能力做成原生工具 —— 它们的实现与 core/mcp 的 Server 类同源，
        只是不再绕 MCP 进程（同进程直连）。
        """
        tools = get_domain_tools(repo)

        names = {t.name for t in tools}
        assert {"WorldModelTool", "ProjectMapTool"} <= names
        assert {"MemoryTool", "StateTool", "TraceTool", "TeamTool"} <= names
        for tool in tools:
            assert tool.workdir == repo.resolve()

    def test_engine_assembly_registers_domain_tools(self, repo: Path):
        """引擎装配后，领域工具必须在工具池里（原生可达，不经 MCP）"""
        import asyncio

        from src.agent.engine import AgentEngine

        engine = AgentEngine(workdir=repo)
        asyncio.run(engine._load_extended_tools())

        assert "WorldModelTool" in engine.tools
        assert "ProjectMapTool" in engine.tools


class TestLargeRepoGuard:
    """大仓库保护：默认不后台全量索引（实测 600 模块 >4 分钟未完），避免白烧 CPU"""

    def test_large_repo_skipped_by_default(self, tmp_path: Path):
        big = tmp_path / "big"
        big.mkdir()
        for i in range(35):
            (big / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")

        state = warmup.ensure_warm(big, max_files=30)

        assert state.state == "skipped_large"
        assert "超过阈值" in state.error

    def test_force_overrides_guard(self, tmp_path: Path):
        forced = tmp_path / "forced"
        forced.mkdir()
        (forced / "a.py").write_text("x = 1\n", encoding="utf-8")

        state = warmup.ensure_warm(forced, max_files=0, force=True, blocking=True)

        assert state.state == "ready"

    def test_tool_reports_skip_reason_not_hang(self, tmp_path: Path):
        big = tmp_path / "bigrepo"
        big.mkdir()
        for i in range(40):
            (big / f"f{i}.py").write_text("y = 2\n", encoding="utf-8")
        warmup.ensure_warm(big, max_files=20)

        result = WorldModelTool(big).execute(action="stats")

        assert result.success is False
        assert result.metadata["state"] == "skipped_large"
