"""SQLite 存储健康自检（`clawd doctor --deep` 的结构化数据源）

为什么需要它：
    Agent 的运行期状态几乎全在 SQLite 里（用量、会话、记忆、经验、durable surfaces）。
    这些库一旦**静默损坏**（断电写坏页、磁盘满、进程被 kill 在提交中途），
    表层症状是"历史记录变少了""用量对不上""记忆检索不到"，
    而不是一个能立刻定位的异常 —— 排查成本极高。
    所以需要一个可以随时跑、**只读、不会把库改坏**的自检入口。

三条硬约束（写这个模块时逐条守住的）：
1. **只读打开**：一律 `file:...?mode=ro`，绝不对生产库做任何写操作；
   `mode=ro` 打不开时（缺 `-shm` 且目录不可写）退回 `immutable=1`，
   并在 `issues` 里 `info` 记一笔 —— 不许静默降级。
2. **单库失败不中断整体**：一个库损坏/被占用/没权限，只影响它自己那几条 issue，
   其余库照常体检。整体绝不抛异常。
3. **不静默吞异常**：每个 `except` 都 `logger.warning` 并落到 `issues`。

输出面向两种读者：人读（`zh_message` / `recommendations` 全中文可行动），
机器读（`severity` / `kind` / 数值字段稳定）。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from .data_dir import data_dir

logger = logging.getLogger(__name__)

#: 认作 SQLite 库的扩展名（用户/第三方工具常见的三种写法）
DB_SUFFIXES: tuple[str, ...] = ('.db', '.sqlite', '.sqlite3')

DEFAULT_TOP_N = 10
DEFAULT_TIMEOUT_S = 5.0

#: 可回收空间占文件比例超过该阈值 → 建议 VACUUM。
#: 20% 是经验值：低于此 VACUUM 的写放大与耗时换不回多少空间。
FRAGMENT_WARN_RATIO = 0.20


# --------------------------------------------------------------------------- #
# 纯函数（无 IO，测试可直接断言分支）
# --------------------------------------------------------------------------- #
def reclaimable_bytes(freelist_count: int, page_size: int) -> int:
    """空闲页 × 页大小 = VACUUM 理论上能还给文件系统的字节数"""
    if freelist_count <= 0 or page_size <= 0:
        return 0
    return int(freelist_count) * int(page_size)


def should_vacuum(size_bytes: int, freelist_count: int, page_size: int) -> bool:
    """可回收空间是否值得一次 VACUUM（> FRAGMENT_WARN_RATIO 才建议）"""
    if size_bytes <= 0:
        return False
    ratio = reclaimable_bytes(freelist_count, page_size) / float(size_bytes)
    return ratio > FRAGMENT_WARN_RATIO


def _quote_ident(name: str) -> str:
    """SQL 标识符转义：表名可能含空格/引号/中文，必须走双引号转义"""
    return '"' + name.replace('"', '""') + '"'


def _issue(severity: str, path: Path, kind: str, zh_message: str, suggestion: str) -> dict[str, Any]:
    """统一 issue 结构（severity 只允许 fail/warn/info）"""
    return {
        'severity': severity,
        'path': str(path),
        'kind': kind,
        'zh_message': zh_message,
        'suggestion': suggestion,
    }


def _classify_error(err: BaseException) -> tuple[str, str, str]:
    """把 sqlite3/OSError 归类成 (severity, kind, 中文处置建议)"""
    text = str(err).lower()
    if isinstance(err, PermissionError) or 'permission denied' in text or 'access is denied' in text:
        return 'fail', 'permission', '检查文件/目录 ACL，或用有权限的账户重跑诊断'
    if 'locked' in text or 'busy' in text:
        return 'fail', 'locked', '库被占用：退出正在写入该库的 clawd 进程后重新诊断'
    if isinstance(err, sqlite3.DatabaseError) and (
        'not a database' in text or 'malformed' in text or 'encrypted' in text
    ):
        return 'fail', 'corrupt', '备份该文件后从副本恢复；这不是 SQLite 库或文件头已损坏'
    if isinstance(err, sqlite3.Error):
        return 'fail', 'sqlite_error', '记录完整报错并交由维护流程处理，不要直接删除该库'
    return 'fail', 'os_error', '检查磁盘是否可读、文件是否已被删除'


# --------------------------------------------------------------------------- #
# 发现
# --------------------------------------------------------------------------- #
def _iter_db_files(root: Path) -> list[Path]:
    """递归找库文件。目录不可读时记 warning 并继续（不因为一个子目录放弃整棵树）"""

    def _on_error(err: OSError) -> None:
        logger.warning(f'扫描数据目录失败，跳过 {getattr(err, "filename", root)}: {err}')

    found: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root, onerror=_on_error):
        for name in filenames:
            if name.lower().endswith(DB_SUFFIXES):
                found.append(Path(dirpath) / name)
    return sorted(found)


def _open_readonly(path: Path, timeout_s: float) -> tuple[sqlite3.Connection, bool]:
    """只读打开。返回 (连接, 是否用了 immutable 降级)

    `immutable=1` 只在 `mode=ro` 打不开时用：WAL 库需要 `-shm`，
    目录不可写时 SQLite 拒绝建它。降级会让调用方拿到瞬时快照，
    因此由调用方记一条 `info` issue，不做静默处理。
    """
    timeout = max(0.0, float(timeout_s))
    uri = path.resolve().as_uri() + '?mode=ro'
    try:
        return sqlite3.connect(uri, uri=True, timeout=timeout), False
    except sqlite3.OperationalError as e:
        logger.warning(f'只读打开 {path} 失败（{e}），回退 immutable=1')
        uri_immutable = uri + '&immutable=1'
        return sqlite3.connect(uri_immutable, uri=True, timeout=timeout), True


# --------------------------------------------------------------------------- #
# 单库检查
# --------------------------------------------------------------------------- #
def _collect_integrity(conn: sqlite3.Connection, path: Path, record: dict[str, Any],
                       issues: list[dict[str, Any]]) -> bool:
    """`PRAGMA integrity_check`。返回 False 表示库已不可用，后续检查应跳过"""
    try:
        row = conn.execute('PRAGMA integrity_check').fetchone()
        record['integrity'] = str(row[0]) if row else 'unknown'
    except (sqlite3.Error, OSError) as e:
        logger.warning(f'完整性检查失败 {path}: {e}')
        record['integrity'] = f'error: {e}'
        record['errors'].append(f'integrity_check: {e}')
        severity, kind, hint = _classify_error(e)
        issues.append(_issue(severity, path, kind, f'完整性检查无法执行：{e}', hint))
        return False

    record['integrity_ok'] = record['integrity'].strip().lower() == 'ok'
    if not record['integrity_ok']:
        detail = record['integrity'].strip() or '（空结果）'
        if 'index' in detail.lower():
            suggestion = '先尝试 REINDEX 重建索引；无效则备份后从副本恢复'
        else:
            suggestion = '立即备份该文件，从最近可用副本恢复；继续读写会扩大损坏面'
        issues.append(_issue(
            'fail', path, 'corrupt',
            f'完整性检查未通过：{detail[:300]}',
            suggestion,
        ))
        return False
    return True


def _collect_pragmas(conn: sqlite3.Connection, path: Path, record: dict[str, Any],
                     issues: list[dict[str, Any]]) -> None:
    """页统计 → 可回收空间 → 碎片建议"""
    for key, pragma in (('page_count', 'PRAGMA page_count'),
                        ('page_size', 'PRAGMA page_size'),
                        ('freelist_count', 'PRAGMA freelist_count')):
        try:
            row = conn.execute(pragma).fetchone()
            record[key] = int(row[0]) if row and row[0] is not None else 0
        except (sqlite3.Error, OSError, TypeError, ValueError) as e:
            logger.warning(f'{pragma} 读取失败 {path}: {e}')
            record['errors'].append(f'{pragma}: {e}')

    reclaimable = reclaimable_bytes(record['freelist_count'], record['page_size'])
    record['reclaimable_bytes'] = reclaimable
    if should_vacuum(record['size_bytes'], record['freelist_count'], record['page_size']):
        pct = reclaimable * 100.0 / record['size_bytes']
        issues.append(_issue(
            'warn', path, 'fragmented',
            f'空洞页 {record["freelist_count"]} 个，可回收 {reclaimable} 字节（占文件 {pct:.1f}%）',
            '执行 `VACUUM` 回收空洞空间（需先停止对该库的写入）',
        ))


def _collect_tables(conn: sqlite3.Connection, path: Path, record: dict[str, Any],
                    issues: list[dict[str, Any]]) -> None:
    """表清单 + 每表行数。单表失败只记该表的 error，不中断"""
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    except (sqlite3.Error, OSError) as e:
        logger.warning(f'读取表清单失败 {path}: {e}')
        record['errors'].append(f'sqlite_master: {e}')
        issues.append(_issue('fail', path, 'sqlite_error',
                             f'无法读取表清单：{e}',
                             '先用 `sqlite3 <库> .tables` 人工确认，再决定修复或恢复'))
        return

    total = 0
    for row in rows:
        name = str(row[0])
        if name.startswith('sqlite_'):        # 内部表（sqlite_sequence 等）不计入用户数据
            continue
        entry: dict[str, Any] = {'name': name, 'rows': None, 'error': None}
        try:
            count_row = conn.execute(f'SELECT COUNT(*) FROM {_quote_ident(name)}').fetchone()
            entry['rows'] = int(count_row[0]) if count_row and count_row[0] is not None else 0
            total += entry['rows']
        except (sqlite3.Error, OSError, TypeError, ValueError) as e:
            logger.warning(f'统计行数失败 {path}::{name}: {e}')
            entry['error'] = str(e)
            record['errors'].append(f'count({name}): {e}')
            issues.append(_issue(
                'warn', path, 'table_error',
                f'表 `{name}` 行数统计失败：{e}',
                f'对该表执行 REINDEX 或 `PRAGMA quick_check`，确认表结构是否损坏（表 `{name}`）',
            ))
        record['tables'].append(entry)

    record['table_count'] = len(record['tables'])
    record['row_count'] = total

    if not record['tables'] and record['size_bytes'] > 0:
        issues.append(_issue(
            'info', path, 'no_table',
            '库内没有任何用户表（可能是废弃/从未写入的占位库）',
            '确认无程序引用后可删除该库文件',
        ))


def _scan_db(path: Path, timeout_s: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """体检单个库。**任何异常都在内部消化成 issue**，绝不外抛"""
    issues: list[dict[str, Any]] = []
    record: dict[str, Any] = {
        'path': str(path),
        'size_bytes': 0,
        'integrity': 'unknown',
        'integrity_ok': False,
        'page_count': 0,
        'page_size': 0,
        'freelist_count': 0,
        'reclaimable_bytes': 0,
        'table_count': 0,
        'tables': [],
        'row_count': 0,
        'errors': [],
    }

    try:
        record['size_bytes'] = path.stat().st_size
    except OSError as e:
        logger.warning(f'读取文件大小失败 {path}: {e}')
        record['errors'].append(f'stat: {e}')
        issues.append(_issue('fail', path, 'permission',
                             f'无法读取文件属性：{e}',
                             '检查文件是否存在、权限是否足够'))
        return record, issues

    if record['size_bytes'] == 0:
        issues.append(_issue('info', path, 'empty_db',
                             '库文件大小为 0 字节（空占位文件）',
                             '确认无程序引用后可删除该文件'))

    try:
        conn, immutable = _open_readonly(path, timeout_s)
    except (sqlite3.Error, OSError) as e:
        logger.warning(f'只读打开失败 {path}: {e}')
        record['integrity'] = f'open failed: {e}'
        record['errors'].append(f'open: {e}')
        severity, kind, hint = _classify_error(e)
        issues.append(_issue(severity, path, kind, f'无法以只读方式打开数据库：{e}', hint))
        return record, issues

    if immutable:
        issues.append(_issue('info', path, 'immutable_fallback',
                             '只读打开失败，已回退到 immutable=1 读取（数据为瞬时快照）',
                             '确认该库当前没有写入进程；仍在写入时诊断结果可能不准'))

    try:
        if not _collect_integrity(conn, path, record, issues):
            return record, issues
        _collect_pragmas(conn, path, record, issues)
        _collect_tables(conn, path, record, issues)
    finally:
        conn.close()

    return record, issues


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #
def scan_storage(root: Path | str | None = None, *, top_n: int = DEFAULT_TOP_N,
                 timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """扫描状态目录下全部 SQLite 库，返回结构化体检报告。

    参数：
        root      数据根目录；None 时走 `core.data_dir.data_dir()`（`CLAWD_DATA_DIR`
                  或 `<workdir>/.clawd`），**不要在这里自己拼路径**。
        top_n     `size_top` 取体积最大的前 N 个库。
        timeout_s 打开连接时的锁等待超时（秒），极小值也不会崩。

    永不抛异常：单库损坏/占用/无权限都变成 `issues` 里的一条 fail。
    """
    started = time.perf_counter()
    base = Path(root) if root is not None else data_dir()

    dbs: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    if base.exists() and base.is_dir():
        for db_path in _iter_db_files(base):
            try:
                record, db_issues = _scan_db(db_path, timeout_s)
            except Exception as e:  # noqa: BLE001 — 兜底：诊断工具自身不能因为单个库崩掉
                logger.warning(f'体检 {db_path} 时出现未预期异常: {e}')
                record = {'path': str(db_path), 'size_bytes': 0, 'integrity': 'unknown',
                          'integrity_ok': False, 'table_count': 0, 'tables': [],
                          'row_count': 0, 'errors': [str(e)], 'reclaimable_bytes': 0,
                          'page_count': 0, 'page_size': 0, 'freelist_count': 0}
                db_issues = [_issue('fail', db_path, 'sqlite_error',
                                    f'体检过程中出现未预期异常：{e}',
                                    '记录该报错并人工检查该库文件')]
            dbs.append(record)
            issues.extend(db_issues)
    else:
        logger.warning(f'数据目录不存在或不是目录，跳过扫描: {base}')

    recommendations = _build_recommendations(issues)
    if not dbs:
        recommendations.append(f'在数据目录 {base} 下未发现任何 SQLite 数据库（*.db / *.sqlite / *.sqlite3）')

    ordered = sorted(dbs, key=lambda d: int(d.get('size_bytes') or 0), reverse=True)
    limit = max(0, int(top_n))
    size_top = [
        {
            'path': d['path'],
            'size_bytes': int(d.get('size_bytes') or 0),
            'reclaimable_bytes': int(d.get('reclaimable_bytes') or 0),
            'integrity': d.get('integrity', 'unknown'),
        }
        for d in ordered[:limit]
    ]

    return {
        'data_dir': str(base),
        'db_count': len(dbs),
        'total_bytes': sum(int(d.get('size_bytes') or 0) for d in dbs),
        'total_table_rows': sum(int(d.get('row_count') or 0) for d in dbs),
        'total_reclaimable_bytes': sum(int(d.get('reclaimable_bytes') or 0) for d in dbs),
        'size_top': size_top,
        'issues': issues,
        'recommendations': recommendations,
        'dbs': dbs,
        'elapsed_ms': round((time.perf_counter() - started) * 1000.0, 1),
    }


def _build_recommendations(issues: list[dict[str, Any]]) -> list[str]:
    """把 issue 的 suggestion + 路径拼成去重的中文可行动清单（保持首次出现顺序）"""
    out: list[str] = []
    seen: set[str] = set()
    for item in issues:
        if item['severity'] == 'info':
            continue        # info 只做记录，不进建议清单，避免噪音
        text = f'{item["suggestion"]}（{item["path"]}）'
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


__all__ = [
    'DB_SUFFIXES',
    'FRAGMENT_WARN_RATIO',
    'reclaimable_bytes',
    'scan_storage',
    'should_vacuum',
]
