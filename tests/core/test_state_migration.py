"""状态目录迁移测试（`src/core/state_migration.py`，审计项 X-9 后半）

覆盖：
- `plan_migration` 分类正确（new / identical / conflict + 计数与字节数）
- `dry_run` 一个文件都不动
- 冲突默认不覆盖，源文件保留
- 第二次迁移 `moved == 0`（幂等）
- 拷贝校验失败如实报 `failed`，源文件不丢，其余条目照常处理
- 非法根目录（相同 / 互为父子 / 不存在）明确报错

全部在 `tmp_path` 内完成，不触碰真实仓库目录。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from src.core import state_migration as sm


def _build(src: Path, dst: Path) -> tuple[Path, Path]:
    """造一套源/目标：1 个冲突、2 个待搬、1 个已相同、1 个空目录。"""
    (src / "sessions").mkdir(parents=True)
    (src / "empty").mkdir()
    (src / "providers.json").write_text('{"active": "old"}', encoding="utf-8")
    (src / "sessions" / "s1.json").write_text('{"session": 1}', encoding="utf-8")
    (src / "sessions" / "s2.json").write_text('{"session": 2}', encoding="utf-8")
    (src / "notes.txt").write_text("hello", encoding="utf-8")

    dst.mkdir(parents=True)
    (dst / "providers.json").write_text('{"active": "new"}', encoding="utf-8")
    (dst / "sessions").mkdir()
    (dst / "sessions" / "s2.json").write_text('{"session": 2}', encoding="utf-8")
    return src, dst


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    return _build(tmp_path / "repo" / ".clawd", tmp_path / "home")


def _status_of(entries: list[dict], rel: str) -> str:
    for item in entries:
        if item["rel"] == rel:
            return item["status"]
    raise AssertionError(f"结果里没有条目 {rel}：{[e['rel'] for e in entries]}")


class TestPlan:
    def test_classification(self, roots: tuple[Path, Path]):
        src, dst = roots
        plan = sm.plan_migration(src, dst)

        assert plan["ok"] is True
        assert plan["src_root"] == str(src.resolve())
        assert plan["dst_root"] == str(dst.resolve())
        assert plan["layout"] == "clawd-state/v1"
        assert plan["layout_version"] == 1

        assert _status_of(plan["entries"], "providers.json") == "conflict"
        assert _status_of(plan["entries"], "notes.txt") == "new"
        assert _status_of(plan["entries"], "sessions/s1.json") == "new"
        assert _status_of(plan["entries"], "sessions/s2.json") == "identical"
        assert _status_of(plan["entries"], "empty") == "new"
        assert _status_of(plan["entries"], "sessions") == "identical"

        assert plan["conflict_count"] == 1
        assert plan["conflicts"] == ["providers.json"]
        assert plan["pending_count"] == 3  # notes.txt, sessions/s1.json, empty
        assert plan["total_files"] == 4
        assert plan["total_dirs"] == 2
        # total_bytes 只统计"还要搬"的字节：sessions/s1.json(14) + notes.txt(5)
        assert plan["total_bytes"] == len('{"session": 1}') + len("hello")
        # 源目录全部文件字节（含冲突/已相同的）
        assert plan["total_source_bytes"] == (
            len('{"active": "old"}') + len('{"session": 1}') + len('{"session": 2}') + len("hello")
        )

    def test_plan_is_read_only(self, roots: tuple[Path, Path]):
        src, dst = roots
        before_src = sorted(p.name for p in src.rglob("*"))
        before_dst = sorted(p.name for p in dst.rglob("*"))
        sm.plan_migration(src, dst)
        assert sorted(p.name for p in src.rglob("*")) == before_src
        assert sorted(p.name for p in dst.rglob("*")) == before_dst


class TestMigrate:
    def test_dry_run_touches_nothing(self, roots: tuple[Path, Path]):
        src, dst = roots
        result = sm.migrate_state(src, dst, dry_run=True)

        assert result["dry_run"] is True
        assert result["moved"] == 0
        assert result["skipped"] == 0
        assert result["failed"] == 0
        assert result["conflict"] == 1
        assert (src / "notes.txt").is_file()
        assert (src / "sessions" / "s1.json").is_file()
        assert not (dst / "notes.txt").exists()
        assert not (dst / "sessions" / "s1.json").exists()
        # dry_run 也要告诉调用方"哪些会被搬"
        assert _status_of(result["entries"], "notes.txt") == "new"

    def test_migrate_moves_and_keeps_conflict(self, roots: tuple[Path, Path]):
        src, dst = roots
        result = sm.migrate_state(src, dst)

        assert result["failed"] == 0
        assert result["conflict"] == 1
        assert result["moved"] >= 3  # 2 个文件 + 1 个目录
        assert _status_of(result["entries"], "providers.json") == "conflict"

        # 冲突：目标内容不动，源文件保留（不丢数据）
        assert json.loads((dst / "providers.json").read_text(encoding="utf-8"))["active"] == "new"
        assert (src / "providers.json").is_file()

        # 正常文件：搬过去了，源没了
        assert (dst / "notes.txt").read_text(encoding="utf-8") == "hello"
        assert not (src / "notes.txt").exists()
        assert (dst / "sessions" / "s1.json").is_file()
        assert not (src / "sessions" / "s1.json").exists()
        # 已相同的文件留在原地不动
        assert (dst / "sessions" / "s2.json").is_file()
        assert (src / "sessions" / "s2.json").is_file()

    def test_second_run_is_idempotent(self, roots: tuple[Path, Path]):
        src, dst = roots
        sm.migrate_state(src, dst)

        second = sm.migrate_state(src, dst)

        assert second["moved"] == 0, f"第二次不该再有搬运：{second['entries']}"
        assert second["skipped"] >= 1
        assert second["failed"] == 0

    def test_overwrite_replaces_conflict(self, roots: tuple[Path, Path]):
        src, dst = roots
        result = sm.migrate_state(src, dst, overwrite=True)

        assert result["conflict"] == 0
        assert result["failed"] == 0
        assert json.loads((dst / "providers.json").read_text(encoding="utf-8"))["active"] == "old"
        assert not (src / "providers.json").exists()

    def test_verification_failure_is_reported_and_source_kept(
        self, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ):
        """拷贝校验失败：如实报 failed、清掉半成品、源文件保留、其余条目继续。"""
        src, dst = roots
        real_copy2 = shutil.copy2

        def broken_copy2(source, target, *args, **kwargs):
            if Path(source).name == "notes.txt":
                Path(target).write_bytes(b"")  # 模拟只写了一部分
                return target
            return real_copy2(source, target, *args, **kwargs)

        monkeypatch.setattr(sm.shutil, "copy2", broken_copy2)

        result = sm.migrate_state(src, dst)

        assert result["ok"] is False
        assert result["failed"] == 1
        failed_entry = next(e for e in result["entries"] if e["rel"] == "notes.txt")
        assert failed_entry["status"] == "failed"
        assert "大小不一致" in failed_entry["reason"]
        assert result["errors"] and "notes.txt" in result["errors"][0]

        assert (src / "notes.txt").is_file(), "校验失败绝不能删源文件"
        assert str((src / "notes.txt").read_text(encoding="utf-8")) == "hello"
        assert not (dst / "notes.txt").exists(), "半成品要清理掉"

        # 其余条目不受影响
        assert (dst / "sessions" / "s1.json").is_file()
        assert not (src / "sessions" / "s1.json").exists()

    def test_retry_after_failure_succeeds(self, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch):
        """失败一次后重跑能把剩下的搬完（源文件都还在）。"""
        src, dst = roots
        real_copy2 = shutil.copy2
        calls = {"n": 0}

        def flaky_copy2(source, target, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                Path(target).write_bytes(b"")
                return target
            return real_copy2(source, target, *args, **kwargs)

        monkeypatch.setattr(sm.shutil, "copy2", flaky_copy2)
        first = sm.migrate_state(src, dst)
        assert first["failed"] == 1

        monkeypatch.setattr(sm.shutil, "copy2", real_copy2)
        second = sm.migrate_state(src, dst)
        assert second["failed"] == 0
        assert second["moved"] >= 1


class TestInvalidRoots:
    def test_same_root_rejected(self, roots: tuple[Path, Path]):
        src, _dst = roots
        with pytest.raises(sm.StateMigrationError):
            sm.migrate_state(src, src)

    def test_dst_inside_src_rejected(self, roots: tuple[Path, Path]):
        src, _dst = roots
        with pytest.raises(sm.StateMigrationError):
            sm.plan_migration(src, src / "inside")

    def test_missing_src_rejected(self, tmp_path: Path):
        with pytest.raises(sm.StateMigrationError):
            sm.migrate_state(tmp_path / "nope", tmp_path / "dst")

    def test_errors_are_chinese(self, roots: tuple[Path, Path]):
        src, _dst = roots
        with pytest.raises(sm.StateMigrationError) as excinfo:
            sm.migrate_state(src, src)
        assert any("一" <= ch <= "鿿" for ch in str(excinfo.value))
