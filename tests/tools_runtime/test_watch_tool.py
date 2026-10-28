"""Tests for src.tools_runtime.watch_tool — FileWatcher / WatchTool 真实行为。

覆盖：
1. gitignore 规则装载（默认模式 + 用户 .gitignore + pathspec 缺失降级）
2. 变化过滤 `_filter_func`（越界路径 / 忽略规则 / 大小上限 / AI 注释）
3. AI 注释提取（多语言注释前缀、动作标记 !/?、异常输入）
4. 后台线程启停、变化记录、`process_changes` 结构化输出
5. `WatchTool.execute` 四个 action 的成功/失败路径

线程不依赖真实 watchfiles：`_watch_files` 用注入的伪 watchfiles 模块驱动。
"""
from __future__ import annotations

import json
import sys
import threading
import types

import pytest

from src.tools_runtime import watch_tool as wt
from src.tools_runtime.watch_tool import FileWatcher, WatchTool


@pytest.fixture(autouse=True)
def _isolate_watchers():
    """WatchTool._watchers 是类级共享状态，测试间必须隔离。"""
    WatchTool._watchers.clear()
    yield
    WatchTool._watchers.clear()


@pytest.fixture
def project(tmp_path):
    """一个含源码文件的项目根目录。"""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.py").write_text("x = 1\n", encoding="utf-8")
    return root


class _AliveThread:
    """伪线程：始终存活，用于触发 '已在运行' 分支而不真正启动线程。"""

    def is_alive(self) -> bool:
        return True

    def join(self, timeout: float | None = None) -> None:
        return None


# ---------------------------------------------------------------------------
# 初始化 / gitignore 装载
# ---------------------------------------------------------------------------


class TestFileWatcherInit:
    def test_root_is_resolved_to_absolute(self, project):
        watcher = FileWatcher(str(project))
        assert watcher.root == project.resolve()
        assert watcher.root.is_absolute()

    def test_defaults(self, project):
        watcher = FileWatcher(project)
        assert watcher.gitignores == []
        assert watcher.verbose is False
        assert watcher.max_file_size == 1024 * 1024
        assert watcher.get_changes() == set()

    def test_default_ignore_patterns_applied(self, project):
        spec = FileWatcher(project)._gitignore_spec
        assert spec is not None
        assert spec.match_file("__pycache__/x.py") is True
        assert spec.match_file("a.log") is True
        assert spec.match_file("node_modules/a/b.js") is True
        assert spec.match_file("main.py") is False

    def test_user_gitignore_file_is_loaded(self, project, tmp_path):
        ignore_file = tmp_path / ".gitignore"
        ignore_file.write_text("secret.txt\nbuild/\n", encoding="utf-8")
        spec = FileWatcher(project, gitignores=[str(ignore_file)])._gitignore_spec
        assert spec.match_file("secret.txt") is True
        assert spec.match_file("build/out.bin") is True
        assert spec.match_file("main.py") is False

    def test_missing_gitignore_file_is_skipped(self, project, tmp_path):
        spec = FileWatcher(
            project, gitignores=[str(tmp_path / "nope.gitignore")]
        )._gitignore_spec
        # 仍然只有默认模式生效
        assert spec is not None
        assert spec.match_file("a.log") is True

    def test_pathspec_missing_degrades_to_no_spec(self, project, monkeypatch):
        monkeypatch.setitem(sys.modules, "pathspec", None)
        watcher = FileWatcher(project)
        assert watcher._gitignore_spec is None
        # 没有忽略规则时顶层目录照旧监控
        assert watcher._get_roots_to_watch() == [str(watcher.root)]

    def test_empty_pattern_set_degrades_to_no_spec(self, project, monkeypatch):
        monkeypatch.setattr(wt, "DEFAULT_IGNORE_PATTERNS", [])
        assert FileWatcher(project)._gitignore_spec is None


# ---------------------------------------------------------------------------
# _filter_func
# ---------------------------------------------------------------------------


class TestFilterFunc:
    def test_path_outside_root_is_rejected(self, project, tmp_path):
        outside = tmp_path / "outside.py"
        outside.write_text("# ai! change me\n", encoding="utf-8")
        assert FileWatcher(project)._filter_func("modified", str(outside)) is False

    def test_file_with_ai_comment_is_accepted(self, project):
        target = project / "todo.py"
        target.write_text("# ai! refactor\nx = 1\n", encoding="utf-8")
        watcher = FileWatcher(project)
        assert watcher._filter_func("modified", str(target)) is True

    def test_file_without_ai_comment_is_rejected(self, project):
        watcher = FileWatcher(project)
        assert watcher._filter_func("modified", str(project / "main.py")) is False

    def test_file_over_size_limit_is_rejected(self, project):
        big = project / "big.py"
        big.write_text("# ai! refactor\n" + "y = 1\n" * 100, encoding="utf-8")
        watcher = FileWatcher(project, max_file_size=10)
        assert watcher._filter_func("modified", str(big)) is False

    def test_gitignored_path_is_rejected(self, project):
        ignored = project / "__pycache__" / "mod.cpython-310.pyc"
        ignored.parent.mkdir()
        ignored.write_text("# ai! refactor\n", encoding="utf-8")
        assert FileWatcher(project)._filter_func("modified", str(ignored)) is False

    def test_nonexistent_path_is_rejected(self, project):
        watcher = FileWatcher(project)
        assert watcher._filter_func("deleted", str(project / "ghost.py")) is False

    def test_verbose_mode_still_returns_correct_result(self, project):
        target = project / "todo.py"
        target.write_text("# ai! refactor\n", encoding="utf-8")
        watcher = FileWatcher(project, verbose=True)
        assert watcher._filter_func("modified", str(target)) is True
        assert watcher._filter_func("modified", str(project / "main.py")) is False

    def test_gitignore_match_error_is_swallowed(self, project):
        target = project / "todo.py"
        target.write_text("# ai! refactor\n", encoding="utf-8")

        class _BrokenSpec:
            def match_file(self, _path):
                raise RuntimeError("bad pattern")

        watcher = FileWatcher(project)
        watcher._gitignore_spec = _BrokenSpec()
        assert watcher._filter_func("modified", str(target)) is True

    def test_stat_failure_is_rejected(self, project, monkeypatch):
        target = project / "main.py"
        monkeypatch.setattr(wt.Path, "is_file", lambda self: True)

        def boom(self, *args, **kwargs):
            raise OSError("access denied")

        monkeypatch.setattr(wt.Path, "stat", boom)
        assert FileWatcher(project)._filter_func("modified", str(target)) is False

    def test_comment_scan_error_is_rejected(self, project, monkeypatch):
        target = project / "main.py"
        watcher = FileWatcher(project)

        def boom(_path):
            raise ValueError("decoder blew up")

        monkeypatch.setattr(watcher, "get_ai_comments", boom)
        assert watcher._filter_func("modified", str(target)) is False


# ---------------------------------------------------------------------------
# _get_roots_to_watch
# ---------------------------------------------------------------------------


class TestGetRootsToWatch:
    def test_lists_unignored_top_level_entries(self, project):
        (project / "kept.log.txt").write_text("x\n", encoding="utf-8")
        roots = FileWatcher(project)._get_roots_to_watch()
        assert str(project / "main.py") in roots
        assert str(project / "kept.log.txt") in roots

    def test_falls_back_to_root_when_all_entries_ignored(self, tmp_path):
        root = tmp_path / "empty-proj"
        (root / ".git").mkdir(parents=True)
        assert FileWatcher(root)._get_roots_to_watch() == [str(root.resolve())]

    def test_non_directory_root_does_not_raise(self, tmp_path):
        """root 不是目录时 iterdir 抛异常 → 回退到 root 本身。"""
        fake_root = tmp_path / "not-a-dir"
        fake_root.write_text("x\n", encoding="utf-8")
        watcher = FileWatcher(fake_root)
        assert watcher._get_roots_to_watch() == [str(watcher.root)]


# ---------------------------------------------------------------------------
# _watch_files / _handle_changes
# ---------------------------------------------------------------------------


class TestWatchFiles:
    def test_missing_watchfiles_logs_and_returns(self, project, monkeypatch):
        monkeypatch.setitem(sys.modules, "watchfiles", None)
        watcher = FileWatcher(project)
        watcher._stop_event = threading.Event()
        assert watcher._watch_files() is None
        assert watcher.get_changes() == set()

    def test_records_changes_from_watch_stream(self, project, monkeypatch):
        changed = str(project / "main.py")
        fake = types.ModuleType("watchfiles")
        seen_kwargs: dict = {}

        def fake_watch(*roots, **kwargs):
            seen_kwargs["roots"] = roots
            seen_kwargs.update(kwargs)
            yield [(2, changed)]

        fake.watch = fake_watch
        monkeypatch.setitem(sys.modules, "watchfiles", fake)

        watcher = FileWatcher(project)
        watcher._stop_event = threading.Event()
        watcher._watch_files()

        assert watcher.get_changes() == {changed}
        assert seen_kwargs["roots"] == tuple(watcher._get_roots_to_watch())
        assert seen_kwargs["ignore_permission_denied"] is True
        assert seen_kwargs["stop_event"] is watcher._stop_event
        assert callable(seen_kwargs["watch_filter"])

    def test_watch_error_propagates(self, project, monkeypatch):
        fake = types.ModuleType("watchfiles")

        def fake_watch(*roots, **kwargs):
            raise RuntimeError("inotify exploded")
            yield  # pragma: no cover - 保持生成器语义

        fake.watch = fake_watch
        monkeypatch.setitem(sys.modules, "watchfiles", fake)

        watcher = FileWatcher(project, verbose=True)
        watcher._stop_event = threading.Event()
        with pytest.raises(RuntimeError, match="inotify exploded"):
            watcher._watch_files()

    def test_empty_change_batch_stops_loop_without_recording(self, project, monkeypatch):
        fake = types.ModuleType("watchfiles")

        def fake_watch(*roots, **kwargs):
            yield []

        fake.watch = fake_watch
        monkeypatch.setitem(sys.modules, "watchfiles", fake)

        watcher = FileWatcher(project)
        watcher._stop_event = threading.Event()
        watcher._watch_files()
        assert watcher.get_changes() == set()


class TestHandleChanges:
    def test_empty_batch(self, project):
        assert FileWatcher(project)._handle_changes([]) is False

    def test_records_paths_and_returns_true(self, project):
        watcher = FileWatcher(project)
        assert watcher._handle_changes([(1, str(project / "a.py"))]) is True
        assert watcher.get_changes() == {str(project / "a.py")}

    def test_accumulates_across_batches(self, project):
        watcher = FileWatcher(project)
        watcher._handle_changes([(1, str(project / "a.py"))])
        watcher._handle_changes([(2, str(project / "b.py"))])
        assert watcher.get_changes() == {
            str(project / "a.py"),
            str(project / "b.py"),
        }


# ---------------------------------------------------------------------------
# 生命周期与变化访问
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_start_creates_thread_and_stop_clears_it(self, project, monkeypatch):
        monkeypatch.setitem(sys.modules, "watchfiles", None)  # 线程立刻退出
        watcher = FileWatcher(project, verbose=True)
        watcher.start()
        assert watcher._watcher_thread is not None
        assert watcher._stop_event is not None
        watcher.stop()
        assert watcher._watcher_thread is None
        assert watcher._stop_event is None

    def test_start_is_idempotent_while_running(self, project, monkeypatch):
        watcher = FileWatcher(project, verbose=True)
        stub = _AliveThread()
        watcher._watcher_thread = stub
        watcher.start()
        assert watcher._watcher_thread is stub

    def test_stop_without_start_is_noop(self, project):
        watcher = FileWatcher(project)
        watcher.stop()
        assert watcher._watcher_thread is None

    def test_stop_resets_changes_only_on_next_start(self, project, monkeypatch):
        monkeypatch.setitem(sys.modules, "watchfiles", None)
        watcher = FileWatcher(project)
        watcher._handle_changes([(1, str(project / "a.py"))])
        watcher.start()  # start 会重置变化集合
        assert watcher.get_changes() == set()
        watcher.stop()

    def test_get_changes_returns_copy(self, project):
        watcher = FileWatcher(project)
        watcher._handle_changes([(1, str(project / "a.py"))])
        snapshot = watcher.get_changes()
        snapshot.clear()
        assert watcher.get_changes() == {str(project / "a.py")}

    def test_clear_changes(self, project):
        watcher = FileWatcher(project)
        watcher._handle_changes([(1, str(project / "a.py"))])
        watcher.clear_changes()
        assert watcher.get_changes() == set()


# ---------------------------------------------------------------------------
# get_ai_comments
# ---------------------------------------------------------------------------


class TestGetAiComments:
    def test_python_execute_marker(self, project):
        target = project / "todo.py"
        target.write_text("x = 1\n# ai! refactor this\ny = 2\n", encoding="utf-8")
        nums, comments, action = FileWatcher(project).get_ai_comments(str(target))
        assert nums == [2]
        assert comments == ["# ai! refactor this"]
        assert action == "!"

    def test_javascript_ask_marker(self, project):
        target = project / "app.js"
        target.write_text("// ai? what does this do\n", encoding="utf-8")
        nums, comments, action = FileWatcher(project).get_ai_comments(str(target))
        assert (nums, comments, action) == ([1], ["// ai? what does this do"], "?")

    def test_sql_comment_prefix(self, project):
        target = project / "schema.sql"
        target.write_text("SELECT 1;\n-- ai! add index\n", encoding="utf-8")
        nums, comments, action = FileWatcher(project).get_ai_comments(str(target))
        assert nums == [2]
        assert action == "!"

    def test_comment_without_action_marker(self, project):
        # 第三分支要求行尾是 "ai"，因此 "# please ask ai" 会被识别为 AI 注释
        target = project / "notes.py"
        target.write_text("# please ask ai\ny = 1\n", encoding="utf-8")
        nums, comments, action = FileWatcher(project).get_ai_comments(str(target))
        assert nums == [1]
        assert comments == ["# please ask ai"]
        assert action is None

    def test_unrelated_comment_is_ignored(self, project):
        target = project / "notes.py"
        target.write_text("# see ai docs\ny = 1\n", encoding="utf-8")
        assert FileWatcher(project).get_ai_comments(str(target)) == ([], [], None)

    def test_multiple_comments_last_action_wins(self, project):
        target = project / "multi.py"
        target.write_text("# ai? what is this\n# ai! fix it\n", encoding="utf-8")
        nums, _comments, action = FileWatcher(project).get_ai_comments(str(target))
        assert nums == [1, 2]
        assert action == "!"

    def test_no_comments(self, project):
        target = project / "clean.py"
        target.write_text("def f():\n    return 1\n", encoding="utf-8")
        assert FileWatcher(project).get_ai_comments(str(target)) == ([], [], None)

    def test_missing_file(self, project):
        watcher = FileWatcher(project)
        assert watcher.get_ai_comments(str(project / "ghost.py")) == ([], [], None)

    def test_invalid_utf8_is_decoded_replacing(self, project):
        target = project / "latin.py"
        target.write_bytes(b"\xff\xfe\n# ai! fix encoding\n")
        nums, comments, action = FileWatcher(project).get_ai_comments(str(target))
        assert nums == [2]
        assert action == "!"
        assert "fix encoding" in comments[0]


# ---------------------------------------------------------------------------
# process_changes
# ---------------------------------------------------------------------------


class TestProcessChanges:
    def test_reports_comments_and_actions(self, project):
        ai_file = project / "todo.py"
        ai_file.write_text("# ai! refactor\n", encoding="utf-8")
        plain_file = project / "main.py"

        watcher = FileWatcher(project)
        watcher._handle_changes([
            (1, str(ai_file)),
            (2, str(plain_file)),
        ])
        result = watcher.process_changes()

        assert sorted(result["changed_files"]) == sorted(
            [str(ai_file), str(plain_file)]
        )
        assert result["ai_comments"][str(ai_file)] == [(1, "# ai! refactor")]
        assert result["actions"][str(ai_file)] == "!"
        assert str(plain_file) not in result["ai_comments"]
        assert str(plain_file) not in result["actions"]

    def test_empty_state(self, project):
        assert FileWatcher(project).process_changes() == {
            "changed_files": [],
            "ai_comments": {},
            "actions": {},
        }

    def test_tracked_files_argument_does_not_filter(self, project):
        """保留参数但当前实现不用于过滤 —— 固定现状。"""
        ai_file = project / "todo.py"
        ai_file.write_text("# ai? explain\n", encoding="utf-8")
        watcher = FileWatcher(project)
        watcher._handle_changes([(1, str(ai_file))])
        result = watcher.process_changes(tracked_files=set())
        assert result["changed_files"] == [str(ai_file)]
        assert result["actions"] == {str(ai_file): "?"}


# ---------------------------------------------------------------------------
# WatchTool.execute
# ---------------------------------------------------------------------------


class TestWatchToolMetadata:
    def test_metadata(self):
        tool = WatchTool()
        assert tool.name == "WatchTool"
        assert tool.risk_kind == "exec"
        assert tool.is_enabled is True

    def test_action_schema_allowed_values(self):
        schema = {s.name: s for s in WatchTool.parameter_schemas}
        assert schema["action"].required is True
        assert set(schema["action"].allowed_values) == {
            "start", "stop", "get_changes", "process",
        }
        assert schema["path"].required is False


class TestWatchToolExecute:
    def test_unknown_action(self):
        result = WatchTool().execute(action="explode")
        assert result.success is False
        assert result.error == "未知操作: explode"
        assert result.exit_code == 1

    def test_default_action_is_get_changes(self):
        result = WatchTool().execute()
        assert result.success is True
        assert json.loads(result.output) == {}

    def test_start_requires_path(self):
        result = WatchTool().execute(action="start")
        assert result.success is False
        assert result.error == "start 操作需要 path 参数"

    def test_start_success(self, project, monkeypatch):
        monkeypatch.setattr(FileWatcher, "start", lambda self: None)
        result = WatchTool().execute(action="start", path=str(project))
        assert result.success is True
        assert result.output == f"已启动监控: {project.resolve()}"
        assert str(project.resolve()) in WatchTool._watchers

    def test_start_with_gitignore(self, project, tmp_path, monkeypatch):
        ignore_file = tmp_path / "custom.gitignore"
        ignore_file.write_text("skipme/\n", encoding="utf-8")
        monkeypatch.setattr(FileWatcher, "start", lambda self: None)
        WatchTool().execute(
            action="start", path=str(project), gitignore=str(ignore_file)
        )
        watcher = WatchTool._watchers[str(project.resolve())]
        assert watcher.gitignores == [str(ignore_file)]
        assert watcher._gitignore_spec.match_file("skipme/x.txt") is True

    def test_start_twice_reports_running(self, project, monkeypatch):
        monkeypatch.setattr(FileWatcher, "start", lambda self: None)
        tool = WatchTool()
        tool.execute(action="start", path=str(project))
        WatchTool._watchers[str(project.resolve())]._watcher_thread = _AliveThread()
        second = tool.execute(action="start", path=str(project))
        assert second.success is True
        assert second.output == f"监控器已在运行: {project.resolve()}"

    def test_start_failure_is_reported(self, project, monkeypatch):
        def boom(self):
            raise OSError("no such device")

        monkeypatch.setattr(FileWatcher, "start", boom)
        result = WatchTool().execute(action="start", path=str(project))
        assert result.success is False
        assert result.error == "启动监控失败: no such device"
        assert result.exit_code == 1

    def test_stop_specific_path(self, project, monkeypatch):
        monkeypatch.setattr(FileWatcher, "start", lambda self: None)
        tool = WatchTool()
        tool.execute(action="start", path=str(project))
        stopped: list[str] = []
        monkeypatch.setattr(
            FileWatcher, "stop", lambda self: stopped.append(str(self.root))
        )
        result = tool.execute(action="stop", path=str(project))
        assert result.success is True
        assert result.output == f"已停止监控: {project.resolve()}"
        assert stopped == [str(project.resolve())]
        assert WatchTool._watchers == {}

    def test_stop_unknown_path(self, project):
        result = WatchTool().execute(action="stop", path=str(project))
        assert result.success is False
        assert result.error == f"未找到监控器: {project.resolve()}"

    def test_stop_all(self, project, tmp_path, monkeypatch):
        monkeypatch.setattr(FileWatcher, "start", lambda self: None)
        other = tmp_path / "other"
        other.mkdir()
        tool = WatchTool()
        tool.execute(action="start", path=str(project))
        tool.execute(action="start", path=str(other))
        stopped: list[str] = []
        monkeypatch.setattr(
            FileWatcher, "stop", lambda self: stopped.append(str(self.root))
        )
        result = tool.execute(action="stop")
        assert result.success is True
        assert result.output == "已停止 2 个监控器"
        assert len(stopped) == 2
        assert WatchTool._watchers == {}

    def test_get_changes_for_path(self, project, monkeypatch):
        monkeypatch.setattr(FileWatcher, "start", lambda self: None)
        tool = WatchTool()
        tool.execute(action="start", path=str(project))
        watcher = WatchTool._watchers[str(project.resolve())]
        watcher._handle_changes([(1, str(project / "a.py"))])
        result = tool.execute(action="get_changes", path=str(project))
        assert result.success is True
        assert json.loads(result.output) == [str(project / "a.py")]

    def test_get_changes_unknown_path(self, project):
        result = WatchTool().execute(action="get_changes", path=str(project))
        assert result.success is False
        assert result.error == f"未找到监控器: {project.resolve()}"

    def test_get_changes_for_all(self, project, monkeypatch):
        monkeypatch.setattr(FileWatcher, "start", lambda self: None)
        tool = WatchTool()
        tool.execute(action="start", path=str(project))
        WatchTool._watchers[str(project.resolve())]._handle_changes(
            [(1, str(project / "a.py"))]
        )
        result = tool.execute(action="get_changes")
        assert result.success is True
        assert json.loads(result.output) == {
            str(project.resolve()): [str(project / "a.py")]
        }

    def test_process_for_path(self, project, monkeypatch):
        monkeypatch.setattr(FileWatcher, "start", lambda self: None)
        ai_file = project / "todo.py"
        ai_file.write_text("# ai! refactor\n", encoding="utf-8")
        tool = WatchTool()
        tool.execute(action="start", path=str(project))
        WatchTool._watchers[str(project.resolve())]._handle_changes(
            [(1, str(ai_file))]
        )
        result = tool.execute(action="process", path=str(project))
        assert result.success is True
        payload = json.loads(result.output)
        assert payload["actions"] == {str(ai_file): "!"}
        assert payload["ai_comments"] == {str(ai_file): [[1, "# ai! refactor"]]}

    def test_process_unknown_path(self, project):
        result = WatchTool().execute(action="process", path=str(project))
        assert result.success is False
        assert result.error == f"未找到监控器: {project.resolve()}"

    def test_process_for_all(self, project, monkeypatch):
        monkeypatch.setattr(FileWatcher, "start", lambda self: None)
        tool = WatchTool()
        tool.execute(action="start", path=str(project))
        result = tool.execute(action="process")
        assert result.success is True
        assert json.loads(result.output) == {
            str(project.resolve()): {
                "changed_files": [],
                "ai_comments": {},
                "actions": {},
            }
        }


def test_watch_tool_is_importable_from_module_namespace():
    """确保测试使用的模块别名与真实符号一致。"""
    assert wt.WatchTool is WatchTool
