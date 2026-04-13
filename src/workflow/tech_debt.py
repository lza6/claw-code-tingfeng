"""TECH_DEBT.md 技术债务管理"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .models import TechDebtPriority, TechDebtRecord


class TechDebtManager:
    """TECH_DEBT.md 文件管理"""

    TECH_DEBT_FILE = 'TECH_DEBT.md'
    _HEADER = '# 技术债务登记表\n\n'
    _TABLE_HEADER = (
        '| ID | 优先级 | 问题 | 描述 | 文件 | 创建日期 | 解决日期 |\n'
        '|----|--------|------|------|------|----------|----------|\n'
    )

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.file_path = self.root / self.TECH_DEBT_FILE
        self._cached_records: list[TechDebtRecord] | None = None
        self._last_mtime: float = 0

    # -- 初始化 --

    def initialize(self) -> None:
        """创建 TECH_DEBT.md（不存在时）"""
        if not self.file_path.exists():
            self.file_path.write_text(
                self._HEADER + self._TABLE_HEADER, encoding='utf-8',
            )

    # -- 写入 --

    def add_record(
        self,
        issue_id: str,
        description: str,
        affected_files: list[str] | None = None,
        priority: TechDebtPriority = TechDebtPriority.HIGH,
    ) -> TechDebtRecord:
        """添加技术债务记录"""
        self.initialize()
        records = self._read_all()
        next_id = self._next_id(records)
        record = TechDebtRecord(
            record_id=next_id,
            issue_id=issue_id,
            priority=priority,
            description=description,
            affected_files=affected_files or [],
            created_at=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        )
        self._rewrite_records([*records, record])
        return record

    # -- 读取 --

    def read_all(self) -> list[TechDebtRecord]:
        """解析 Markdown 表格返回记录列表"""
        self.initialize()
        return self._read_all()

    # -- 批量操作 --

    def prioritize_all_pending(self) -> list[TechDebtRecord]:
        """将所有未解决债务提升为 HIGH 优先级。热修复退出时自动调用。"""
        records = self.read_all()
        pending = [r for r in records if not r.resolved]
        if not pending:
            return []
        updated = [
            TechDebtRecord(
                record_id=r.record_id, issue_id=r.issue_id,
                priority=TechDebtPriority.HIGH if not r.resolved else r.priority,
                description=r.description, affected_files=r.affected_files,
                created_at=r.created_at, resolved=r.resolved,
                resolved_at=r.resolved_at,
            ) for r in records
        ]
        self._rewrite_records(updated)
        return pending

    def resolve(self, record_id: str) -> bool:
        """标记债务已解决"""
        records = self.read_all()
        for i, r in enumerate(records):
            if r.record_id == record_id:
                records[i] = TechDebtRecord(
                    record_id=r.record_id, issue_id=r.issue_id,
                    priority=r.priority, description=r.description,
                    affected_files=r.affected_files, created_at=r.created_at,
                    resolved=True,
                    resolved_at=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                )
                self._rewrite_records(records)
                return True
        return False

    def get_top_priorities(self, limit: int = 5) -> list[TechDebtRecord]:
        """返回优先级最高的未解决债务"""
        records = self.read_all()
        pending = [r for r in records if not r.resolved]
        order = {
            TechDebtPriority.CRITICAL: 0, TechDebtPriority.HIGH: 1,
            TechDebtPriority.MEDIUM: 2, TechDebtPriority.LOW: 3,
        }
        return sorted(pending, key=lambda r: (order.get(r.priority, 4), r.created_at))[:limit]

    # -- 内部方法 --

    def _read_all(self) -> list[TechDebtRecord]:
        if not self.file_path.exists():
            return []

        # 缓存验证
        current_mtime = self.file_path.stat().st_mtime
        if self._cached_records is not None and current_mtime == self._last_mtime:
            return self._cached_records

        content = self.file_path.read_text(encoding='utf-8')
        self._cached_records = self._parse_table(content)
        self._last_mtime = current_mtime
        return self._cached_records

    def _parse_table(self, content: str) -> list[TechDebtRecord]:
        records: list[TechDebtRecord] = []
        lines = content.splitlines()
        in_table = False
        for line in lines:
            if line.startswith('| ID |'):
                in_table = True
                continue
            if line.startswith('|--') or line.startswith('|----'):
                continue
            if in_table and line.startswith('|'):
                # 使用非捕获组分割，防止解析包含 | 的描述时出错
                cells = [c.strip() for c in re.split(r'(?<!\\)\|', line.strip('|'))]
                if len(cells) >= 7:
                    priority_str = cells[1]
                    priority = TechDebtPriority(
                        priority_str
                    ) if priority_str in (e.value for e in TechDebtPriority) else TechDebtPriority.HIGH
                    files = [f.strip() for f in cells[4].split(',') if f.strip()] if cells[4] and cells[4] != '-' else []
                    resolved_str = cells[6].strip() if len(cells) > 6 else '-'
                    is_resolved = resolved_str != '-' and len(resolved_str) > 0
                    records.append(TechDebtRecord(
                        record_id=cells[0], issue_id=cells[2], priority=priority,
                        description=cells[3], affected_files=files,
                        created_at=cells[5], resolved=is_resolved,
                        resolved_at=resolved_str if is_resolved else None,
                    ))
        return records

    def _next_id(self, records: list[TechDebtRecord]) -> str:
        existing_ids = [
            int(m.group(1)) for r in records
            if (m := re.match(r'TD-(\d+)', r.record_id))
        ]
        next_num = max(existing_ids, default=0) + 1
        return f'TD-{next_num:04d}'

    def _rewrite_records(self, records: list[TechDebtRecord]) -> None:
        lines = [self._HEADER, self._TABLE_HEADER]
        for r in records:
            lines.append(self._format_row(r))

        temp_file = self.file_path.with_suffix('.tmp')
        temp_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')

        # 原子替换并更新缓存状态
        os.replace(temp_file, self.file_path)
        self._cached_records = records
        self._last_mtime = self.file_path.stat().st_mtime

    @staticmethod
    def _format_row(record: TechDebtRecord) -> str:
        files = ', '.join(record.affected_files) if record.affected_files else '-'
        resolved = record.resolved_at or '-' if record.resolved else '-'
        return (
            f'| {record.record_id} | {record.priority.value} | {record.issue_id} '
            f'| {record.description} | {files} | {record.created_at} | {resolved} |'
        )
