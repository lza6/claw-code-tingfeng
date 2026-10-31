"""运行期数据目录（`.clawd`）的唯一解析入口

为什么要单独一个模块（真实事故）：
    桌面端把 Host 的 cwd 设成安装目录 `resources/host`，于是 `.clawd/` 也落在**安装目录**里。
    一升级/重装，安装目录被覆盖 → 用户的 provider 配置、用量、会话**全丢**。
    修法：数据目录必须与"程序目录"分离。

解析顺序（严格按此优先级，命中即停）：
1. 环境变量 `CLAWD_DATA_DIR`（桌面端由 Electron 设成 `app.getPath('userData')/data`）；
2. 环境变量 `CLAWD_HOME`（`CLAWD_DATA_DIR` 的别名，便于 `CLAWD_HOME=/tmp/x` 一行重定向）；
3. 否则 `<workdir>/.clawd`（CLI 默认，保持向后兼容）。

两个变量同时设置时 **`CLAWD_DATA_DIR` 优先**，`describe()` 会如实标出实际生效的是哪个变量
（另一个记在 `ignored_env`），避免"我设了 env 却没生效"这种查不出来的事。

状态布局版本：
    状态目录里放 `state.json`（`{"version": N, "created_at": ISO, "layout": "clawd-state/v1"}`），
    用来标记这份落盘数据的布局版本。当前为 `STATE_LAYOUT_VERSION = 1`。
    读到**更高**版本时抛 `StateVersionError`（中文说明）—— 绝不静默按旧布局继续读写，
    否则新版本写的字段会被老程序覆盖掉，属于不可逆的数据损坏。

约定：**代码里不要再手写 `Path('.clawd')`**，一律走 `data_dir()` / `data_path(...)`。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

#: 主环境变量（优先级最高）
ENV_VAR = "CLAWD_DATA_DIR"
#: 别名环境变量（`CLAWD_DATA_DIR` 未设时才生效）
ENV_VAR_ALIAS = "CLAWD_HOME"
#: 状态目录布局版本号；不兼容地改动落盘结构时 +1
STATE_LAYOUT_VERSION = 1
#: 布局标识，写进 `state.json`，人工排查时一眼能看出是哪个布局
STATE_LAYOUT_NAME = "clawd-state/v1"
#: 布局描述文件名（位于数据目录根部）
STATE_FILE_NAME = "state.json"


class StateVersionError(RuntimeError):
    """状态目录的布局版本不受支持（通常是更新版本的程序写的数据）。

    继承 `RuntimeError` 而不是 `ValueError`：这是运行环境不兼容，不是调用参数写错。
    """


def _env_value(name: str) -> str:
    """读取环境变量并去掉首尾空白；空串视作未设置。"""
    return (os.environ.get(name) or "").strip()


def _resolve(workdir: Path | str | None = None) -> tuple[Path, str]:
    """解析数据目录并返回 `(路径, 生效来源)`；来源取值见 `describe()` 的 `source`。"""
    primary = _env_value(ENV_VAR)
    if primary:
        return Path(primary).expanduser(), ENV_VAR
    alias = _env_value(ENV_VAR_ALIAS)
    if alias:
        return Path(alias).expanduser(), ENV_VAR_ALIAS
    base = Path(workdir) / ".clawd" if workdir else Path.cwd() / ".clawd"
    return base, "workdir/.clawd"


def data_dir(workdir: Path | str | None = None, *, create: bool = False) -> Path:
    """返回运行期数据目录（不自动创建，除非 create=True）"""
    base, _source = _resolve(workdir)
    if create:
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(f"创建数据目录失败 {base}: {e}")
    return base


def data_path(*parts: str, workdir: Path | str | None = None, create_dir: bool = False) -> Path:
    """拼一个数据文件路径，例如 data_path('sessions', create_dir=True)"""
    base = data_dir(workdir)
    target = base.joinpath(*parts)
    if create_dir:
        try:
            (target if not target.suffix else target.parent).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(f"创建数据子目录失败 {target}: {e}")
    return target


def state_file(workdir: Path | str | None = None) -> Path:
    """状态目录里的布局描述文件路径（不创建）。"""
    return data_dir(workdir) / STATE_FILE_NAME


def _read_state(path: Path) -> dict:
    """读取并校验 `state.json`；损坏或版本过高时抛 `StateVersionError`（中文说明）。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise StateVersionError(f"无法读取状态文件 {path}：{e}。请检查文件权限。") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise StateVersionError(
            f"状态文件已损坏，无法解析：{path}（{e}）。请修复该文件，或把它移走让程序重新生成。"
        ) from e
    if not isinstance(data, dict):
        raise StateVersionError(f"状态文件内容不是 JSON 对象：{path}。请修复或移走该文件。")

    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise StateVersionError(f"状态文件缺少合法的 version 字段：{path}（实际：{version!r}）。")
    if version > STATE_LAYOUT_VERSION:
        raise StateVersionError(
            f"状态目录布局版本 {version} 高于当前程序支持的版本 {STATE_LAYOUT_VERSION}：{path}。"
            f"这通常是用更新版本的 Clawd Code 生成的数据；请升级程序，"
            f"或改用另一个 {ENV_VAR} / {ENV_VAR_ALIAS} 目录，不要用旧程序覆盖它。"
        )
    return data


def _atomic_write_json(path: Path, payload: dict) -> None:
    """原子写 JSON（同目录临时文件 + fsync + os.replace），UTF-8，末尾换行。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        # 写失败不留半成品（不吞异常，照原样往上抛）
        tmp.unlink(missing_ok=True)
        raise


def state_version(workdir: Path | str | None = None) -> int:
    """返回状态目录布局版本；`state.json` 不存在时返回 0（表示"还没有状态布局"）。

    版本高于当前程序支持的上限时抛 `StateVersionError`，不返回假值。
    """
    path = state_file(workdir)
    if not path.is_file():
        return 0
    return int(_read_state(path)["version"])


def ensure_state_dir(create: bool = True) -> Path:
    """确保状态目录可用并写入 `state.json`，返回状态目录路径。

    - `create=True`（默认）：目录不存在就建；`state.json` 不存在就原子写入
      `{"version": STATE_LAYOUT_VERSION, "created_at": <首次创建时间>, "layout": STATE_LAYOUT_NAME}`。
    - `create=False`：只做校验，不建目录、不写文件。
    - **幂等**：已存在 `state.json` 时不重写，`created_at` 保持不变。
    - 布局版本高于 `STATE_LAYOUT_VERSION` 时抛 `StateVersionError`（不静默继续）。
    """
    base = data_dir()
    path = base / STATE_FILE_NAME
    if path.is_file():
        _read_state(path)  # 版本过高 / 内容损坏 → 在这里抛
        return base
    if not create:
        return base
    base.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STATE_LAYOUT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "layout": STATE_LAYOUT_NAME,
    }
    _atomic_write_json(path, payload)
    return base


def describe() -> dict[str, str]:
    """给 /api/info、设置页用的可读说明（不含敏感信息）"""
    base, source = _resolve()
    info = {
        "data_dir": str(base),
        "source": source,
        "state_file": str(base / STATE_FILE_NAME),
        "layout": STATE_LAYOUT_NAME,
        "layout_version": str(STATE_LAYOUT_VERSION),
        "precedence": f"{ENV_VAR} > {ENV_VAR_ALIAS} > workdir/.clawd",
    }
    if source == ENV_VAR and _env_value(ENV_VAR_ALIAS):
        # 别名也设了但没生效：明说，省得排查半天
        info["ignored_env"] = ENV_VAR_ALIAS
    return info


__all__ = [
    "ENV_VAR",
    "ENV_VAR_ALIAS",
    "STATE_FILE_NAME",
    "STATE_LAYOUT_NAME",
    "STATE_LAYOUT_VERSION",
    "StateVersionError",
    "data_dir",
    "data_path",
    "describe",
    "ensure_state_dir",
    "state_file",
    "state_version",
]
