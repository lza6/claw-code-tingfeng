"""Swarm — 多 Agent 协作模块

组件:
- SwarmEngine: 主引擎
- SwarmConfig: 配置
- OrchestratorAgent: 编排器
- AuditorAgent: 审计师
- QualityGate: 质量门禁
- MessageBus: 消息总线
- TaskRegistry: 任务注册
- BaseAgent: Agent 基类

使用示例:
    from src.agent.swarm import SwarmEngine, SwarmConfig

    config = SwarmConfig(max_workers=2, enable_auditor=True)
    engine = SwarmEngine(config=config, workdir=Path.cwd())
    result = await engine.run("实现用户认证功能")
"""
from __future__ import annotations

from .auditor import AuditFinding, AuditorAgent, AuditReport
from .base_agent import BaseAgent
from .config import SwarmConfig
from .engine import SwarmEngine, SwarmResult
from .message_bus import AgentMessage, MessageBus, MessageType
from .orchestrator import OrchestratorAgent, TaskDecomposition
from .quality_gate import GateResult, QualityGate
from .roles import ROLE_DESCRIPTIONS, ROLE_SYSTEM_PROMPTS, AgentRole
from .task_registry import SubTask, TaskRegistry, TaskStatus

__all__ = [
    'ROLE_DESCRIPTIONS',
    'ROLE_SYSTEM_PROMPTS',
    'AgentMessage',
    'AgentRole',
    'AuditFinding',
    'AuditReport',
    'AuditorAgent',
    'BaseAgent',
    'GateResult',
    'MessageBus',
    'MessageType',
    'OrchestratorAgent',
    'QualityGate',
    'SubTask',
    'SwarmConfig',
    'SwarmEngine',
    'SwarmResult',
    'TaskDecomposition',
    'TaskRegistry',
    'TaskStatus',
]
