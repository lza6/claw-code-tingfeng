"""Atomic Integrator — 高精度代码集成器
使用 Unified Diff 或 AST 安全补丁方式集成代码变更。
"""
from __future__ import annotations

import contextlib
import difflib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class IntegrationResult:
    """集成结果"""
    success: bool
    file_path: str
    diff: str = ""
    error: str = ""


class AtomicIntegrator:
    """原子化集成器，提供比正则提取更稳健的代码合并能力。

    企业级特性:
    - 原子写入: 使用临时文件 + rename 确保文件完整性
    - 事务支持: 支持批量变更回滚，确保多文件修改的一致性
    - 审计集成: 支持在应用前调用 Auditor 进行安全/质量检查
    """

    def __init__(self, workdir: Path | None = None, message_bus: Any | None = None) -> None:
        self.workdir: Path = workdir or Path.cwd()
        self.message_bus = message_bus
        self._backups: dict[str, str] = {}
        self._in_transaction: bool = False

    async def start_transaction(self) -> None:
        """显式开启事务"""
        self._backups.clear()
        self._in_transaction = True
        logger.info("AtomicIntegrator: 开启全局事务")

        # [NEW] 广播事务开始消息
        if self.message_bus:
            from .message_bus import AgentMessage, MessageType
            await self.message_bus.publish(AgentMessage(
                sender='integrator',
                recipient='orchestrator-1',
                message_type=MessageType.TX_SYNC,
                content="Transaction started",
                metadata={"action": "start"}
            ))

    async def commit(self) -> None:
        """提交事务，清除备份"""
        count = len(self._backups)
        self._backups.clear()
        self._in_transaction = False
        logger.info(f"AtomicIntegrator: 提交事务 (涉及 {count} 个文件修正)")

        # [NEW] 广播事务提交消息
        if self.message_bus:
            from .message_bus import AgentMessage, MessageType
            await self.message_bus.publish(AgentMessage(
                sender='integrator',
                recipient='orchestrator-1',
                message_type=MessageType.TX_SYNC,
                content="Transaction committed",
                metadata={"action": "commit", "count": count}
            ))

    def apply_patch(self, file_path: str, new_content: str, skip_backup: bool = False) -> IntegrationResult:
        """应用代码变更 (已升级为原子写入)。

        参数:
            file_path: 目标文件路径
            new_content: 新文件内容
            skip_backup: 是否跳过备份（由调用方已备份时设为 True）
        """
        full_path = self.workdir / file_path
        tmp_path = full_path.with_suffix('.tmp')

        try:
            # 确保父目录存在
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # 事务模式下自动备份（仅在未跳过时执行）
            if self._in_transaction and not skip_backup:
                self._backup_file(file_path)

            old_content = ""
            if full_path.exists():
                with open(full_path, encoding='utf-8') as f:
                    old_content = f.read()

            # 生成 Diff 供审计
            diff = "".join(difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f'a/{file_path}',
                tofile=f'b/{file_path}'
            ))

            # 原子写入流程
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            # 使用 os.replace 确保操作原子性
            import os
            os.replace(tmp_path, full_path)

            logger.info(f"成功原子化集成变更至: {file_path}")
            return IntegrationResult(success=True, file_path=file_path, diff=diff)

        except Exception as e:
            if tmp_path.exists():
                with contextlib.suppress(Exception):
                    tmp_path.unlink()
            logger.error(f"原子化集成失败 {file_path}: {e}")
            return IntegrationResult(success=False, file_path=file_path, error=str(e))

    async def audit_and_apply(
        self,
        file_path: str,
        new_content: str,
        auditor: Any = None
    ) -> IntegrationResult:
        """先审计，后应用。如果审计失败，则拒绝集成。"""
        if auditor:
            from .message_bus import AgentMessage, MessageType
            audit_msg = AgentMessage(
                sender='integrator',
                recipient=auditor.agent_id,
                message_type=MessageType.AUDIT_REQUEST,
                content=f"请审计以下代码变更:\n\n文件: {file_path}\n内容:\n{new_content}"
            )
            audit_result = await auditor.process(audit_msg)
            if "AUDIT_FAIL" in audit_result:
                return IntegrationResult(
                    success=False,
                    file_path=file_path,
                    error=f"审计未通过: {audit_result}"
                )

        return self.apply_patch(file_path, new_content)

    def _backup_file(self, file_path: str) -> None:
        """备份原始文件内容以便回滚"""
        full_path = self.workdir / file_path
        if full_path.exists() and file_path not in self._backups:
            with open(full_path, encoding='utf-8') as f:
                self._backups[file_path] = f.read()
        elif not full_path.exists():
            self._backups[file_path] = "__DELETED__"

    async def rollback(self) -> None:
        """回滚所有当前事务中的变更"""
        if not self._backups:
            return
        logger.warning(f"AtomicIntegrator: 触发事务回滚，涉及 {len(self._backups)} 个文件")
        for file_path, content in self._backups.items():
            full_path = self.workdir / file_path
            if content == "__DELETED__":
                if full_path.exists():
                    full_path.unlink()
            else:
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(content)
        self._backups.clear()
        self._in_transaction = False

        # [NEW] 广播事务回滚消息
        if self.message_bus:
            from .message_bus import AgentMessage, MessageType
            await self.message_bus.publish(AgentMessage(
                sender='integrator',
                recipient='orchestrator-1',
                message_type=MessageType.TX_SYNC,
                content="Transaction rolled back",
                metadata={"action": "rollback"}
            ))

    async def integrate_batch(self, code_changes: dict[str, str]) -> list[IntegrationResult]:
        """批量集成代码变更 (支持流式事务)。

        修复: 备份逻辑已移至 apply_patch 内部，避免重复备份。
        """
        results = []

        try:
            for path, content in code_changes.items():
                # 备份逻辑已移至 apply_patch 内部，避免重复备份
                res = self.apply_patch(path, content)
                results.append(res)
                if not res.success:
                    raise RuntimeError(f"集成文件 {path} 失败: {res.error}")

            # [NEW] 广播批次集成完成消息
            if self.message_bus:
                from .message_bus import AgentMessage, MessageType
                await self.message_bus.publish(AgentMessage(
                    sender='integrator',
                    recipient='orchestrator-1',
                    message_type=MessageType.TX_SYNC,
                    content=f"Integrated {len(code_changes)} files",
                    metadata={"action": "integrate_batch", "files": list(code_changes.keys())}
                ))

            return results

        except Exception as e:
            logger.error(f"批量集成发生异常: {e}")
            if self._in_transaction:
                await self.rollback()
            # 返回失败结果
            return [IntegrationResult(success=False, file_path=p, error=str(e)) for p in code_changes]
