"""mode_state 深度行为测试（真实文件系统，无 mock）。

覆盖行为面：
1. 数据模型序列化/反序列化
2. 状态文件布局与路径守卫（路径遍历）
3. start / read / update / cancel / resume 生命周期
4. 空状态、缺失状态、损坏状态文件
5. 独占模式互斥与冲突判定
6. 并发读改写（不丢更新、不留半截 JSON）
7. 技能激活状态：持久化、跨会话恢复、深度面试输入锁
8. Ralph 状态规范化校验
9. RuntimeEngine 集成：事件驱动、持久化、重开恢复、压缩

说明：所有测试均使用 `tmp_path`，读写真实磁盘；`SkillStateManager.record_activation`
的 `keyword_detector_func` 参数是被测函数**公开的注入点**，用它构造“取消”
触发器（关键词注册表里根本没有 `cancel` 条目，正常路径无法产生该分支）。
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest
from src.agent.keyword_registry import is_deep_interview_input_blocked
from src.runtime.engine import DispatchDeliveredEvent, DispatchFailedEvent, NotFoundError
from src.workflow.mode_state import (
    ALL_SUPPORTED_MODES,
    DEEP_INTERVIEW_BLOCKED_APPROVAL_INPUTS,
    EXCLUSIVE_MODES,
    DeepInterviewInputLock,
    ModeState,
    ModeStateManager,
    ModeType,
    SkillActiveState,
    SkillStateManager,
    assert_mode_allowed,
    assert_mode_start_allowed,
    can_resume_mode,
    cancel_mode,
    check_mode_conflict,
    create_deep_interview_input_lock,
    get_mode_state_path,
    get_runtime_engine,
    list_active_modes,
    read_existing_skill_state,
    read_mode_state,
    release_deep_interview_input_lock,
    save_skill_state,
    start_mode,
    update_mode_state,
    validate_and_normalize_ralph_state,
)

# ============================================================================
# 辅助
# ============================================================================

def _state_dir(root: Path) -> Path:
    return root / ".clawd" / "state"


def _write_raw_state(root: Path, mode: str, payload: dict) -> Path:
    path = get_mode_state_path(mode, str(root))
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class _FakeKeywordMatch:
    """`keyword_detector_func` 注入点的返回值替身（被测模块公开契约）。"""

    skill: str
    keyword: str = ""


# ============================================================================
# 1. 数据模型
# ============================================================================

class TestModeStateModel:
    def test_to_dict_roundtrip_preserves_all_fields(self):
        state = ModeState(
            mode="pipeline",
            task="build",
            current_phase="mode:pipeline:started",
            started_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:01",
            metadata={"active": True, "n": 3},
        )

        restored = ModeState.from_dict(state.to_dict())

        assert restored == state

    def test_from_dict_fills_defaults_for_missing_keys(self):
        restored = ModeState.from_dict({"mode": "team"})

        assert restored.mode == "team"
        assert restored.task == ""
        assert restored.current_phase == ""
        assert restored.started_at == ""
        assert restored.updated_at == ""
        assert restored.metadata == {}

    def test_from_dict_ignores_unknown_keys(self):
        restored = ModeState.from_dict({"mode": "ralph", "surprise": 1})

        assert restored.mode == "ralph"
        assert not hasattr(restored, "surprise")

    def test_mode_type_constants_match_supported_modes(self):
        declared = {
            ModeType.PIPELINE,
            ModeType.TEAM,
            ModeType.SKILL,
            ModeType.AUTOPILOT,
            ModeType.RALPH,
            ModeType.AUTORESEARCH,
            ModeType.ULTRAWORK,
            ModeType.DEEP_INTERVIEW,
        }

        assert declared == ALL_SUPPORTED_MODES


# ============================================================================
# 2. 路径布局与路径守卫
# ============================================================================

class TestStatePathLayout:
    def test_get_mode_state_path_creates_state_root_and_uses_file_name(self, tmp_path):
        path = get_mode_state_path("pipeline", str(tmp_path))

        assert path == _state_dir(tmp_path) / "mode-pipeline.json"
        assert _state_dir(tmp_path).is_dir()
        assert not path.exists()

    def test_manager_creates_state_root_and_injects_runtime_integration(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))

        assert manager._state_root == _state_dir(tmp_path)
        assert manager._state_root.is_dir()
        assert manager.runtime._mode_manager is manager
        assert manager.runtime._state_dir == _state_dir(tmp_path)

    def test_start_mode_with_escaping_mode_name_raises_and_stays_inside(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))

        with pytest.raises(ValueError, match="Path traversal detected"):
            manager.start_mode("/../../escaped", "task")

        assert not (tmp_path.parent / "escaped.json").exists()
        assert not (tmp_path / "escaped.json").exists()

    def test_get_skill_manager_returns_state_dir_bound_instance(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))

        skill_manager = manager.get_skill_manager()

        assert isinstance(skill_manager, SkillStateManager)
        assert skill_manager is manager.get_skill_manager()
        assert skill_manager.state_dir == manager._state_root


# ============================================================================
# 3. start / read 生命周期 + 损坏文件
# ============================================================================

class TestStartAndRead:
    def test_start_mode_writes_phase_task_and_timestamps(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))

        state = manager.start_mode("pipeline", "ship it", {"active": True})

        on_disk = _read_json(_state_dir(tmp_path) / "mode-pipeline.json")
        assert on_disk["mode"] == "pipeline"
        assert on_disk["task"] == "ship it"
        assert on_disk["current_phase"] == "mode:pipeline:started"
        assert on_disk["metadata"] == {"active": True}
        assert on_disk["started_at"] and on_disk["updated_at"]
        assert state.started_at == on_disk["started_at"]

    def test_read_state_returns_none_when_file_absent(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))

        assert manager.read_state("team") is None

    def test_read_state_returns_none_on_corrupted_json(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        path = get_mode_state_path("ralph", str(tmp_path))
        path.write_text("{ this is not json", encoding="utf-8")

        assert manager.read_state("ralph") is None

    def test_start_mode_twice_overwrites_previous_snapshot(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        first = manager.start_mode("pipeline", "first")
        second = manager.start_mode("pipeline", "second")

        reloaded = manager.read_state("pipeline")
        assert reloaded is not None
        assert reloaded.task == "second"
        assert reloaded.started_at >= first.started_at
        assert second.task == "second"


# ============================================================================
# 4. update / cancel / resume
# ============================================================================

class TestUpdateCancelResume:
    def test_update_state_sets_known_field_and_keeps_metadata_untouched(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("pipeline", "task", {"active": True})

        updated = manager.update_state("pipeline", {"current_phase": "mode:pipeline:step2"})

        assert updated is not None
        assert updated.current_phase == "mode:pipeline:step2"
        assert updated.metadata == {"active": True}
        assert manager.read_state("pipeline").current_phase == "mode:pipeline:step2"

    def test_update_state_puts_unknown_keys_into_metadata(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("pipeline", "task")

        updated = manager.update_state("pipeline", {"progress": 0.5})

        assert updated is not None
        assert updated.metadata["progress"] == 0.5
        assert _read_json(_state_dir(tmp_path) / "mode-pipeline.json")["metadata"]["progress"] == 0.5

    def test_update_state_returns_none_when_mode_never_started(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))

        assert manager.update_state("team", {"current_phase": "x"}) is None

    def test_cancel_mode_marks_phase_and_records_reason(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("autopilot", "task")

        assert manager.cancel_mode("autopilot", "user asked") is True

        state = manager.read_state("autopilot")
        assert state is not None
        assert state.current_phase == "mode:autopilot:cancelled"
        assert state.metadata["cancel_reason"] == "user asked"

    def test_cancel_mode_returns_false_when_mode_absent(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))

        assert manager.cancel_mode("autopilot") is False

    def test_can_resume_returns_bool_true_for_started_state(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("pipeline", "task")

        resumed = manager.can_resume("pipeline")

        assert resumed is True

    def test_can_resume_is_false_after_cancel(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("pipeline", "task")
        manager.cancel_mode("pipeline")

        assert manager.can_resume("pipeline") is False

    def test_can_resume_is_false_when_started_at_empty(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        _write_raw_state(
            tmp_path,
            "pipeline",
            {"mode": "pipeline", "task": "t", "current_phase": "mode:pipeline:started"},
        )

        assert manager.can_resume("pipeline") is False

    def test_can_resume_is_false_when_state_missing(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))

        assert manager.can_resume("skill") is False


# ============================================================================
# 5. 独占模式互斥
# ============================================================================

class TestModeConflict:
    def test_non_exclusive_mode_never_conflicts(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("autopilot", "task", {"active": True})

        assert manager.check_mode_conflict("pipeline") is None
        assert "pipeline" not in EXCLUSIVE_MODES

    def test_active_exclusive_mode_blocks_other_exclusive_mode(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("autopilot", "task", {"active": True})

        assert manager.check_mode_conflict("ralph") == "autopilot"

    def test_inactive_mode_does_not_conflict(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("autopilot", "task", {"active": False})

        assert manager.check_mode_conflict("ralph") is None

    def test_terminal_phase_does_not_conflict(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        _write_raw_state(
            tmp_path,
            "autopilot",
            {
                "mode": "autopilot",
                "task": "t",
                "current_phase": "mode:autopilot:cancelled",
                "started_at": "2026-01-01T00:00:00",
                "metadata": {"active": True},
            },
        )

        assert manager.check_mode_conflict("ralph") is None

    def test_same_mode_does_not_conflict_with_itself(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("ralph", "task", {"active": True})

        assert manager.check_mode_conflict("ralph") is None

    def test_assert_mode_allowed_raises_with_conflicting_mode_name(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("ultrawork", "task", {"active": True})

        with pytest.raises(RuntimeError, match="ultrawork is already active"):
            manager.assert_mode_allowed("ralph")

    def test_assert_mode_allowed_passes_when_no_conflict(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))

        manager.assert_mode_allowed("ralph")

    def test_list_active_modes_reports_only_active_flags(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("pipeline", "a", {"active": True})
        manager.start_mode("team", "b", {"active": False})
        manager.start_mode("skill", "c")

        assert manager.list_active_modes() == ["pipeline"]

    def test_list_active_modes_empty_when_nothing_started(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))

        assert manager.list_active_modes() == []


# ============================================================================
# 6. 并发读改写
# ============================================================================

class TestConcurrentStateWrites:
    def test_parallel_updates_do_not_lose_keys(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("team", "concurrent")
        workers = 8
        errors: list[BaseException] = []

        def worker(index: int) -> None:
            try:
                manager.update_state("team", {f"k{index}": index})
            except BaseException as exc:  # 线程内异常必须回传主线程断言
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert errors == []
        final = manager.read_state("team")
        assert final is not None
        assert {f"k{i}": i for i in range(workers)}.items() <= final.metadata.items()
        # 文件必须始终是完整 JSON（原子写 + 锁）
        assert _read_json(_state_dir(tmp_path) / "mode-team.json")["metadata"].keys() >= {
            f"k{i}" for i in range(workers)
        }

    def test_parallel_updates_keep_file_parseable_when_reader_runs_concurrently(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("team", "reader-writer")
        read_failures: list[str] = []
        stop = threading.Event()

        def reader() -> None:
            path = _state_dir(tmp_path) / "mode-team.json"
            while not stop.is_set():
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                except (FileNotFoundError, PermissionError):
                    # 文件正被 os.replace 换主：Windows 上读者会短暂被拒。
                    # 这里断言的是"读到的内容永远可解析"，不是"读取永不被打断"。
                    continue
                except json.JSONDecodeError as exc:
                    read_failures.append(str(exc))

        def writer() -> None:
            for i in range(20):
                manager.update_state("team", {f"w{i}": i})

        reader_thread = threading.Thread(target=reader)
        reader_thread.start()
        try:
            writer()
        finally:
            stop.set()
            reader_thread.join(timeout=30)

        assert read_failures == []


# ============================================================================
# 7. 技能激活状态
# ============================================================================

class TestSkillActiveStateSerialization:
    def test_roundtrip_including_input_lock(self):
        state = SkillActiveState(
            active=True,
            skill="deep-interview",
            keyword="deep interview",
            phase="planning",
            activated_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:01",
            session_id="s1",
            thread_id="th1",
            turn_id="tu1",
            input_lock=DeepInterviewInputLock(
                active=True,
                acquired_at="2026-01-01T00:00:00",
                blocked_inputs=["yes"],
                message="blocked",
            ),
        )

        restored = SkillActiveState.from_dict(state.to_dict())

        assert restored == state
        assert restored.input_lock is not None
        assert restored.input_lock.blocked_inputs == ["yes"]

    def test_from_dict_without_input_lock_yields_none(self):
        restored = SkillActiveState.from_dict({"active": True, "skill": "ralph_loop"})

        assert restored.input_lock is None
        assert restored.version == 1
        assert restored.source == "keyword-detector"

    def test_from_dict_empty_dict_uses_defaults(self):
        restored = SkillActiveState.from_dict({})

        assert restored.active is False
        assert restored.skill == ""
        assert restored.phase == ""


class TestDeepInterviewLockHelpers:
    def test_create_lock_keeps_acquired_at_when_previous_active(self):
        previous = DeepInterviewInputLock(active=True, acquired_at="2026-01-01T00:00:00")

        lock = create_deep_interview_input_lock("2026-02-02T00:00:00", previous)

        assert lock.active is True
        assert lock.acquired_at == "2026-01-01T00:00:00"
        assert lock.blocked_inputs == DEEP_INTERVIEW_BLOCKED_APPROVAL_INPUTS

    def test_create_lock_uses_now_when_previous_inactive(self):
        previous = DeepInterviewInputLock(active=False, acquired_at="2026-01-01T00:00:00")

        lock = create_deep_interview_input_lock("2026-02-02T00:00:00", previous)

        assert lock.acquired_at == "2026-02-02T00:00:00"

    def test_blocked_inputs_list_is_copied_not_shared(self):
        first = create_deep_interview_input_lock("2026-01-01T00:00:00")
        first.blocked_inputs.append("definitely-not-blocked")

        second = create_deep_interview_input_lock("2026-01-01T00:00:00")

        assert "definitely-not-blocked" not in second.blocked_inputs
        assert DEEP_INTERVIEW_BLOCKED_APPROVAL_INPUTS == [
            "yes", "y", "proceed", "continue", "ok", "sure", "go ahead", "next i should"
        ]

    def test_release_returns_none_without_previous_lock(self):
        assert release_deep_interview_input_lock(None, "2026-01-01T00:00:00") is None

    def test_release_marks_inactive_and_keeps_exit_reason(self):
        previous = DeepInterviewInputLock(
            active=True, acquired_at="2026-01-01T00:00:00", blocked_inputs=["yes"], message="m"
        )

        released = release_deep_interview_input_lock(previous, "2026-01-02T00:00:00", "abort")

        assert released is not None
        assert released.active is False
        assert released.acquired_at == "2026-01-01T00:00:00"
        assert released.released_at == "2026-01-02T00:00:00"
        assert released.exit_reason == "abort"
        assert released.blocked_inputs == ["yes"]
        assert released.message == "m"


class TestSkillStatePersistence:
    def test_save_creates_parent_directory_and_returns_true(self, tmp_path):
        path = tmp_path / "nested" / "deeper" / "skill-active-state.json"

        assert save_skill_state(path, SkillActiveState(active=True, skill="ralph_loop")) is True
        assert _read_json(path)["skill"] == "ralph_loop"

    def test_save_returns_false_when_parent_path_is_a_file(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")

        assert save_skill_state(blocker / "skill-active-state.json", SkillActiveState()) is False

    def test_read_returns_none_when_file_missing(self, tmp_path):
        assert read_existing_skill_state(tmp_path / "missing.json") is None

    def test_read_returns_none_for_corrupted_file(self, tmp_path):
        path = tmp_path / "skill-active-state.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")

        assert read_existing_skill_state(path) is None

    def test_manager_state_path_is_inside_state_dir(self, tmp_path):
        manager = SkillStateManager(_state_dir(tmp_path))

        assert manager.get_state_path() == _state_dir(tmp_path) / "skill-active-state.json"
        assert manager.get_current_state() is None


class TestSkillActivationRecording:
    def test_returns_none_when_text_has_no_skill_keyword(self, tmp_path):
        manager = SkillStateManager(_state_dir(tmp_path))

        assert manager.record_activation("just a normal sentence") is None
        assert manager.get_state_path().exists() is False

    def test_records_activation_and_persists_state(self, tmp_path):
        manager = SkillStateManager(_state_dir(tmp_path))

        state = manager.record_activation("$ralph 请开始循环", session_id="sess-1")

        assert state is not None
        assert state.active is True
        assert state.skill == "ralph_loop"
        assert state.keyword == "ralph"
        assert state.phase == "planning"
        assert state.session_id == "sess-1"
        on_disk = _read_json(manager.get_state_path())
        assert on_disk["skill"] == "ralph_loop"
        assert on_disk["active"] is True
        assert on_disk["activated_at"] == state.activated_at

    def test_activated_at_is_persisted_and_survives_repeated_activation(self, tmp_path):
        manager = SkillStateManager(_state_dir(tmp_path))
        first = manager.record_activation("$ralph 第一次", now_iso="2026-01-01T00:00:00")

        second = manager.record_activation("$ralph 第二次", now_iso="2026-02-02T00:00:00")

        assert first is not None and second is not None
        assert first.activated_at == "2026-01-01T00:00:00"
        assert second.activated_at == "2026-01-01T00:00:00"
        assert second.updated_at == "2026-02-02T00:00:00"

    def test_state_survives_new_manager_instance(self, tmp_path):
        first_manager = SkillStateManager(_state_dir(tmp_path))
        first_manager.record_activation("$review 帮我审一下", session_id="sess-9")

        reopened = SkillStateManager(_state_dir(tmp_path)).get_current_state()

        assert reopened is not None
        assert reopened.skill == "code_review"
        assert reopened.session_id == "sess-9"

    def test_deep_interview_activation_locks_auto_approval_inputs(self, tmp_path):
        manager = SkillStateManager(_state_dir(tmp_path))

        state = manager.record_activation("$deep-interview 我们来聊聊需求")

        assert state is not None
        assert state.skill == "deep-interview"
        assert state.input_lock is not None
        assert state.input_lock.active is True
        blocked, message = is_deep_interview_input_blocked("yes", workdir=tmp_path)
        assert blocked is True
        assert message == state.input_lock.message

    def test_cancel_releases_deep_interview_lock(self, tmp_path):
        manager = SkillStateManager(_state_dir(tmp_path))
        manager.record_activation("$deep-interview 开始", session_id="sess-1")

        cancel_match = _FakeKeywordMatch(skill="cancel", keyword="cancel")
        state = manager.record_activation(
            "cancel", keyword_detector_func=lambda _text: cancel_match
        )

        assert state is not None
        assert state.active is False
        assert state.phase == "completing"
        assert state.skill == "deep-interview"
        assert state.input_lock is not None
        assert state.input_lock.active is False
        assert state.input_lock.exit_reason == "abort"
        on_disk = _read_json(manager.get_state_path())
        assert on_disk["active"] is False
        assert on_disk["input_lock"]["active"] is False
        assert is_deep_interview_input_blocked("yes", workdir=tmp_path) == (False, None)

    def test_cancel_without_previous_state_is_recorded_as_normal_activation(self, tmp_path):
        manager = SkillStateManager(_state_dir(tmp_path))
        cancel_match = _FakeKeywordMatch(skill="cancel", keyword="abort now")

        state = manager.record_activation(
            "cancel", keyword_detector_func=lambda _text: cancel_match
        )

        assert state is not None
        assert state.active is True
        assert state.phase == "planning"
        assert state.keyword == "abort now"


# ============================================================================
# 8. Ralph 状态规范化
# ============================================================================

class TestRalphStateNormalization:
    @pytest.mark.parametrize("missing", ["current_phase", "started_at"])
    def test_missing_required_field_raises(self, missing):
        payload = {"current_phase": "idle", "started_at": "2026-01-01T00:00:00"}
        payload.pop(missing)

        with pytest.raises(ValueError, match=f"Missing required field: {missing}"):
            validate_and_normalize_ralph_state(payload)

    def test_invalid_phase_is_normalized_to_idle(self):
        normalized = validate_and_normalize_ralph_state(
            {"current_phase": "teleporting", "started_at": "2026-01-01T00:00:00"}
        )

        assert normalized["current_phase"] == "idle"

    def test_valid_state_is_returned_unchanged_with_metadata_added(self):
        payload = {"current_phase": "executing", "started_at": "2026-01-01T00:00:00"}

        normalized = validate_and_normalize_ralph_state(payload)

        assert normalized["current_phase"] == "executing"
        assert normalized["started_at"] == "2026-01-01T00:00:00"
        assert normalized["metadata"] == {}

    def test_invalid_timestamps_are_reset_to_now(self):
        normalized = validate_and_normalize_ralph_state(
            {
                "current_phase": "idle",
                "started_at": "not-a-date",
                "updated_at": "also-not-a-date",
            }
        )

        assert normalized["started_at"] != "not-a-date"
        assert normalized["updated_at"] != "also-not-a-date"


# ============================================================================
# 9. 模式启动前断言 + 便捷函数
# ============================================================================

class TestStartGuardAndConvenienceFunctions:
    def test_assert_mode_start_allowed_raises_on_conflict(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("autopilot", "task", {"active": True})

        with pytest.raises(RuntimeError, match="Cannot start ralph"):
            assert_mode_start_allowed("ralph", tmp_path)

    def test_assert_mode_start_allowed_tolerates_existing_non_exclusive_state(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("pipeline", "task", {"active": True})

        assert_mode_start_allowed("pipeline", tmp_path)

    def test_convenience_functions_delegate_to_manager(self, tmp_path):
        started = start_mode("pipeline", "task", cwd=str(tmp_path), metadata={"active": True})
        assert started.task == "task"

        assert read_mode_state("pipeline", str(tmp_path)).task == "task"
        assert check_mode_conflict("ralph", str(tmp_path)) is None
        assert list_active_modes(str(tmp_path)) == ["pipeline"]
        assert can_resume_mode("pipeline", str(tmp_path)) is True

        updated = update_mode_state("pipeline", {"current_phase": "step-2"}, str(tmp_path))
        assert updated is not None and updated.current_phase == "step-2"

        assert cancel_mode("pipeline", str(tmp_path), "done") is True
        assert read_mode_state("pipeline", str(tmp_path)).metadata["cancel_reason"] == "done"
        assert can_resume_mode("pipeline", str(tmp_path)) is False

    def test_convenience_assert_mode_allowed_raises_on_conflict(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        manager.start_mode("autopilot", "task", {"active": True})

        with pytest.raises(RuntimeError):
            assert_mode_allowed("ralph", str(tmp_path))


# ============================================================================
# 10. RuntimeEngine 集成
# ============================================================================

class TestRuntimeEngineIntegration:
    def test_get_engine_is_cached_and_uses_state_dir(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        integration = manager.runtime

        engine = integration.get_engine()

        assert engine is integration.get_engine()
        assert (manager._state_root / "engine").is_dir()

    def test_fresh_engine_is_not_ready(self, tmp_path):
        integration = ModeStateManager(str(tmp_path)).runtime

        assert integration.is_system_ready() is False
        assert integration.get_snapshot().authority.owner is None

    def test_acquire_authority_makes_system_ready(self, tmp_path):
        integration = ModeStateManager(str(tmp_path)).runtime

        event = integration.acquire_authority("owner-A", "lease-1", "2099-01-01T00:00:00")

        assert event.owner == "owner-A"
        snapshot = integration.get_snapshot()
        assert snapshot.authority.owner == "owner-A"
        assert snapshot.authority.lease_id == "lease-1"
        assert integration.is_system_ready() is True

    def test_dispatch_lifecycle_delivered(self, tmp_path):
        integration = ModeStateManager(str(tmp_path)).runtime

        notified = integration.notify_dispatch("req-1", "worker-1")
        delivered = integration.mark_delivered("req-1")

        assert notified.request_id == "req-1"
        assert isinstance(delivered, DispatchDeliveredEvent)
        backlog = integration.get_snapshot().backlog
        assert (backlog.delivered, backlog.notified, backlog.failed) == (1, 0, 0)

    def test_dispatch_lifecycle_failed(self, tmp_path):
        integration = ModeStateManager(str(tmp_path)).runtime
        integration.notify_dispatch("req-2", "worker-2")

        failed = integration.mark_failed("req-2", "worker crashed")

        assert isinstance(failed, DispatchFailedEvent)
        assert failed.reason == "worker crashed"
        assert integration.get_snapshot().backlog.failed == 1

    def test_marking_unknown_dispatch_raises_not_found(self, tmp_path):
        integration = ModeStateManager(str(tmp_path)).runtime

        with pytest.raises(NotFoundError):
            integration.mark_delivered("never-queued")

    def test_mailbox_message_is_recorded_as_event(self, tmp_path):
        integration = ModeStateManager(str(tmp_path)).runtime

        event = integration.create_mailbox_message("msg-1", "w1", "w2", "hello")

        assert event.message_id == "msg-1"
        assert event.to_worker == "w2"

    def test_persist_writes_snapshot_and_compatibility_views(self, tmp_path):
        manager = ModeStateManager(str(tmp_path))
        integration = manager.runtime
        integration.acquire_authority("owner-A", "lease-1", "2099-01-01T00:00:00")

        integration.persist()

        engine_dir = manager._state_root / "engine"
        written = {p.name for p in engine_dir.iterdir()}
        assert {"snapshot.json", "events.json", "mailbox.json"} <= written
        assert {"authority.json", "backlog.json", "readiness.json", "replay.json"} <= written
        assert _read_json(engine_dir / "snapshot.json")["authority"]["owner"] == "owner-A"

    def test_state_is_restored_by_a_new_manager(self, tmp_path):
        first = ModeStateManager(str(tmp_path))
        first.runtime.acquire_authority("owner-A", "lease-1", "2099-01-01T00:00:00")
        first.runtime.notify_dispatch("req-1", "worker-1")
        first.runtime.persist()

        reopened = ModeStateManager(str(tmp_path))
        snapshot = reopened.runtime.get_snapshot()

        assert snapshot.authority.owner == "owner-A"
        assert snapshot.backlog.notified == 1
        # 事件顺序：acquire-authority → queue-dispatch → mark-notified
        assert len(reopened.runtime.get_engine().event_log) == 3

    def test_compact_events_drops_terminal_records(self, tmp_path):
        integration = ModeStateManager(str(tmp_path)).runtime
        integration.notify_dispatch("req-1", "worker-1")
        integration.mark_delivered("req-1")
        integration.notify_dispatch("req-2", "worker-2")
        before = len(integration.get_engine().event_log)

        integration.compact_events()

        assert len(integration.get_engine().event_log) < before

    def test_get_runtime_engine_returns_integration_for_cwd(self, tmp_path):
        integration = get_runtime_engine(str(tmp_path))

        assert integration._state_dir == _state_dir(tmp_path)
        assert integration.get_engine() is not None
