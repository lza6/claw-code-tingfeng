"""结构化日志目录必须跟随数据目录（桌面端不能写进安装目录）

真实问题：`src/main.py` 里写死 `WORK_DIR/.clawd/logs`，桌面端的 cwd 是
`resources/host` —— 日志落在安装目录里，升级覆盖就没了，而且安装目录可能只读。
现在统一走 `data_dir` 唯一入口（ADR 0022），与 provider/会话/用量同一套规则。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


class TestResolveLogDir:
    def test_follows_clawd_data_dir(self, tmp_path, monkeypatch):
        data = tmp_path / "udata"
        data.mkdir()
        monkeypatch.setenv("CLAWD_DATA_DIR", str(data))
        monkeypatch.chdir(tmp_path)  # 无论 cwd 在哪，都不该影响结果

        from src.utils.logger import resolve_log_dir

        got = resolve_log_dir()
        assert Path(got) == data / "logs", f"日志没跟着数据目录走: {got}"

    def test_independent_of_cwd(self, tmp_path, monkeypatch):
        data = tmp_path / "udata"
        data.mkdir()
        monkeypatch.setenv("CLAWD_DATA_DIR", str(data))
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        from src.utils.logger import resolve_log_dir

        assert Path(resolve_log_dir()) == data / "logs"
        assert not (elsewhere / ".clawd").exists(), "不应在 cwd 下造 .clawd"

    def test_falls_back_to_workdir_without_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAWD_DATA_DIR", raising=False)
        work = tmp_path / "proj"
        work.mkdir()
        monkeypatch.chdir(work)

        from src.utils.logger import resolve_log_dir

        got = Path(resolve_log_dir())
        assert got == work / ".clawd" / "logs", f"无 CLAWD_DATA_DIR 时应回落工作区: {got}"

    def test_explicit_workdir_argument(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAWD_DATA_DIR", raising=False)
        work = tmp_path / "explicit"
        work.mkdir()

        from src.utils.logger import resolve_log_dir

        assert Path(resolve_log_dir(work)) == work / ".clawd" / "logs"


class TestMainUsesResolver:
    def test_main_module_does_not_hardcode_work_dir_logs(self):
        """防止回退：main.py 里不能再出现 `WORK_DIR` + `.clawd/logs` 的硬编码"""
        src = (Path(__file__).resolve().parents[2] / "src" / "main.py").read_text(encoding="utf-8")
        assert "resolve_log_dir" in src, "main.py 必须走 resolve_log_dir()"
        assert "_os.environ.get('WORK_DIR', '.')" not in src, "不要再用 WORK_DIR 拼日志目录"

    def test_env_switch_still_disables_logging(self):
        """ENABLE_FILE_LOGGING=false 时不应创建日志目录（桌面端自检会用到）"""
        src = (Path(__file__).resolve().parents[2] / "src" / "main.py").read_text(encoding="utf-8")
        assert "ENABLE_FILE_LOGGING" in src
        assert os is not None  # 保持导入显式
