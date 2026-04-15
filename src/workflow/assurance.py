"""质保计划模块 - 负责定义验证场景、验证工具 (Oracle) 和准入策略 (汲取 GoalX AssurancePlan)"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("workflow.assurance")

@dataclass
class AssuranceScenario:
    """验证场景"""
    id: str
    description: str
    command: str  # 验证命令 (如 'pytest tests/test_auth.py')
    expected_exit_code: int = 0
    required_evidence: list[str] = field(default_factory=lambda: ["stdout"])
    severity: str = "required" # 'quick' | 'required' | 'full'
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "command": self.command,
            "expected_exit_code": self.expected_exit_code,
            "required_evidence": self.required_evidence,
            "severity": self.severity,
            "status": self.status
        }

class AssuranceManager:
    """质保管理器 (汲取 GoalX AssurancePlan 管理逻辑)"""

    def __init__(self, workdir: Path, run_id: str = "latest", surface_manager: Any | None = None):
        self.workdir = workdir
        self.plan_file = workdir / ".clawd" / "runs" / run_id / "assurance-plan.json"
        self.scenarios: list[AssuranceScenario] = []
        self.version = 1
        self.surface_manager = surface_manager

    def add_scenario(self, scenario: AssuranceScenario):
        """添加验证场景"""
        self.scenarios.append(scenario)

    def generate_from_tasks(self, tasks: list[Any]):
        """根据任务自动推导验证场景"""
        for task in tasks:
            # 如果任务描述中包含测试建议
            if "测试" in task.description or "test" in task.description.lower():
                # 尝试提取命令
                import re
                cmd_match = re.search(r'`(pytest[^`]*)`', task.description)
                cmd = cmd_match.group(1) if cmd_match else f"pytest --ids {task.task_id}"

                self.add_scenario(AssuranceScenario(
                    id=f"verify-{task.task_id}",
                    description=f"验证任务 {task.task_id} 的修复效果",
                    command=cmd
                ))

    def save(self):
        """保存质保计划"""
        data = {
            "version": self.version,
            "updated_at": datetime.utcnow().isoformat(),
            "scenarios": [s.to_dict() for s in self.scenarios]
        }
        self.plan_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.plan_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self) -> bool:
        """加载已有的质保计划"""
        if not self.plan_file.exists():
            return False
        try:
            with open(self.plan_file, encoding="utf-8") as f:
                data = json.load(f)
                self.scenarios = []
                for s in data.get("scenarios", []):
                    self.scenarios.append(AssuranceScenario(**s))
                return True
        except Exception as e:
            logger.error(f"加载质保计划失败: {e}")
            return False

    async def run_scenarios_for_task(self, task_id: str, workdir: Path) -> bool:
        """为特定任务运行所有关联的验证场景"""
        relevant_scenarios = [s for s in self.scenarios if s.id == f"verify-{task_id}"]
        if not relevant_scenarios:
            logger.info(f"任务 {task_id} 没有关联的验证场景，跳过。")
            return True

        import os
        import shlex
        import subprocess

        # [Durable Surface] 获取 Durable AssurancePlan
        durable_plan = None
        if self.surface_manager:
            try:
                from ..core.durable.surfaces.assurance_plan import AssurancePlan as DurableAssurancePlan
                from ..core.durable.surfaces.assurance_plan import AssuranceScenario as DurableScenario
                from ..core.durable.surfaces.assurance_plan import VerificationMethod
                durable_plan = self.surface_manager.load_surface("assurance_plan", DurableAssurancePlan)
            except Exception as e:
                logger.warning(f"无法加载 Durable AssurancePlan: {e}")

        # 定义允许执行的命令白名单 (汲取 GoalX 命令加固)
        ALLOWED_COMMANDS = {"pytest", "python", "npm", "make", "ruff", "black"}

        all_passed = True
        for scenario in relevant_scenarios:
            logger.info(f"正在执行验证场景: {scenario.description} (命令: {scenario.command})")
            scenario.status = "running"

            try:
                # 汲取 GoalX: 在子进程中执行验证命令 (修复命令注入风险)
                # 使用 shlex.split 将命令字符串安全地拆分为参数列表，并禁用 shell=True
                cmd_parts = shlex.split(scenario.command)
                if not cmd_parts:
                    raise ValueError("空的验证命令")

                # 获取基础命令名 (如 'pytest')
                base_cmd = os.path.basename(cmd_parts[0])
                if base_cmd not in ALLOWED_COMMANDS:
                    logger.error(f"拒绝执行未授权命令: {base_cmd}")
                    scenario.status = "error"
                    all_passed = False
                    continue

                process = subprocess.run(
                    cmd_parts,
                    shell=False,
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    timeout=300 # 5分钟超时
                )

                passed = process.returncode == scenario.expected_exit_code

                # 记录证据 (简化版)
                evidence_log_content = f"Command: {scenario.command}\nExit Code: {process.returncode}\nStdout: {process.stdout}\nStderr: {process.stderr}"
                evidence_path = workdir / f"assurance_{scenario.id}.log"
                evidence_path.write_text(evidence_log_content, encoding="utf-8")

                if passed:
                    scenario.status = "passed"
                    logger.info(f"验证场景 {scenario.id} 通过。")
                else:
                    scenario.status = "failed"
                    logger.error(f"验证场景 {scenario.id} 失败! 输出:\n{process.stderr or process.stdout}")
                    all_passed = False

                # [Durable Surface] 更新 Durable AssurancePlan 和 EvidenceLog
                if durable_plan and self.surface_manager:
                    try:
                        # 确保场景存在于 Durable Plan 中
                        if scenario.id not in durable_plan.scenarios:
                            from ..core.durable.surfaces.assurance_plan import AssuranceScenario as DurableScenario
                            from ..core.durable.surfaces.assurance_plan import VerificationMethod
                            durable_plan.add_scenario(DurableScenario(
                                id=scenario.id,
                                name=f"Scenario {scenario.id}",
                                description=scenario.description,
                                method=VerificationMethod.UNIT_TEST, # 默认为单元测试
                                test_command=scenario.command,
                                obligation_ids=[task_id]
                            ))

                        durable_plan.execute_scenario(scenario.id, passed, evidence_log_content)
                        self.surface_manager.save_surface("assurance_plan", durable_plan)

                        # 记录到 EvidenceLog
                        from ..core.durable.surfaces.evidence_log import EvidenceEntry as DurableEvidenceEntry
                        from ..core.durable.surfaces.evidence_log import EvidenceLog as DurableEvidenceLog
                        from ..core.durable.surfaces.evidence_log import EvidenceType
                        evidence_log = self.surface_manager.load_surface("evidence_log", DurableEvidenceLog)
                        entry = DurableEvidenceEntry(
                            id=f"ev-{scenario.id}-{int(datetime.utcnow().timestamp())}",
                            type=EvidenceType.TEST_RESULT,
                            description=f"Automated verification for {scenario.id}",
                            recorded_at=datetime.utcnow().isoformat(),
                            obligation_id=task_id,
                            scenario_id=scenario.id,
                            data={"exit_code": process.returncode, "command": scenario.command},
                            artifacts=[str(evidence_path.relative_to(self.workdir) if evidence_path.is_relative_to(self.workdir) else evidence_path)],
                            recorded_by="assurance_manager",
                            source_command=scenario.command
                        )
                        evidence_log.record_evidence(entry)
                        self.surface_manager.save_surface("evidence_log", evidence_log)
                    except Exception as de:
                        logger.warning(f"同步 Durable Surfaces 失败: {de}")

            except Exception as e:
                logger.error(f"执行验证场景 {scenario.id} 出错: {e}")
                scenario.status = "error"
                all_passed = False

        return all_passed
