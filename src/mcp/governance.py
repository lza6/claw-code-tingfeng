"""MCP 工具安全治理 — 工具签名 + 检疫审批流（参考 mcpproxy-go 模式，Python 实现）

防 MCP tool poisoning：新接入的 server 处于检疫期（quarantine），
- 工具签名（描述+参数 schema 哈希）记录基线
- 签名变更 → 重新进入检疫，需人工审批才可暴露
- 审批记录持久化（JSON 文件），跨会话有效
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .client import MCPToolInfo

logger = logging.getLogger(__name__)


class ServerStatus(str, Enum):
    QUARANTINED = "quarantined"  # 检疫期：工具可发现但调用需审批
    APPROVED = "approved"        # 已放行
    REJECTED = "rejected"        # 已拒绝


@dataclass
class ToolSignature:
    """工具签名（描述 + 参数 schema 的哈希基线）"""
    qualified_name: str
    signature: str  # sha256
    first_seen: str
    last_changed: str

    @staticmethod
    def compute(info: MCPToolInfo) -> str:
        payload = json.dumps(
            {"name": info.name, "description": info.description, "schema": info.input_schema},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class ServerRecord:
    """server 的治理记录（持久化单元）"""
    name: str
    status: str = ServerStatus.QUARANTINED.value
    approved_at: str | None = None
    tool_signatures: dict[str, dict[str, str]] = field(default_factory=dict)
    # 审批历史（最近 50 条）
    audit: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "approved_at": self.approved_at,
            "tool_signatures": self.tool_signatures,
            "audit": self.audit[-50:],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ServerRecord":
        return cls(
            name=d["name"],
            status=d.get("status", ServerStatus.QUARANTINED.value),
            approved_at=d.get("approved_at"),
            tool_signatures=d.get("tool_signatures", {}),
            audit=d.get("audit", []),
        )


class ToolGovernor:
    """工具治理器：签名基线 + 检疫 + 审批"""

    def __init__(self, state_path: str | Path | None = None):
        # 默认状态文件（可注入 tmp 路径便于测试）
        if state_path is None:
            state_path = Path(".clawd/mcp_governance.json")
        self.state_path = Path(state_path)
        self._records: dict[str, ServerRecord] = {}
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            for rec in data.get("servers", []):
                r = ServerRecord.from_dict(rec)
                self._records[r.name] = r
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"治理状态文件损坏，重建: {e}")
            self._records = {}

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"servers": [r.to_dict() for r in self._records.values()]}
        self.state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---------- 查询 ----------
    def get_record(self, server: str) -> ServerRecord:
        if server not in self._records:
            self._records[server] = ServerRecord(name=server)
        return self._records[server]

    def status_of(self, server: str) -> ServerStatus:
        try:
            return ServerStatus(self.get_record(server).status)
        except ValueError:
            return ServerStatus.QUARANTINED

    # ---------- 检疫/审批 ----------
    def sync_signatures(self, server: str, tools: list[MCPToolInfo]) -> dict[str, str]:
        """同步工具签名基线。返回每工具的判定: unchanged | changed | new

        已放行的 server 若出现签名变更，自动降级回检疫期（防工具投毒）。
        """
        record = self.get_record(server)
        verdicts: dict[str, str] = {}
        changed = False

        for info in tools:
            qn = info.qualified_name
            sig = ToolSignature.compute(info)
            prev = record.tool_signatures.get(qn)
            now = datetime.now(timezone.utc).isoformat()
            if prev is None:
                verdicts[qn] = "new"
                record.tool_signatures[qn] = {
                    "signature": sig, "first_seen": now, "last_changed": now
                }
            elif prev["signature"] != sig:
                verdicts[qn] = "changed"
                record.tool_signatures[qn] = {
                    "signature": sig,
                    "first_seen": prev["first_seen"],
                    "last_changed": now,
                }
                changed = True
            else:
                verdicts[qn] = "unchanged"

        # 已放行 server 出现签名变更 → 降级检疫
        if changed and record.status == ServerStatus.APPROVED.value:
            self._set_status(record, ServerStatus.QUARANTINED, reason="工具签名变更")
            logger.warning(
                f"server {server} 工具签名变更，已降级回检疫期"
            )
        self.save()
        return verdicts

    def approve(self, server: str, note: str = "") -> None:
        """人工放行 server"""
        record = self.get_record(server)
        self._set_status(record, ServerStatus.APPROVED, reason=f"人工放行: {note}")

    def reject(self, server: str, note: str = "") -> None:
        record = self.get_record(server)
        self._set_status(record, ServerStatus.REJECTED, reason=f"人工拒绝: {note}")

    def _set_status(self, record: ServerRecord, status: ServerStatus, reason: str) -> None:
        record.status = status.value
        if status == ServerStatus.APPROVED:
            record.approved_at = datetime.now(timezone.utc).isoformat()
        record.audit.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "status": status.value,
            "reason": reason,
        })
        self.save()
        logger.info(f"server {record.name} 状态 → {status.value} ({reason})")

    # ---------- 调用门禁 ----------
    def check_call_allowed(self, server: str, config_requires_approval: bool) -> tuple[bool, str]:
        """检查是否允许调用该 server 的工具

        返回 (allowed, reason)
        """
        status = self.status_of(server)
        if status == ServerStatus.REJECTED:
            return False, f"server {server} 已被拒绝"
        if status == ServerStatus.APPROVED and not config_requires_approval:
            return True, "ok"
        if config_requires_approval:
            return False, f"server {server} 配置要求每次审批"
        return False, f"server {server} 处于检疫期，需人工 approve 后方可调用"
