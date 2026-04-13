"""Evolution Oracle — 元进化先知

负责系统的自我优化决策，是 Brain 模块的核心类。

依赖:
- src/core/session_store.py: 获取历史转录
- src/rag/vector_store.py: 检索模式
- src/memory/manager.py: 记忆管理
"""
from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any

from ..core.project_context import ProjectContext
from .config_patcher import ConfigPatcher, RuntimeConfig
from .entropy import SemanticEntropyAnalyzer
from .memory_adapter import MemoryAdapter
from .models import (
    BrainRule,
    EntropyReport,
    FailureSequence,
    OptimizationAdvice,
    SuccessVector,
)
from .pattern_extractor import PatternExtractor


class EvolutionOracle:
    """元进化先知：负责系统的自我优化决策

    核心能力:
    1. reflect_on_sessions: 分析历史会话，提取优化建议
    2. apply_config_patch: 动态热修补运行时参数
    3. analyze_entropy: 计算代码语义熵
    4. record_success/failure: 记录成功/失败模式
    5. get_brain_rules: 获取生效的 Brain 规则
    6. find_similar_success: 检索相似成功任务

    使用方式:
        oracle = EvolutionOracle()
        advice = await oracle.reflect_on_sessions()
        oracle.apply_config_patch({"MAX_ITERATIONS": 15})
    """

    def __init__(
        self,
        brain_dir: Path | None = None,
        session_dir: Path | None = None,
        project_ctx: ProjectContext | None = None,
    ) -> None:

        if brain_dir is not None:
            self._brain_dir = brain_dir
        elif project_ctx is not None:
            self._brain_dir = project_ctx.brain_dir
        else:
            # 向后兼容：使用相对路径
            self._brain_dir = Path('.clawd') / 'brain'
        self._brain_dir.mkdir(parents=True, exist_ok=True)

        self._adapter = MemoryAdapter(db_dir=self._brain_dir)
        self._pattern_extractor = PatternExtractor(adapter=self._adapter)
        self._entropy_analyzer = SemanticEntropyAnalyzer()
        self._config_patcher = ConfigPatcher(config_dir=self._brain_dir)
        self._session_dir = session_dir

        self._platform = platform.system().lower()

    # ========================================================================
    # 核心接口: 自省分析
    # ========================================================================

    async def reflect_on_sessions(
        self, limit: int = 10
    ) -> list[OptimizationAdvice]:
        """分析最近的会话转录，产出优化建议

        流程:
        1. 提取工具调用失败序列
        2. 识别 LLM 的"认知偏离"点
        3. 产出具体的 Prompt 补丁

        参数:
            limit: 分析最近 N 个会话

        返回:
            OptimizationAdvice 列表
        """
        # 1. 加载最近会话
        sessions = await self._load_recent_sessions(limit)

        # 2. 分析失败模式
        failure_patterns = self._analyze_failures(sessions)

        # 3. 识别认知偏离点
        cognitive_drifts = self._identify_cognitive_drifts(sessions)

        # 4. 生成优化建议
        advice_list: list[OptimizationAdvice] = []

        # 基于失败模式生成建议
        for seq, count in failure_patterns:
            advice = OptimizationAdvice(
                advice_type="prompt_patch",
                description=f"修复 {seq.tool_name} 的 {seq.error_type} 问题",
                prompt_patch=self._generate_failure_advice(seq),
                affected_tools=[seq.tool_name],
                confidence=min(1.0, count / 5.0),
            )
            advice_list.append(advice)

        # 基于认知偏离生成建议
        for drift in cognitive_drifts:
            advice = OptimizationAdvice(
                advice_type="config_tweak",
                description=drift.get("description", ""),
                config_changes=drift.get("config_changes", {}),
                affected_tools=drift.get("affected_tools", []),
                confidence=drift.get("confidence", 0.5),
            )
            advice_list.append(advice)

        # 保存建议
        for a in advice_list:
            self._adapter.save_advice(a)

        return advice_list

    # ========================================================================
    # 核心接口: 配置热修补
    # ========================================================================

    def apply_config_patch(self, patch: dict[str, Any]) -> bool:
        """动态热修补运行时参数

        例如自动调整 MAX_ITERATIONS 或 TOKEN_LIMIT。

        参数:
            patch: 配置键值对 (必须在白名单内)

        返回:
            是否成功
        """
        result = self._config_patcher.apply_patch(patch)
        return result.success

    def get_config(self) -> RuntimeConfig:
        """获取当前运行时配置"""
        return self._config_patcher.get_config()

    def reset_config(self) -> bool:
        """重置配置为默认值"""
        result = self._config_patcher.reset_to_defaults()
        return result.success

    # ========================================================================
    # 语义熵分析
    # ========================================================================

    def analyze_entropy(self, target: Path) -> list[EntropyReport]:
        """计算目标代码的语义熵

        参数:
            target: 文件或目录路径

        返回:
            熵报告列表
        """
        if target.is_file():
            report = self._entropy_analyzer.analyze_file(target)
            self._adapter.save_entropy_report(report)
            return [report]
        elif target.is_dir():
            reports = self._entropy_analyzer.analyze_directory(target)
            for r in reports:
                self._adapter.save_entropy_report(r)
            return reports
        return []

    def get_high_entropy_files(
        self, threshold: float = 0.5
    ) -> list[EntropyReport]:
        """获取高熵文件列表"""
        return self._adapter.get_high_entropy_files(threshold)

    # ========================================================================
    # 模式记录
    # ========================================================================

    def record_success(
        self,
        goal: str,
        steps: list[str],
        tools_used: list[str],
        tool_feedback: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> SuccessVector:
        """记录成功任务"""
        return self._pattern_extractor.record_success(
            goal=goal,
            steps=steps,
            tools_used=tools_used,
            tool_feedback=tool_feedback or [],
            tags=tags or [],
        )

    def record_failure(
        self,
        tool_name: str,
        error_type: str,
        error_msg: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[bool, BrainRule | None]:
        """记录失败并检查是否形成模式"""
        return self._pattern_extractor.record_failure(
            tool_name=tool_name,
            error_type=error_type,
            error_msg=error_msg,
            context=context or {},
        )

    # ========================================================================
    # 规则与建议查询
    # ========================================================================

    def get_brain_rules(
        self, tool_name: str | None = None
    ) -> list[BrainRule]:
        """获取生效的 Brain 规则"""
        return self._pattern_extractor.get_active_rules(tool_name)

    def find_similar_success(
        self, goal: str, top_k: int = 3
    ) -> list[SuccessVector]:
        """检索相似成功任务"""
        return self._pattern_extractor.find_similar_success(goal, top_k)

    def get_optimization_advice(
        self, limit: int = 10
    ) -> list[OptimizationAdvice]:
        """获取优化建议"""
        return self._adapter.get_advice(limit)

    def get_failure_sequences(
        self, min_occurrences: int = 3
    ) -> list[FailureSequence]:
        """获取失败序列"""
        return self._adapter.get_failure_sequences(min_occurrences)

    def get_config_info(self) -> dict[str, dict[str, Any]]:
        """获取可修补参数信息"""
        return self._config_patcher.get_patchable_params()

    # ========================================================================
    # 内部方法
    # ========================================================================

    async def _load_recent_sessions(
        self, limit: int
    ) -> list[dict[str, Any]]:
        """加载最近的会话转录"""
        sessions: list[dict[str, Any]] = []

        # 尝试从 session_store 加载
        if self._session_dir and self._session_dir.exists():
            session_files = sorted(
                self._session_dir.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for f in session_files[:limit]:
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    sessions.append(data)
                except (json.JSONDecodeError, ValueError):
                    continue

        # 如果没有 session 数据，返回空列表
        return sessions

    def _analyze_failures(
        self, sessions: list[dict[str, Any]]
    ) -> list[tuple[FailureSequence, int]]:
        """分析会话中的失败模式

        返回:
            [(FailureSequence, 出现次数)] 列表
        """
        # 从已存储的失败序列中获取
        all_sequences = self._adapter.get_failure_sequences(min_occurrences=1)
        return [(seq, seq.occurrences) for seq in all_sequences]

    def _identify_cognitive_drifts(
        self, sessions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """识别 LLM 的"认知偏离"点

        认知偏离指 LLM 在任务执行过程中偏离正确路径的模式。
        """
        drifts: list[dict[str, Any]] = []

        for session in sessions:
            messages = session.get("messages", [])
            error_count = 0
            turn_count = session.get("turn_count", 0)

            # 统计错误消息
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "assistant" and any(
                    err in content.lower()
                    for err in ["error", "failed", "failed to", "cannot"]
                ):
                    error_count += 1

            # 如果错误率过高，识别为认知偏离
            if turn_count > 0 and error_count / turn_count > 0.3:
                drifts.append({
                    "description": (
                        f"会话错误率 {error_count}/{turn_count} > 30%，"
                        "建议调整 Temperature 或增加 System Prompt 约束"
                    ),
                    "config_changes": {"TEMPERATURE": 0.5},
                    "affected_tools": [],
                    "confidence": min(1.0, error_count / turn_count),
                })

        return drifts

    def _generate_failure_advice(self, seq: FailureSequence) -> str:
        """生成失败模式的 Prompt 补丁"""
        return (
            f"[BRAIN ADVICE]: {seq.tool_name} 已连续 {seq.occurrences} 次出现 "
            f"{seq.error_type} 错误。\n"
            f"最近错误: {seq.error_messages[-1] if seq.error_messages else 'N/A'}\n"
            f"建议: 在执行 {seq.tool_name} 前，检查环境配置并准备备选方案。"
        )
