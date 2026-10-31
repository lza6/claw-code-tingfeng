"""状态目录迁移（`clawd migrate-state` 的实现体）

场景：老用户的运行期数据还躺在**仓库目录**的 `.clawd/` 里（历史默认行为），
现在要把状态根固定到 `CLAWD_DATA_DIR` / `CLAWD_HOME`（例如 `~/.clawd` 或桌面端 userData）。
搬迁必须是**可重复、可中断、不丢数据**的，否则用户丢的是会话和 provider 配置。

四条硬规则（对应审计项 X-9）：
1. **幂等**：第二次运行 `moved == 0`（同内容文件一律 `skipped`）；
2. **不静默覆盖**：目标已存在同路径但内容不同 → 记 `conflict`，源文件原地不动；
3. **先校验再删源**：先拷贝，再核对字节数与 sha256，全部一致才删源；任何一步失败都保留源文件；
4. **失败不静默**：单条失败写入结果的 `failed` + `errors`，其余条目照常处理，不中断整批。

只依赖标准库，返回结构化 dict（CLI `--json` 直接可输出）。
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from .data_dir import STATE_LAYOUT_NAME, STATE_LAYOUT_VERSION

#: 单条状态：需要搬过去
STATUS_NEW = "new"
#: 单条状态：目标已有完全相同内容
STATUS_IDENTICAL = "identical"
#: 单条状态：目标已有同路径但内容/类型不同
STATUS_CONFLICT = "conflict"
#: 单条状态：结果计数键
STATUS_MOVED = "moved"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

_CHUNK = 256 * 1024


class StateMigrationError(ValueError):
    """迁移参数非法（源/目标根目录不存在、相同、或互为父子）。"""


def _validate_roots(src_root: Path | str, dst_root: Path | str) -> tuple[Path, Path]:
    """规范化并校验两个根目录；不合法就抛 `StateMigrationError`。"""
    src = Path(src_root).expanduser().resolve()
    dst = Path(dst_root).expanduser().resolve()
    if src == dst:
        raise StateMigrationError(f"源目录与目标目录相同，无需迁移：{src}")
    if dst.is_relative_to(src):
        raise StateMigrationError(f"目标目录位于源目录内部（会把数据搬进自己）：{dst}")
    if src.is_relative_to(dst):
        raise StateMigrationError(f"源目录位于目标目录内部（会把已有数据当成待迁移数据）：{src}")
    if not src.is_dir():
        raise StateMigrationError(f"源状态目录不存在或不是目录：{src}")
    return src, dst


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_content(left: Path, right: Path) -> bool:
    """大小 + sha256 双重比对；任何 IO 错误都视作"不同"（保守，宁可报冲突不覆盖）。"""
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
        return _sha256(left) == _sha256(right)
    except OSError:
        return False


def _entry(rel: Path, *, kind: str, status: str, size: int = 0, reason: str = "") -> dict:
    item = {
        "rel": rel.as_posix(),
        "kind": kind,
        "size": size,
        "status": status,
    }
    if reason:
        item["reason"] = reason
    return item


def _classify_file(src_file: Path, dst_file: Path) -> tuple[str, str]:
    if not dst_file.exists() and not dst_file.is_symlink():
        return STATUS_NEW, ""
    if dst_file.is_dir():
        return STATUS_CONFLICT, "目标同路径是目录，无法覆盖为文件"
    if _same_content(src_file, dst_file):
        return STATUS_IDENTICAL, "目标已有相同内容"
    return STATUS_CONFLICT, "目标已存在且内容不同（不覆盖）"


def _classify_dir(dst_dir: Path) -> tuple[str, str]:
    if not dst_dir.exists() and not dst_dir.is_symlink():
        return STATUS_NEW, ""
    if dst_dir.is_file():
        return STATUS_CONFLICT, "目标同路径是文件，无法建目录"
    return STATUS_IDENTICAL, "目标目录已存在"


def _scan(src: Path, dst: Path) -> list[dict]:
    """遍历源目录，为每个条目分类（不写任何文件）。"""
    entries: list[dict] = []
    for root, dirnames, filenames in os.walk(src, followlinks=False):
        root_path = Path(root)
        keep: list[str] = []
        for name in sorted(dirnames):
            child = root_path / name
            rel = child.relative_to(src)
            if child.is_symlink():
                # 符号链接可能指向源目录之外，静默跟随会搬出意料之外的东西 → 显式跳过
                entries.append(_entry(rel, kind="symlink", status=STATUS_IDENTICAL,
                                      reason="符号链接目录不迁移，请手工处理"))
                continue
            keep.append(name)
            status, reason = _classify_dir(dst / rel)
            entries.append(_entry(rel, kind="dir", status=status, reason=reason))
        dirnames[:] = keep
        for name in sorted(filenames):
            child = root_path / name
            rel = child.relative_to(src)
            if child.is_symlink():
                entries.append(_entry(rel, kind="symlink", status=STATUS_IDENTICAL,
                                      reason="符号链接不迁移，请手工处理"))
                continue
            try:
                size = child.stat().st_size
            except OSError as exc:
                entries.append(_entry(rel, kind="file", status=STATUS_CONFLICT,
                                      reason=f"无法读取源文件属性：{exc}"))
                continue
            status, reason = _classify_file(child, dst / rel)
            entries.append(_entry(rel, kind="file", status=status, size=size, reason=reason))
    return entries


def _summarize(entries: list[dict]) -> dict:
    files = [e for e in entries if e["kind"] == "file"]
    conflicts = [e["rel"] for e in entries if e["status"] == STATUS_CONFLICT]
    identical = [e["rel"] for e in entries if e["status"] == STATUS_IDENTICAL]
    pending = [e["rel"] for e in entries if e["status"] == STATUS_NEW]
    return {
        "total_entries": len(entries),
        "total_files": len(files),
        "total_dirs": sum(1 for e in entries if e["kind"] == "dir"),
        # total_bytes = 还需搬运的字节（新条目）；total_source_bytes = 源目录全部文件字节
        "total_bytes": sum(int(e["size"]) for e in files if e["status"] == STATUS_NEW),
        "total_source_bytes": sum(int(e["size"]) for e in files),
        "pending_count": len(pending),
        "conflict_count": len(conflicts),
        "identical_count": len(identical),
        "conflicts": conflicts,
        "identical": identical,
        "pending": pending,
    }


def plan_migration(src_root: Path | str, dst_root: Path | str) -> dict:
    """列出迁移计划（只读，不动任何文件）。

    返回：`src_root`/`dst_root`（绝对路径）/`layout`/`total_entries`/`total_files`/
    `total_dirs`/`total_bytes`（**待搬运**的字节数）/`total_source_bytes`（源目录全部文件字节）/
    `conflict_count`/`conflicts`/`identical_count`/`identical`/`pending_count`/`pending`/`entries`。
    """
    src, dst = _validate_roots(src_root, dst_root)
    entries = _scan(src, dst)
    return {
        "ok": True,
        "src_root": str(src),
        "dst_root": str(dst),
        "layout": STATE_LAYOUT_NAME,
        "layout_version": STATE_LAYOUT_VERSION,
        **_summarize(entries),
        "entries": entries,
    }


def _move_file(src_file: Path, dst_file: Path) -> str:
    """拷贝 → 校验（大小 + sha256）→ 删源；返回附加说明。校验失败抛 `OSError` 且保留源文件。

    不直接 `os.replace`：跨盘会失败，而且"先删/替换再校验"一旦发现内容不对，源已经没了。
    统一走"拷贝-校验-删源"，只有一条代码路径，正确性优先于省一次 IO。
    """
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    expected = src_file.stat().st_size
    overwrote = dst_file.exists()
    shutil.copy2(src_file, dst_file)
    try:
        actual = dst_file.stat().st_size
        if actual != expected:
            raise OSError(f"拷贝后大小不一致：源 {expected} 字节 / 目标 {actual} 字节")
        if _sha256(src_file) != _sha256(dst_file):
            raise OSError("拷贝后内容摘要不一致（源文件可能在迁移期间被改动）")
    except OSError:
        # 半成品要清掉，否则下次运行会被误判成"目标已存在且内容不同"
        try:
            dst_file.unlink(missing_ok=True)
        except OSError as cleanup_exc:
            raise OSError(f"校验失败且清理半成品失败：{cleanup_exc}") from cleanup_exc
        raise
    src_file.unlink()
    return "已覆盖目标同名文件" if overwrote else ""


def _prune_empty_dirs(src_root: Path) -> int:
    """自底向上删掉搬空的源目录（保留 `src_root` 本身），返回删除个数。"""
    removed = 0
    for root, dirnames, filenames in os.walk(src_root, topdown=False, followlinks=False):
        path = Path(root)
        if path == src_root:
            continue
        if dirnames or filenames:
            continue
        try:
            path.rmdir()
            removed += 1
        except OSError:
            # 目录非空/被占用：留着无妨，下次运行还会尝试
            continue
    return removed


def migrate_state(
    src_root: Path | str,
    dst_root: Path | str,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict:
    """把状态目录从 `src_root` 搬到 `dst_root`。

    - `dry_run=True`：只返回计划，不动任何文件（`moved/skipped/failed` 全为 0）。
    - `overwrite=False`（默认）：目标已有同路径不同内容的文件 → 记 `conflict`，源文件保留。
    - 幂等：第二次运行 `moved == 0`，全部为 `skipped`。

    返回 dict 含 `ok`/`src_root`/`dst_root`/`dry_run`/`overwrite`/`layout`/
    `moved`/`skipped`/`conflict`/`failed`/`moved_bytes`/`pruned_dirs`/`errors`/`entries`。
    """
    src, dst = _validate_roots(src_root, dst_root)
    entries = _scan(src, dst)
    summary = _summarize(entries)

    if dry_run:
        for item in entries:
            item["action"] = "move" if item["status"] == STATUS_NEW else "skip"
            if item["status"] == STATUS_CONFLICT:
                item["action"] = "conflict"
        if overwrite:
            for item in entries:
                if item["status"] == STATUS_CONFLICT:
                    item["action"] = "move"
        return {
            "ok": True,
            **summary,
            "src_root": str(src),
            "dst_root": str(dst),
            "layout": STATE_LAYOUT_NAME,
            "dry_run": True,
            "overwrite": overwrite,
            "moved": 0,
            "skipped": 0,
            "conflict": summary["conflict_count"],
            "failed": 0,
            "moved_bytes": 0,
            "pruned_dirs": 0,
            "errors": [],
            "entries": entries,
        }

    counts = {STATUS_MOVED: 0, STATUS_SKIPPED: 0, STATUS_CONFLICT: 0, STATUS_FAILED: 0}
    errors: list[str] = []
    moved_bytes = 0
    dst.mkdir(parents=True, exist_ok=True)

    def _record(item: dict, status: str, reason: str = "") -> None:
        counts[status] += 1
        item["status"] = status
        if reason:
            item["reason"] = reason
        if status == STATUS_FAILED:
            errors.append(f"{item['rel']}: {reason}")

    # 先建目录（浅的在前），否则文件落盘时会重复 mkdir
    for item in sorted((e for e in entries if e["kind"] == "dir"), key=lambda e: len(e["rel"])):
        target = dst / item["rel"]
        if item["status"] == STATUS_NEW:
            try:
                target.mkdir(parents=True, exist_ok=True)
                _record(item, STATUS_MOVED)
            except OSError as exc:
                _record(item, STATUS_FAILED, f"创建目录失败：{exc}")
        elif item["status"] == STATUS_CONFLICT:
            _record(item, STATUS_CONFLICT, item.get("reason", "目标路径冲突"))
        else:
            _record(item, STATUS_SKIPPED, item.get("reason", "目标目录已存在"))

    # 再搬文件
    for item in entries:
        if item["kind"] == "symlink":
            # 计数里也要出现，别让符号链接凭空从结果中消失
            _record(item, STATUS_SKIPPED, item.get("reason", "符号链接不迁移"))
            continue
        if item["kind"] != "file":
            continue
        src_file = src / item["rel"]
        dst_file = dst / item["rel"]
        if item["status"] == STATUS_IDENTICAL:
            _record(item, STATUS_SKIPPED, item.get("reason", "目标已有相同内容"))
            continue
        if item["status"] == STATUS_CONFLICT and not overwrite:
            _record(item, STATUS_CONFLICT, item.get("reason", "目标已存在且内容不同（不覆盖）"))
            continue
        try:
            note = _move_file(src_file, dst_file)
            moved_bytes += int(item["size"])
            _record(item, STATUS_MOVED, note)
        except OSError as exc:
            _record(item, STATUS_FAILED, str(exc))

    pruned = _prune_empty_dirs(src)

    return {
        "ok": counts[STATUS_FAILED] == 0,
        **summary,
        "src_root": str(src),
        "dst_root": str(dst),
        "layout": STATE_LAYOUT_NAME,
        "dry_run": False,
        "overwrite": overwrite,
        "moved": counts[STATUS_MOVED],
        "skipped": counts[STATUS_SKIPPED],
        "conflict": counts[STATUS_CONFLICT],
        "failed": counts[STATUS_FAILED],
        "moved_bytes": moved_bytes,
        "pruned_dirs": pruned,
        "errors": errors,
        "entries": entries,
    }


__all__ = [
    "StateMigrationError",
    "migrate_state",
    "plan_migration",
]
