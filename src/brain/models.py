"""Brain 数据模型

定义 Brain 模块的核心数据结构:
- OptimizationAdvice: 优化建议
- BrainRule: 自动生成的强制规则
- EntropyReport: 语义熵分析报告
- ConfigPatchResult: 配置热修补结果
- FailureSequence: 失败序列模式
- SuccessVector: 成功特征向量
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrainRule:
    """Brain 自动生成的强制规则

    当检测到重复失败模式时自动生成，例如:
    "[BRAIN-RULE]: 在 Windows 环境下修改 .sh 文件时，必须显式检查换行符格式。"
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    rule_text: str = ""
    trigger_error: str = ""        # 触发的错误类型
    trigger_count: int = 0         # 触发次数
    platform: str = ""             # 适用平台 (windows, linux, darwin)
    tool_name: str = ""            # 关联工具
    severity: str = "warning"      # warning, critical
    created_at: float = field(default_factory=time.time)
    enforced: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule_text": self.rule_text,
            "trigger_error": self.trigger_error,
            "trigger_count": self.trigger_count,
            "platform": self.platform,
            "tool_name": self.tool_name,
            "severity": self.severity,
            "created_at": self.created_at,
            "enforced": self.enforced,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrainRule:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            rule_text=data.get("rule_text", ""),
            trigger_error=data.get("trigger_error", ""),
            trigger_count=data.get("trigger_count", 0),
            platform=data.get("platform", ""),
            tool_name=data.get("tool_name", ""),
            severity=data.get("severity", "warning"),
            created_at=data.get("created_at", time.time()),
            enforced=data.get("enforced", True),
        )


@dataclass
class FailureSequence:
    """工具调用失败序列

    记录连续失败的工具调用模式，用于识别系统性问题。
    """
    tool_name: str = ""
    error_type: str = ""
    error_messages: list[str] = field(default_factory=list)
    occurrences: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    context: dict[str, Any] = field(default_factory=dict)

    def record_failure(self, error_type: str, error_msg: str) -> None:
        """记录一次失败"""
        self.error_type = error_type
        self.error_messages.append(error_msg)
        self.occurrences += 1
        self.last_seen = time.time()

    @property
    def is_pattern(self) -> bool:
        """是否已形成模式 (连续 3+ 次同类错误)"""
        return self.occurrences >= 3


@dataclass
class SuccessVector:
    """成功特征向量

    将成功的任务按照 "目标 -> 步骤序列 -> 工具反馈" 进行向量化，
    用于未来相似任务检索。
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    goal: str = ""
    steps: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    tool_feedback: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    embedding: list[float] = field(default_factory=list)
    success_score: float = 1.0
    created_at: float = field(default_factory=time.time)
    access_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "steps": self.steps,
            "tools_used": self.tools_used,
            "tool_feedback": self.tool_feedback,
            "tags": self.tags,
            "embedding": self.embedding,
            "success_score": self.success_score,
            "created_at": self.created_at,
            "access_count": self.access_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SuccessVector:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            goal=data.get("goal", ""),
            steps=data.get("steps", []),
            tools_used=data.get("tools_used", []),
            tool_feedback=data.get("tool_feedback", []),
            tags=data.get("tags", []),
            embedding=data.get("embedding", []),
            success_score=data.get("success_score", 1.0),
            created_at=data.get("created_at", time.time()),
            access_count=data.get("access_count", 0),
        )

    def access(self) -> None:
        """记录访问"""
        self.access_count += 1


@dataclass
class OptimizationAdvice:
    """优化建议 — reflect_on_sessions 的产出

    包含具体的 Prompt 补丁、配置调整或规则生成建议。
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    advice_type: str = ""            # prompt_patch, config_tweak, rule_generation
    description: str = ""
    prompt_patch: str = ""           # 具体的 Prompt 补丁文本
    config_changes: dict[str, Any] = field(default_factory=dict)
    affected_tools: list[str] = field(default_factory=list)
    confidence: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "advice_type": self.advice_type,
            "description": self.description,
            "prompt_patch": self.prompt_patch,
            "config_changes": self.config_changes,
            "affected_tools": self.affected_tools,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OptimizationAdvice:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            advice_type=data.get("advice_type", ""),
            description=data.get("description", ""),
            prompt_patch=data.get("prompt_patch", ""),
            config_changes=data.get("config_changes", {}),
            affected_tools=data.get("affected_tools", []),
            confidence=data.get("confidence", 0.0),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class EntropyReport:
    """语义熵分析报告

    计算代码库的"语义熵"，预测哪些模块最容易产生潜在 Bug。
    """
    file_path: str = ""
    entropy_score: float = 0.0       # 0.0 (低熵/稳定) ~ 1.0 (高熵/不稳定)
    risk_level: str = "low"          # low, medium, high, critical
    contributing_factors: list[str] = field(default_factory=list)
    hotspots: list[str] = field(default_factory=list)  # 高风险函数/类
    recommendations: list[str] = field(default_factory=list)
    analyzed_at: float = field(default_factory=time.time)

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in ("high", "critical") or self.entropy_score > 0.7

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "entropy_score": self.entropy_score,
            "risk_level": self.risk_level,
            "contributing_factors": self.contributing_factors,
            "hotspots": self.hotspots,
            "recommendations": self.recommendations,
            "analyzed_at": self.analyzed_at,
        }


@dataclass
class ConfigPatchResult:
    """配置热修补结果"""
    success: bool = False
    patched_params: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    timestamp: float = field(default_factory=time.time)
