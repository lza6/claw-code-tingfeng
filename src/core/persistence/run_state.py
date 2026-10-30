import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..workflow_status import WorkflowStatus

logger = logging.getLogger("core.persistence.run_state")

# [Phase 2] 集成 Durable Surfaces
_DURABLE_SURFACES_AVAILABLE = False
try:
    from src.core.durable.surface_manager import SurfaceManager
    from src.core.durable.surfaces.assurance_plan import AssurancePlan as DurableAssurancePlan
    from src.core.durable.surfaces.assurance_plan import AssuranceScenario
    from src.core.durable.surfaces.coordination_state import (
        CoordinationState,
        SessionInfo,
        SessionState,
    )
    from src.core.durable.surfaces.evidence_log import EvidenceEntry as DurableEvidenceEntry
    from src.core.durable.surfaces.evidence_log import EvidenceLog as DurableEvidenceLog
    from src.core.durable.surfaces.evidence_log import EvidenceType
    from src.core.durable.surfaces.objective_contract import (
        ObjectiveContract as DurableObjectiveContract,
    )
    from src.core.durable.surfaces.obligation_model import Obligation as DurableObligation
    from src.core.durable.surfaces.obligation_model import ObligationModel as DurableObligationModel
    from src.core.durable.surfaces.obligation_model import ObligationStatus
    from src.core.durable.surfaces.status_summary import RunPhase, StatusSummary
    _DURABLE_SURFACES_AVAILABLE = True
except ImportError:
    # Durable surfaces not available, fall back to existing behavior
    pass

if _DURABLE_SURFACES_AVAILABLE:
    __all__ = [
        "CoordinationState",
        "DurableAssurancePlan",
        "DurableEvidenceLog",
        "DurableObjectiveContract",
        "DurableObligationModel",
        "RunStateManager",
        "StatusSummary",
        "SurfaceManager",
    ]
else:
    __all__ = ["RunStateManager"]

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _validate_run_id(run_id: str) -> str:
    """校验 run_id，防止路径穿越与非法字符注入。"""
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id 必须是非空字符串")
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(
            f"非法 run_id: {run_id!r}。仅允许 1-64 位字母、数字、下划线和连字符，且首字符必须是字母或数字。"
        )
    return run_id


class RunStateManager:
    """运行状态管理器 (汲取 GoalX durable state 设计精髓)

    职责:
    - 实时持久化工作流 DAG 状态。
    - 持久化 ObjectiveContract (目标合同)。
    - 持久化 ObligationModel (义务模型)。
    - 支持从崩溃中恢复 (Resume/Recover)。
    - 记录决策过程和证据。
    - [Phase 2] 集成 Durable Surfaces 系统。
    """
    def __init__(self, workdir: Path, run_id: str = "latest"):
        run_id = _validate_run_id(run_id)
        self.run_dir = workdir / ".clawd" / "runs" / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.coordination_file = self.run_dir / "coordination.json"
        self.contract_file = self.run_dir / "objective-contract.json"
        self.obligation_file = self.run_dir / "obligation-model.json"
        self.evidence_log_file = self.run_dir / "evidence-log.jsonl"
        self.backup_dir = self.run_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # [Phase 2] 初始化 Durable Surfaces
        if _DURABLE_SURFACES_AVAILABLE:
            self._surface_manager: SurfaceManager | None = SurfaceManager(self.run_dir)
        else:
            self._surface_manager = None

    def save_contract(self, contract: Any) -> None:
        """保存目标合同 (借鉴 GoalX SaveObjectiveContract)"""
        data = self._to_dict(contract)
        self._write_atomic(self.contract_file, data)

    def load_contract(self) -> dict[str, Any] | None:
        """加载目标合同"""
        return self._load_json(self.contract_file)

    def save_obligations(self, model: Any) -> None:
        """保存义务模型 (借鉴 GoalX SaveObligationModel)"""
        data = self._to_dict(model)
        data["updated_at"] = datetime.utcnow().isoformat()
        self._write_atomic(self.obligation_file, data)

    def load_obligations(self) -> dict[str, Any] | None:
        """加载义务模型"""
        return self._load_json(self.obligation_file)

    def record_evidence_event(self, scenario_id: str, harness_kind: str, result: dict[str, Any], artifacts: list[str] | None = None) -> None:
        """记录证据事件到 JSONL (借鉴 GoalX AppendEvidenceLogEvent)

        并发安全：JSONL 追加在文件锁内完成，并 flush + fsync，
        避免多执行者同时写时出现交错行或掉电丢事件。
        """
        from ...utils.file_ops import file_lock

        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "scenario_id": scenario_id,
            "harness_kind": harness_kind,
            "oracle_result": result,
            "artifact_refs": artifacts or []
        }
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with file_lock(self.evidence_log_file, timeout=30.0):
            with open(self.evidence_log_file, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())


    def _to_dict(self, obj: Any) -> dict[str, Any]:
        """将 dataclass 转换为字典"""
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        import dataclasses
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
        return obj

    def _write_atomic(self, path: Path, data: dict[str, Any]) -> None:
        """原子写入文件（跨平台锁 + fsync；备份先复制再覆盖）

        旧实现使用固定 `<name>.tmp`、无锁、无 fsync，且先 move 目标再 replace：
        并发写会互相覆盖，崩溃窗口里目标文件可能不存在。
        """
        from ...utils.file_ops import atomic_write, file_lock

        try:
            with file_lock(path, timeout=30.0):
                # 先备份现有文件（copy 而不是 move：目标始终存在）
                if path.exists():
                    backup_name = (
                        f"{path.stem}_{int(datetime.utcnow().timestamp())}_"
                        f"{uuid.uuid4().hex[:6]}{path.suffix}"
                    )
                    backup_path = self.backup_dir / backup_name
                    try:
                        shutil.copy2(path, backup_path)
                    except OSError as backup_err:
                        logger.warning(f"创建备份失败 (非致命): {backup_err}")

                atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            logger.error(f"原子写入 {path} 失败: {e}")
            raise RuntimeError(f"原子写入失败: {path}") from e

    def _load_json(self, path: Path) -> dict[str, Any] | None:
        """安全加载 JSON"""
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载 {path} 失败: {e}")
            return None

    def sync(self, state: dict[str, Any]) -> None:
        """同步完整状态到磁盘，并保留一个备份"""
        data = {
            "version": 2, # v2: 结构化增强
            "run_id": self.run_dir.name,
            "updated_at": datetime.utcnow().isoformat(),
            "goal": state.get("goal", ""),
            "intent": state.get("intent", "deliver"),
            "iteration": state.get("iteration", 0),
            "plan_summary": state.get("plan_summary", []),
            "tasks": state.get("tasks", []),
            "optimization_points": state.get("optimization_points", []),
            "sessions": state.get("sessions", {}),
            "evidence": state.get("evidence", []),
            "metadata": state.get("metadata", {})
        }
        self._write_atomic(self.coordination_file, data)

    def load(self) -> dict[str, Any] | None:
        """加载保存的状态，如果主文件损坏则尝试最新的备份"""
        files_to_try = [self.coordination_file, *sorted(self.backup_dir.glob("*.json"), reverse=True)]

        for file in files_to_try:
            if not file.exists():
                continue
            try:
                with open(file, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"无法从 {file} 加载状态: {e}")
                continue
        return None

    def update_task(self, task_id: str, status: WorkflowStatus, result: Any = None, evidence: list[str] | None = None, worktree_id: str | None = None, verification_criteria: str | None = None, expected_version: int | None = None):
        """增量更新单个任务状态 (借鉴 GoalX CoordinationRequiredItem)
        支持乐观并发控制 (OCC)。

        读改写整体加锁：OCC 检查与实际写入必须在同一临界区，
        否则两个执行者可能同时通过版本检查后互相覆盖。
        """
        from ...utils.file_ops import file_lock

        with file_lock(self.coordination_file, timeout=30.0):
            return self._update_task_locked(
                task_id, status, result, evidence, worktree_id,
                verification_criteria, expected_version,
            )

    def _update_task_locked(self, task_id: str, status: WorkflowStatus, result: Any = None, evidence: list[str] | None = None, worktree_id: str | None = None, verification_criteria: str | None = None, expected_version: int | None = None):
        """在文件锁内执行 update_task 的读改写。"""
        current_data = self.load()
        if not current_data:
             # 如果无法加载，尝试初始化一个
             current_data = {"tasks": [], "version": 0}

        # OCC 检查
        if expected_version is not None:
            actual_version = current_data.get("version", 0)
            if actual_version != expected_version:
                raise RuntimeError(f"OCC Conflict: expected version {expected_version}, but found {actual_version}")

        state = current_data.get("state", current_data)
        tasks_data = state.get("tasks", [])

        found = False
        for t_dict in tasks_data:
            if t_dict.get("task_id") == task_id:
                t_dict["status"] = status.value if hasattr(status, 'value') else status
                if result is not None:
                    t_dict["result"] = result
                if evidence:
                    t_dict["evidence_paths"] = list(set(t_dict.get("evidence_paths", []) + evidence))
                if worktree_id is not None:
                    t_dict["worktree_id"] = worktree_id
                if verification_criteria is not None:
                    t_dict["verification_criteria"] = verification_criteria

                t_dict["updated_at"] = datetime.utcnow().isoformat()
                found = True
                break

        if not found:
            tasks_data.append({
                "task_id": task_id,
                "status": status.value if hasattr(status, 'value') else status,
                "result": result,
                "evidence_paths": evidence or [],
                "worktree_id": worktree_id,
                "verification_criteria": verification_criteria,
                "updated_at": datetime.utcnow().isoformat()
            })

        state["tasks"] = tasks_data
        # 增加全局版本号
        state["version"] = current_data.get("version", 0) + 1
        self.sync(state)

    def record_evidence(self, task_id: str, file_path: str):
        """记录任务执行证据"""
        self.update_task(task_id, WorkflowStatus.RUNNING, evidence=[file_path])

    # ===== [Phase 2] Durable Surfaces 集成 =====

    @property
    def surface_manager(self) -> Optional["SurfaceManager"]:
        """获取 SurfaceManager 实例 (如果可用)"""
        return self._surface_manager

    def update_status_summary(
        self,
        phase: str = "executing",
        current_activity: str = "",
        active_sessions: int = 0,
        blocked_sessions: int = 0,
        progress_percentage: float = 0.0,
        obligations_satisfied: int = 0,
        obligations_total: int = 0,
        summary: str = "",
    ) -> None:
        """更新运行状态摘要 (Durable Surface)"""
        if not self._surface_manager:
            return

        try:
            status = self._surface_manager.load_surface(
                "status_summary", StatusSummary
            )
            if status.run_id == "":
                status.run_id = self.run_dir.name

            status.phase = RunPhase(phase)
            status.current_activity = current_activity
            status.active_sessions = active_sessions
            status.blocked_sessions = blocked_sessions
            status.progress_percentage = progress_percentage
            status.obligations_satisfied = obligations_satisfied
            status.obligations_total = obligations_total
            status.summary = summary
            status.updated_at = datetime.utcnow().isoformat()

            self._surface_manager.save_surface("status_summary", status)
        except Exception as e:
            logger.warning(f"更新状态摘要失败: {e}")

    def add_evidence_entry(
        self,
        evidence_id: str,
        evidence_type: str,
        description: str,
        obligation_id: str | None = None,
        scenario_id: str | None = None,
        data: dict | None = None,
        artifacts: list[str] | None = None,
        recorded_by: str | None = None,
    ) -> None:
        """添加证据条目到 Durable EvidenceLog"""
        if not self._surface_manager:
            return

        try:
            evidence_log = self._surface_manager.load_surface(
                "evidence_log", DurableEvidenceLog
            )

            entry = DurableEvidenceEntry(
                id=evidence_id,
                type=EvidenceType(evidence_type),
                description=description,
                recorded_at=datetime.utcnow().isoformat(),
                obligation_id=obligation_id,
                scenario_id=scenario_id,
                data=data or {},
                artifacts=artifacts or [],
                recorded_by=recorded_by,
            )

            evidence_log.record_evidence(entry)
            self._surface_manager.save_surface("evidence_log", evidence_log)
        except Exception as e:
            logger.warning(f"添加证据条目失败: {e}")

    def update_coordination_session(
        self,
        session_id: str,
        state: str = "idle",
        assigned_obligations: list[str] | None = None,
        worktree_path: str | None = None,
        progress_notes: str = "",
    ) -> None:
        """更新协调状态中的会话信息"""
        if not self._surface_manager:
            return

        try:
            coord = self._surface_manager.load_surface(
                "coordination_state", CoordinationState
            )

            if session_id in coord.sessions:
                # 更新现有会话
                coord.update_session(
                    session_id,
                    state=SessionState(state),
                    assigned_obligations=assigned_obligations or coord.sessions[session_id].assigned_obligations,
                    worktree_path=worktree_path or coord.sessions[session_id].worktree_path,
                    progress_notes=progress_notes,
                )
            else:
                # 创建新会话
                session = SessionInfo(
                    session_id=session_id,
                    state=SessionState(state),
                    created_at=datetime.utcnow().isoformat(),
                    assigned_obligations=assigned_obligations or [],
                    worktree_path=worktree_path,
                    progress_notes=progress_notes,
                )
                coord.add_session(session)

            self._surface_manager.save_surface("coordination_state", coord)
        except Exception as e:
            logger.warning(f"更新会话协调状态失败: {e}")

    def assign_obligation_to_session(
        self, session_id: str, obligation_id: str
    ) -> None:
        """将义务分配给特定会话"""
        if not self._surface_manager:
            return

        try:
            coord = self._surface_manager.load_surface(
                "coordination_state", CoordinationState
            )
            coord.assign_obligation(session_id, obligation_id)
            self._surface_manager.save_surface("coordination_state", coord)
        except Exception as e:
            logger.warning(f"分配义务到会话失败: {e}")
