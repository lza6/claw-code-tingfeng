"""项目（工作区）列表 —— 抄参考客户端的"项目"概念：一个项目 = 一个文件夹

为什么要这个：用户的真实工作方式是"多个仓库来回切换"。之前只有一个隐式 cwd，
切项目只能重启 Host。现在：
- 项目列表存 `<数据目录>/projects.json`（JSON，可读可手改）；
- 选中项目后，新会话的**工作目录**就是它（Host 把 workdir 传给引擎）；
- 每个项目单独记会话目录的命名空间，侧栏按项目分组显示历史。

字段：{"active": "<id>", "projects": {"<id>": {"name", "path", "added_at"}}}
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time

from pathlib import Path
from typing import Any

from . import data_dir as data_dir_mod

logger = logging.getLogger(__name__)
FILE_NAME = "projects.json"


def _path() -> Path:
    return data_dir_mod.data_path(FILE_NAME)


def _load() -> dict[str, Any]:
    path = _path()
    if not path.is_file():
        return {"active": "", "projects": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"projects.json 读取失败（按空处理）: {e}")
        return {"active": "", "projects": {}}
    if not isinstance(data, dict):
        return {"active": "", "projects": {}}
    data.setdefault("active", "")
    data.setdefault("projects", {})
    return data


def _save(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _project_id(path: Path) -> str:
    digest = hashlib.sha256(str(path).lower().encode("utf-8")).hexdigest()[:10]
    return f"p-{digest}"


def list_projects() -> list[dict[str, Any]]:
    data = _load()
    active = str(data.get("active") or "")
    items = []
    for pid, raw in (data.get("projects") or {}).items():
        path = str(raw.get("path") or "")
        items.append({
            "id": pid,
            "name": raw.get("name") or Path(path).name or pid,
            "path": path,
            "exists": bool(path) and Path(path).is_dir(),
            "is_active": pid == active,
            "added_at": float(raw.get("added_at") or 0.0),
        })
    items.sort(key=lambda item: (not item["is_active"], -item["added_at"]))
    return items


def add_project(path: str, name: str = "") -> dict[str, Any]:
    target = Path(str(path)).expanduser()
    if not target.is_dir():
        raise ValueError(f"目录不存在: {target}")
    resolved = target.resolve()
    data = _load()
    pid = _project_id(resolved)
    projects = data.setdefault("projects", {})
    projects[pid] = {
        "name": (name or resolved.name or str(resolved))[:80],
        "path": str(resolved),
        "added_at": time.time(),
    }
    if not data.get("active"):
        data["active"] = pid
    _save(data)
    return {"id": pid, **projects[pid], "is_active": data.get("active") == pid, "exists": True}


def remove_project(project_id: str) -> bool:
    data = _load()
    projects = data.get("projects") or {}
    if project_id not in projects:
        return False
    projects.pop(project_id, None)
    if data.get("active") == project_id:
        remaining = sorted(projects.items(), key=lambda kv: -float(kv[1].get("added_at") or 0))
        data["active"] = remaining[0][0] if remaining else ""
    _save(data)
    return True


def set_active(project_id: str) -> bool:
    data = _load()
    if project_id not in (data.get("projects") or {}):
        return False
    data["active"] = project_id
    _save(data)
    return True


def active_project() -> dict[str, Any] | None:
    data = _load()
    pid = str(data.get("active") or "")
    raw = (data.get("projects") or {}).get(pid)
    if not raw:
        return None
    return {"id": pid, "name": raw.get("name"), "path": raw.get("path"), "exists": Path(str(raw.get("path"))).is_dir()}


def active_workdir(fallback: Path | str | None = None) -> Path:
    """新会话应该用的工作目录：优先选中的项目，其次 fallback/cwd"""
    project = active_project()
    if project and project.get("exists"):
        return Path(str(project["path"]))
    return Path(fallback) if fallback else Path.cwd()


__all__ = [
    "active_project",
    "active_workdir",
    "add_project",
    "list_projects",
    "remove_project",
    "set_active",
]
