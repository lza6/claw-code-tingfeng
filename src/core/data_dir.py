"""运行期数据目录（`.clawd`）的唯一解析入口

为什么要单独一个模块（真实事故）：
    桌面端把 Host 的 cwd 设成安装目录 `resources/host`，于是 `.clawd/` 也落在**安装目录**里。
    一升级/重装，安装目录被覆盖 → 用户的 provider 配置、用量、会话**全丢**。
    修法：数据目录必须与"程序目录"分离。

解析顺序：
1. 环境变量 `CLAWD_DATA_DIR`（桌面端由 Electron 设成 `app.getPath('userData')/data`）；
2. 否则 `<workdir>/.clawd`（CLI 默认，保持向后兼容）。

约定：**代码里不要再手写 `Path('.clawd')`**，一律走 `data_dir()` / `data_path(...)`。
"""
from __future__ import annotations

import logging
import os

from pathlib import Path

logger = logging.getLogger(__name__)

ENV_VAR = "CLAWD_DATA_DIR"


def data_dir(workdir: Path | str | None = None, *, create: bool = False) -> Path:
    """返回运行期数据目录（不自动创建，除非 create=True）"""
    env_value = (os.environ.get(ENV_VAR) or "").strip()
    if env_value:
        base = Path(env_value).expanduser()
    else:
        base = Path(workdir) / ".clawd" if workdir else Path.cwd() / ".clawd"
    if create:
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as e:  # pragma: no cover - 极端权限问题
            logger.warning(f"创建数据目录失败 {base}: {e}")
    return base


def data_path(*parts: str, workdir: Path | str | None = None, create_dir: bool = False) -> Path:
    """拼一个数据文件路径，例如 data_path('sessions', create_dir=True)"""
    base = data_dir(workdir)
    target = base.joinpath(*parts)
    if create_dir:
        try:
            (target if not target.suffix else target.parent).mkdir(parents=True, exist_ok=True)
        except OSError as e:  # pragma: no cover
            logger.warning(f"创建数据子目录失败 {target}: {e}")
    return target


def describe() -> dict[str, str]:
    """给 /api/info、设置页用的可读说明（不含敏感信息）"""
    return {"data_dir": str(data_dir()), "source": ENV_VAR if os.environ.get(ENV_VAR) else "workdir/.clawd"}


__all__ = ["ENV_VAR", "data_dir", "data_path", "describe"]
