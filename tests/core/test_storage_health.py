"""`src/core/storage_health.py` 的测试

覆盖点对应真实故障面：
- 正常库 → 数据（integrity/行数/体积）必须真实读出来，不能是"没报错就算过"
- 损坏库 → **不得抛异常**，且必须在 issues 里留下一条中文 fail
- 空目录 → 不得报假失败（db_count=0 / issues=[]）
- 碎片 → VACUUM 建议真的会被触发（不是只有纯函数分支）
- timeout_s 极小 → 不崩
- 只读约束 → 体检过程不得修改库文件（字节数/mtime 不变是硬证据）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.core.storage_health import (
    FRAGMENT_WARN_RATIO,
    reclaimable_bytes,
    scan_storage,
    should_vacuum,
)


def _make_db(path: Path, rows: int = 3) -> Path:
    """建一个正常库：一张表 + N 行"""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute('CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)')
        conn.executemany('INSERT INTO notes (body) VALUES (?)',
                         [(f'note-{i}',) for i in range(rows)])
        conn.commit()
    finally:
        conn.close()
    return path


def _severity_of(report: dict, kind: str) -> list[str]:
    return [i['severity'] for i in report['issues'] if i['kind'] == kind]


class TestHealthyDb:
    def test_integrity_rows_and_size_top(self, tmp_path: Path):
        db = _make_db(tmp_path / 'good.db', rows=3)

        report = scan_storage(tmp_path)

        assert report['db_count'] == 1
        rec = report['dbs'][0]
        assert rec['path'] == str(db)
        assert rec['integrity'] == 'ok'
        assert rec['integrity_ok'] is True
        assert rec['size_bytes'] == db.stat().st_size
        assert rec['table_count'] == 1
        assert rec['tables'][0]['name'] == 'notes'
        assert rec['tables'][0]['rows'] == 3
        assert rec['row_count'] == 3
        assert report['total_table_rows'] == 3
        assert report['total_bytes'] == db.stat().st_size
        assert [item['path'] for item in report['size_top']] == [str(db)]
        assert report['size_top'][0]['size_bytes'] == db.stat().st_size
        assert report['issues'] == []
        assert isinstance(report['elapsed_ms'], float)

    def test_discovers_all_three_suffixes(self, tmp_path: Path):
        for name in ('a.db', 'b.sqlite', 'c.sqlite3', 'ignored.txt'):
            (tmp_path / name).write_bytes(b'placeholder')
        report = scan_storage(tmp_path)
        assert report['db_count'] == 3

    def test_size_top_respects_top_n_and_order(self, tmp_path: Path):
        _make_db(tmp_path / 'small.db', rows=1)
        big = _make_db(tmp_path / 'big.db', rows=300)

        report = scan_storage(tmp_path, top_n=1)

        assert len(report['size_top']) == 1
        assert report['size_top'][0]['path'] == str(big)
        assert report['db_count'] == 2        # top_n 只截断展示，不影响统计

    def test_scan_is_read_only(self, tmp_path: Path):
        """体检不得改动库文件：字节数与 mtime 必须原样"""
        db = _make_db(tmp_path / 'good.db')
        before_stat = db.stat()

        scan_storage(tmp_path)

        after_stat = db.stat()
        assert after_stat.st_size == before_stat.st_size
        assert after_stat.st_mtime_ns == before_stat.st_mtime_ns


class TestCorruptDb:
    def test_garbage_file_reports_fail_without_raising(self, tmp_path: Path):
        bad = tmp_path / 'broken.db'
        bad.write_bytes(b'this is definitely not a sqlite database' * 20)

        report = scan_storage(tmp_path)      # 关键：不抛异常

        assert report['db_count'] == 1
        rec = report['dbs'][0]
        assert rec['integrity_ok'] is False
        assert 'error' in rec['integrity'] or 'not a database' in rec['integrity']

        fails = [i for i in report['issues'] if i['severity'] == 'fail']
        assert len(fails) == 1
        fail = fails[0]
        assert fail['path'] == str(bad)
        assert fail['kind'] in ('corrupt', 'sqlite_error', 'permission')
        assert fail['zh_message']      # 中文原因非空
        assert any('一' <= ch <= '鿿' for ch in fail['zh_message'])
        assert report['recommendations']    # 有可行动建议

    def test_truncated_header_reports_fail(self, tmp_path: Path):
        """只写 SQLite 文件头前 10 字节：能识别成库但读不动（真实断电场景）"""
        bad = tmp_path / 'half.db'
        bad.write_bytes(b'SQLite format 3\x00'[:10])

        report = scan_storage(tmp_path)

        assert report['db_count'] == 1
        assert [i['severity'] for i in report['issues'] if i['severity'] == 'fail']

    def test_other_dbs_still_scanned_when_one_is_corrupt(self, tmp_path: Path):
        """单库损坏不得中断整体体检"""
        _make_db(tmp_path / 'good.db', rows=2)
        (tmp_path / 'broken.db').write_bytes(b'\x00' * 4096)

        report = scan_storage(tmp_path)

        assert report['db_count'] == 2
        good = [d for d in report['dbs'] if d['path'].endswith('good.db')][0]
        assert good['integrity'] == 'ok'
        assert good['row_count'] == 2
        assert report['total_table_rows'] == 2


class TestEmptyDir:
    def test_empty_dir_is_not_a_failure(self, tmp_path: Path):
        report = scan_storage(tmp_path)

        assert report['db_count'] == 0
        assert report['total_bytes'] == 0
        assert report['total_table_rows'] == 0
        assert report['size_top'] == []
        assert report['dbs'] == []
        assert report['issues'] == []          # 不报假失败
        assert report['recommendations']       # 但要告诉人"这里什么都没有"

    def test_missing_dir_is_not_a_failure(self, tmp_path: Path):
        report = scan_storage(tmp_path / 'nope')
        assert report['db_count'] == 0
        assert report['issues'] == []

    def test_default_root_uses_data_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """root=None 必须走 data_dir()，不能自己拼 '.clawd'"""
        monkeypatch.setenv('CLAWD_DATA_DIR', str(tmp_path))
        _make_db(tmp_path / 'from_env.db')

        report = scan_storage()

        assert report['db_count'] == 1
        assert report['data_dir'] == str(tmp_path)


class TestFragmentation:
    def test_freelist_triggers_vacuum_suggestion(self, tmp_path: Path):
        """真实制造碎片：塞大量大行再全删 → freelist 增长 → 应给出 VACUUM 建议"""
        db = tmp_path / 'frag.db'
        conn = sqlite3.connect(str(db))
        try:
            conn.execute('CREATE TABLE blobs (id INTEGER PRIMARY KEY, payload BLOB)')
            payload = b'x' * 4000
            conn.executemany('INSERT INTO blobs (payload) VALUES (?)',
                             [(payload,) for _ in range(500)])
            conn.commit()
            conn.execute('DELETE FROM blobs')
            conn.commit()
        finally:
            conn.close()

        report = scan_storage(tmp_path)
        rec = report['dbs'][0]

        assert rec['freelist_count'] > 0, '前提不成立：没能制造出空洞页'
        assert rec['reclaimable_bytes'] == rec['freelist_count'] * rec['page_size']
        assert rec['reclaimable_bytes'] > 0
        assert rec['integrity_ok'] is True          # 有空洞 ≠ 库坏了
        frag = [i for i in report['issues'] if i['kind'] == 'fragmented']
        assert len(frag) == 1
        assert frag[0]['severity'] == 'warn'
        assert 'VACUUM' in frag[0]['suggestion']
        assert any('VACUUM' in r for r in report['recommendations'])


class TestPureHelpers:
    """碎片判定的纯函数分支（不依赖能否在某个平台上造出 freelist）"""

    @pytest.mark.parametrize(('size_bytes', 'freelist', 'page_size', 'expected'), [
        (1000, 0, 4096, False),                          # 无空洞
        (1000, 1, 4096, True),                           # 可回收 4096 > 1000*20%
        (10000, 1, 4096, True),                          # 4096 / 10000 = 41% > 20%
        (100000, 1, 4096, False),                        # 4.1% < 20%
        (0, 5, 4096, False),                             # 空文件不判碎片
        (1000, -1, 4096, False),                         # 负数视为无空洞
        (1000, 5, 0, False),                             # 页大小未知时不建议
    ])
    def test_should_vacuum_branches(self, size_bytes, freelist, page_size, expected):
        assert should_vacuum(size_bytes, freelist, page_size) is expected

    def test_reclaimable_bytes(self):
        assert reclaimable_bytes(3, 4096) == 12288
        assert reclaimable_bytes(0, 4096) == 0
        assert reclaimable_bytes(3, 0) == 0
        assert reclaimable_bytes(-1, 4096) == 0

    def test_threshold_matches_constant(self):
        """阈值改常量就得改行为：正好等于 20% 不触发（要求严格大于）"""
        page = 4096
        size = int(page / FRAGMENT_WARN_RATIO)          # 恰好 20%
        assert should_vacuum(size, 1, page) is False


class TestTimeout:
    def test_tiny_timeout_does_not_crash(self, tmp_path: Path):
        _make_db(tmp_path / 'good.db', rows=5)

        report = scan_storage(tmp_path, timeout_s=0.0001)

        assert report['db_count'] == 1
        assert report['dbs'][0]['integrity_ok'] is True

    def test_zero_and_negative_timeout_do_not_crash(self, tmp_path: Path):
        _make_db(tmp_path / 'good.db', rows=1)
        for value in (0.0, -1.0):
            report = scan_storage(tmp_path, timeout_s=value)
            assert report['db_count'] == 1

    def test_blocked_db_is_reported_not_raised(self, tmp_path: Path):
        """持有排他锁时不得抛异常中断（SQLite 报 database is locked → 落 issues）"""
        db = _make_db(tmp_path / 'locked.db', rows=1)
        holder = sqlite3.connect(str(db), timeout=0)
        try:
            holder.execute('BEGIN EXCLUSIVE')
            report = scan_storage(tmp_path, timeout_s=0.001)
        finally:
            holder.rollback()
            holder.close()

        assert report['db_count'] == 1
        # 只读打开 + 排他锁：要么只读到旧快照，要么落一条 fail，二者都不能崩
        severities = {i['severity'] for i in report['issues']}
        assert severities <= {'fail', 'warn', 'info'}
