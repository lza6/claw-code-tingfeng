"""Swarm 配置"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SwarmConfig:
    """Swarm 配置"""

    # Agent 配置
    max_workers: int = 3              # 最大 Worker 数量
    enable_auditor: bool = True       # 是否启用审计
    enable_reviewer: bool = True      # 是否启用审查
    enable_integrator: bool = True    # 是否启用集成

    # 质量门禁配置
    max_audit_retries: int = 2        # 审计驳回后的最大重试
    require_tests: bool = True        # 强制要求测试
    require_docs: bool = False        # 强制要求文档
    lint_strict: bool = True          # 严格 Lint 检查

    # 超时配置
    worker_timeout_seconds: int = 300  # Worker 超时
    audit_timeout_seconds: int = 60    # 审计超时

    # 回退策略
    fallback_to_single_agent: bool = True  # Swarm 失败时回退单 Agent

    # 模型配置
    orchestrator_model: str | None = None  # Orchestrator 专用模型
    auditor_model: str | None = None       # Auditor 专用模型
    worker_model: str | None = None        # Worker 专用模型

    # 自裂变配置 (Swarm Self-Fission)
    enable_self_fission: bool = True           # 启用自裂变
    max_specialized_agents: int = 3            # 最大专项 Agent 数量
    detection_threshold: float = 0.5           # 特征检测置信度阈值

    # 经验回传配置 (RL-Experience Hub)
    enable_experience_retrieval: bool = True   # 启用经验检索
    max_experience_hints: int = 5              # 最大经验提示数量
    experience_min_success_rate: float = 0.6   # 经验最低成功率阈值

    # Auditor 配置
    auditor_llm_review_batch_size: int = 3     # LLM 审查批次大小
    auditor_max_line_length: int = 120         # 最大行长度

    # [性能优化 v0.37.0] 并发控制
    max_concurrent_tasks: int = 5              # 最大并发任务数，避免 API 限流
    enable_memory_optimization: bool = True    # 启用内存优化 (结果截断)
    max_dependency_context_length: int = 2000  # 依赖上下文最大长度

    # [Phase 4] 资源与协作配置
    enable_runtime_host: bool = True           # 启用运行时托管监控
    enable_coordination_state: bool = True      # 启用协作状态持久化
    resource_memory_threshold_mb: float = 4096.0 # 内存警告阈值
    resource_cpu_threshold: float = 85.0         # CPU 警告阈值
