"""紧急热修复管理器 — FIXME 标注 → 技术债务 → 优先消除"""
from __future__ import annotations

import re
from pathlib import Path

from ..core.events import Event, EventBus, EventType, get_event_bus
from .models import TechDebtPriority, TechDebtRecord
from .tech_debt import TechDebtManager


class HotfixManager:
    """紧急热修复管理器

    流程:
    1. enable() — 进入热修复模式，解除 TDD 要求
    2. annotate() — 为修改的代码添加 FIXME-[ID] 标注
    3. create_debt_record() — 自动创建技术债务
    4. disable() — 退出热修复模式，自动 prioritize 所有债务
    """

    _COMMENT_STYLE = {
        '.py': '#',
        '.sh': '#',
        '.bash': '#',
        '.yml': '#',
        '.yaml': '#',
        '.toml': '#',
        '.ini': '#',
        '.cfg': '#',
        '.rb': '#',
        '.ts': '//',
        '.js': '//',
        '.jsx': '//',
        '.tsx': '//',
        '.go': '//',
        '.rs': '//',
        '.java': '//',
        '.c': '//',
        '.cpp': '//',
        '.h': '//',
        '.hpp': '//',
        '.sql': '--',
    }

    def __init__(
        self,
        root: Path | None = None,
        tech_debt_manager: TechDebtManager | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.root = root or Path.cwd()
        self._active = False
        self._issue_id: str | None = None
        self._tech_debt = tech_debt_manager or TechDebtManager(self.root)
        self._event_bus = event_bus or get_event_bus()
        self._hotfixed_files: set[Path] = set()

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def bypass_tdd(self) -> bool:
        """是否绕过 TDD 要求。仅在热修复激活时为 True。"""
        return self._active

    @property
    def hotfixed_files(self) -> list[Path]:
        """获取本次热修复涉及的文件列表"""
        return sorted(list(self._hotfixed_files))

    # -- 模式切换 --

    def enable(self, issue_id: str) -> None:
        """进入热修复模式"""
        self._active = True
        self._issue_id = issue_id
        self._hotfixed_files.clear()
        self._tech_debt.initialize()
        self._event_bus.publish(Event(
            type=EventType.WORKFLOW_HOTFIX_ENABLED,
            data={'issue_id': issue_id},
            source='hotfix_manager',
        ))

    def record_hotfix_applied(self, file_path: Path | str) -> None:
        """记录已应用热修复的文件"""
        if self._active:
            self._hotfixed_files.add(Path(file_path))

    def disable(self) -> list[TechDebtRecord]:
        """退出热修复模式，自动提升所有待处理债务优先级"""
        if not self._active:
            return []

        # 记录受影响的文件到债务描述中（如果尚未记录）
        affected_paths = [str(p.relative_to(self.root)) for p in self._hotfixed_files]

        pending = self._tech_debt.prioritize_all_pending()

        # 如果有活跃的 issue_id 且有受影响文件，确保它们被关联
        if self._issue_id and affected_paths:
            # 这里的逻辑可以根据需要调整，目前简单地通过 Event 广播
            pass

        self._active = False
        self._event_bus.publish(Event(
            type=EventType.WORKFLOW_HOTFIX_DISABLED,
            data={
                'pending_debt': len(pending),
                'affected_files': affected_paths
            },
            source='hotfix_manager',
        ))
        self._issue_id = None
        self._hotfixed_files.clear()
        return pending

    # -- 代码标注 --

    def annotate(self, content: str, issue_id: str | None = None,
                 file_ext: str = '.py') -> str:
        """为代码片段添加 FIXME 标注

        参数:
            content: 原始代码内容
            issue_id: 热修复问题 ID（默认使用 enable 时传入的）
            file_ext: 文件扩展名，用于确定注释语法
        返回: 添加了 FIXME 标注的代码
        """
        cid = issue_id or self._issue_id or 'HOTFIX'
        comment = self._COMMENT_STYLE.get(file_ext, '//')
        return f'{comment} FIXME-[{cid}]: 热修复已应用\n{content}'

    def annotate_file(self, file_path: Path, original_content: str,
                      new_content: str, issue_id: str | None = None) -> str:
        """对整个文件修改添加 FIXME 标注"""
        cid = issue_id or self._issue_id or 'HOTFIX'
        comment = self._COMMENT_STYLE.get(file_path.suffix, '//')
        suffix = '\n' if not new_content.endswith('\n') else ''
        return f'{new_content}{suffix}{comment} FIXME-[{cid}]: 热修复已应用\n'

    # -- 债务记录 --

    def cleanup_fixme_annotations(self, file_path: Path, issue_id: str) -> bool:
        """清理指定文件中与特定 Issue ID 相关的 FIXME 标注"""
        if not file_path.exists():
            return False

        content = file_path.read_text(encoding='utf-8')
        pattern = rf'.*FIXME-\[{re.escape(issue_id)}\]:.*\n?'
        new_content = re.sub(pattern, '', content)

        if new_content != content:
            file_path.write_text(new_content, encoding='utf-8')
            return True
        return False

    def create_debt_record(
        self,
        description: str,
        affected_files: list[str] | None = None,
        issue_id: str | None = None,
        priority: TechDebtPriority = TechDebtPriority.HIGH,
    ) -> TechDebtRecord:
        """自动创建技术债务记录"""
        cid = issue_id or self._issue_id or 'HOTFIX'
        return self._tech_debt.add_record(
            issue_id=cid,
            description=description,
            affected_files=affected_files or [],
            priority=priority,
        )
