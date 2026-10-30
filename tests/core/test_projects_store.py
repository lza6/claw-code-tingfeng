"""项目（工作区）列表测试 —— 抄参考客户端的"添加项目/切换项目"能力"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core import projects_store


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    data = tmp_path / "userdata"
    monkeypatch.setenv("CLAWD_DATA_DIR", str(data))
    return data


def _folder(tmp_path: Path, name: str = "repo") -> Path:
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    return path


class TestProjects:
    def test_add_and_list(self, tmp_path: Path):
        folder = _folder(tmp_path, "alpha")
        project = projects_store.add_project(str(folder))
        assert project["name"] == "alpha"
        assert project["is_active"] is True
        items = projects_store.list_projects()
        assert [i["id"] for i in items] == [project["id"]]

    def test_add_missing_dir_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="目录不存在"):
            projects_store.add_project(str(tmp_path / "nope"))

    def test_set_active_switches(self, tmp_path: Path):
        a = projects_store.add_project(str(_folder(tmp_path, "a")))
        b = projects_store.add_project(str(_folder(tmp_path, "b")))
        assert projects_store.active_project()["id"] == a["id"]  # 首个自动激活
        assert projects_store.set_active(b["id"]) is True
        assert projects_store.active_project()["id"] == b["id"]

    def test_active_workdir_points_to_project(self, tmp_path: Path):
        folder = _folder(tmp_path, "proj")
        projects_store.add_project(str(folder))
        assert projects_store.active_workdir() == folder.resolve()

    def test_remove_active_promotes_other(self, tmp_path: Path):
        a = projects_store.add_project(str(_folder(tmp_path, "a")))
        b = projects_store.add_project(str(_folder(tmp_path, "b")))
        projects_store.set_active(a["id"])
        assert projects_store.remove_project(a["id"]) is True
        assert projects_store.active_project()["id"] == b["id"]

    def test_persisted_across_reload(self, tmp_path: Path):
        folder = _folder(tmp_path, "keep")
        created = projects_store.add_project(str(folder))
        # 重新读取（模拟重启）
        items = projects_store.list_projects()
        assert items[0]["id"] == created["id"]
        assert items[0]["path"] == str(folder.resolve())

    def test_missing_folder_marked_not_exists(self, tmp_path: Path):
        folder = _folder(tmp_path, "gone")
        project = projects_store.add_project(str(folder))
        folder.rmdir()
        items = projects_store.list_projects()
        assert items[0]["exists"] is False
        assert items[0]["id"] == project["id"]
