"""状态根单一入口测试（`src/core/data_dir.py`，审计项 X-9 前半）

覆盖：
- `CLAWD_HOME` 生效（`CLAWD_HOME=/tmp/x` 时状态不落进仓库目录）
- `CLAWD_DATA_DIR` 优先于 `CLAWD_HOME`，且 `describe()` 如实标出生效变量
- `state.json` 幂等（两次 `created_at` 相同、文件字节不变）
- 高版本 `state.json` 抛错且信息含中文、不静默改写
- `data_dir()` / `data_path()` / `describe()["data_dir"]` 既有行为回归

所有写盘都落在 `tmp_path`；环境变量用 `monkeypatch` 设置，测试结束自动还原。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from src.core import data_dir as data_dir_mod

CHINESE = re.compile(r"[一-鿿]")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """套件级隔离：不继承开发机上的真实 CLAWD_DATA_DIR / CLAWD_HOME。"""
    monkeypatch.delenv(data_dir_mod.ENV_VAR, raising=False)
    monkeypatch.delenv(data_dir_mod.ENV_VAR_ALIAS, raising=False)


class TestClawdHomeAlias:
    def test_home_env_takes_effect(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        home = tmp_path / "state-home"
        monkeypatch.setenv("CLAWD_HOME", str(home))
        assert data_dir_mod.data_dir() == home
        # workdir 参数不能越过环境变量
        assert data_dir_mod.data_dir(tmp_path / "work") == home
        assert data_dir_mod.describe()["source"] == "CLAWD_HOME"

    def test_data_dir_wins_over_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        home = tmp_path / "state-home"
        data = tmp_path / "state-data"
        monkeypatch.setenv("CLAWD_HOME", str(home))
        monkeypatch.setenv("CLAWD_DATA_DIR", str(data))
        assert data_dir_mod.data_dir() == data
        info = data_dir_mod.describe()
        assert info["source"] == "CLAWD_DATA_DIR"
        assert info["ignored_env"] == "CLAWD_HOME", "两个都设时必须说明谁被忽略"

    def test_home_does_not_write_into_workdir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """X-9 验收点：CLAWD_HOME 指走后，仓库/CWD 下不得再出现 .clawd。"""
        home = tmp_path / "state-home"
        workdir = tmp_path / "repo"
        workdir.mkdir()
        monkeypatch.setenv("CLAWD_HOME", str(home))
        monkeypatch.chdir(workdir)

        state_root = data_dir_mod.ensure_state_dir()

        assert state_root == home
        assert (home / "state.json").is_file()
        assert not (workdir / ".clawd").exists(), "状态被写回了工作目录"

    def test_blank_env_falls_back_to_workdir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("CLAWD_HOME", "   ")  # 手滑写了空格，等同未设置
        assert data_dir_mod.data_dir(tmp_path) == tmp_path / ".clawd"
        assert data_dir_mod.describe()["source"] == "workdir/.clawd"


class TestStateLayout:
    def test_ensure_writes_state_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        data = tmp_path / "data"
        monkeypatch.setenv("CLAWD_DATA_DIR", str(data))

        root = data_dir_mod.ensure_state_dir()

        assert root == data
        payload = json.loads((data / "state.json").read_text(encoding="utf-8"))
        assert payload["version"] == data_dir_mod.STATE_LAYOUT_VERSION == 1
        assert payload["layout"] == "clawd-state/v1"
        assert payload["created_at"], "created_at 不能为空"
        assert data_dir_mod.state_version() == 1

    def test_ensure_is_idempotent(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        data = tmp_path / "data"
        monkeypatch.setenv("CLAWD_DATA_DIR", str(data))

        data_dir_mod.ensure_state_dir()
        first_bytes = (data / "state.json").read_bytes()
        first_created_at = json.loads(first_bytes)["created_at"]

        data_dir_mod.ensure_state_dir()
        second_bytes = (data / "state.json").read_bytes()

        assert json.loads(second_bytes)["created_at"] == first_created_at
        assert second_bytes == first_bytes, "重复调用不应重写 state.json"

    def test_ensure_without_create_does_not_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        data = tmp_path / "data"
        monkeypatch.setenv("CLAWD_DATA_DIR", str(data))

        root = data_dir_mod.ensure_state_dir(create=False)

        assert root == data
        assert not data.exists(), "create=False 不能落盘"
        assert data_dir_mod.state_version() == 0

    def test_newer_layout_raises_and_is_not_rewritten(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        data = tmp_path / "data"
        data.mkdir()
        original = {"version": 99, "created_at": "2029-01-01T00:00:00+00:00", "layout": "clawd-state/v99"}
        (data / "state.json").write_text(json.dumps(original), encoding="utf-8")
        monkeypatch.setenv("CLAWD_DATA_DIR", str(data))

        with pytest.raises(data_dir_mod.StateVersionError) as excinfo:
            data_dir_mod.ensure_state_dir()
        message = str(excinfo.value)
        assert CHINESE.search(message), f"异常信息必须是中文说明：{message}"
        assert "99" in message and str(data_dir_mod.STATE_LAYOUT_VERSION) in message

        with pytest.raises(data_dir_mod.StateVersionError):
            data_dir_mod.state_version()

        assert json.loads((data / "state.json").read_text(encoding="utf-8")) == original, "不得静默降级改写"

    def test_corrupt_state_file_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        data = tmp_path / "data"
        data.mkdir()
        (data / "state.json").write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("CLAWD_DATA_DIR", str(data))

        with pytest.raises(data_dir_mod.StateVersionError) as excinfo:
            data_dir_mod.state_version()
        assert CHINESE.search(str(excinfo.value))


class TestLegacyBehaviour:
    """回归：既有调用方（providers_store / session_bridge / local_db / websocket_server）不受影响。"""

    def test_data_dir_env_wins(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        data = tmp_path / "userdata"
        monkeypatch.setenv("CLAWD_DATA_DIR", str(data))
        assert data_dir_mod.data_dir() == data
        assert data_dir_mod.data_dir("/some/other") == data

    def test_workdir_fallback(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        assert data_dir_mod.data_dir(tmp_path) == tmp_path / ".clawd"
        assert data_dir_mod.data_dir() == Path.cwd() / ".clawd"

    def test_create_flags(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        data = tmp_path / "userdata"
        monkeypatch.setenv("CLAWD_DATA_DIR", str(data))
        assert data_dir_mod.data_path("sessions", create_dir=True).is_dir()
        assert data_dir_mod.data_dir(create=True).is_dir()

    def test_describe_keeps_data_dir_key(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """`src/server/websocket_server.py` 直接读 describe()["data_dir"]，键不能少。"""
        data = tmp_path / "userdata"
        monkeypatch.setenv("CLAWD_DATA_DIR", str(data))
        info = data_dir_mod.describe()
        assert info["data_dir"] == str(data)
        assert all(isinstance(value, str) for value in info.values())
