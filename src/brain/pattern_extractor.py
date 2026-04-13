"""Pattern Extractor — 模式提取协议

实现:
- 3.1 成功特征向量 (Success Embedding)
- 3.2 避坑指南自动生成

当 FileEditTool 在某个平台上连续 3 次报错 SyntaxError，
自动生成强制规则。
"""
from __future__ import annotations

import platform
from typing import Any

from .memory_adapter import MemoryAdapter
from .models import (
    BrainRule,
    FailureSequence,
    OptimizationAdvice,
    SuccessVector,
)

# 错误类型到规则的映射模板
RULE_TEMPLATES: dict[str, str] = {
    "SyntaxError": (
        "[BRAIN-RULE]: 在 {platform} 环境下修改 {file_type} 文件时，"
        "必须检查语法错误，避免 SyntaxError。"
    ),
    "PermissionError": (
        "[BRAIN-RULE]: 在 {platform} 环境下访问 {file_type} 文件时，"
        "必须先检查文件权限，避免 PermissionError。"
    ),
    "FileNotFoundError": (
        "[BRAIN-RULE]: 在 {platform} 环境下操作文件前，"
        "必须验证文件路径存在，避免 FileNotFoundError。"
    ),
    "TimeoutError": (
        "[BRAIN-RULE]: 在 {platform} 环境下执行命令时，"
        "必须设置合理超时，避免 TimeoutError。"
    ),
    "ModuleNotFoundError": (
        "[BRAIN-RULE]: 在 {platform} 环境下导入模块失败时，"
        "应先检查依赖是否已安装: {module_name}。"
    ),
}


class PatternExtractor:
    """模式提取器

    从工具执行结果中提取成功/失败模式，
    自动生成 Brain 规则和优化建议。
    """

    def __init__(self, adapter: MemoryAdapter | None = None) -> None:
        self._adapter = adapter or MemoryAdapter()
        self._platform = platform.system().lower()

    # ========================================================================
    # 成功特征向量
    # ========================================================================

    def record_success(
        self,
        goal: str,
        steps: list[str],
        tools_used: list[str],
        tool_feedback: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> SuccessVector:
        """记录成功任务并生成特征向量"""
        vec = SuccessVector(
            goal=goal,
            steps=steps,
            tools_used=tools_used,
            tool_feedback=tool_feedback or [],
            tags=tags or [],
        )
        # 计算简单 embedding (基于工具使用模式)
        vec.embedding = self._compute_success_embedding(vec)
        self._adapter.save_success_vector(vec)
        return vec

    def find_similar_success(
        self, goal: str, top_k: int = 3
    ) -> list[SuccessVector]:
        """检索相似成功任务

        使用简单的 Jaccard 相似度进行检索。
        """
        all_vectors = self._adapter.get_success_vectors(top_k=50)
        query_tokens = set(goal.lower().split())

        scored: list[tuple[float, SuccessVector]] = []
        for vec in all_vectors:
            goal_tokens = set(vec.goal.lower().split())
            similarity = self._jaccard_similarity(query_tokens, goal_tokens)
            scored.append((similarity, vec))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [vec for _, vec in scored[:top_k]]

    # ========================================================================
    # 失败模式提取
    # ========================================================================

    def record_failure(
        self,
        tool_name: str,
        error_type: str,
        error_msg: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[bool, BrainRule | None]:
        """记录工具失败并检查是否形成模式

        返回:
            (是否已形成模式, 生成的规则或 None)
        """
        # 获取或创建失败序列
        seq_id = f"{tool_name}:{error_type}"
        existing = self._adapter.get_failure_sequences(min_occurrences=1)
        seq = None
        for s in existing:
            if f"{s.tool_name}:{s.error_type}" == seq_id:
                seq = s
                break

        if seq is None:
            seq = FailureSequence(
                tool_name=tool_name,
                error_type=error_type,
                context=context or {},
            )

        seq.record_failure(error_type, error_msg)
        self._adapter.save_failure_sequence(seq)

        # 检查是否形成模式
        if seq.is_pattern:
            rule = self._generate_rule_from_failure(seq)
            if rule:
                self._adapter.save_rule(rule)
                return True, rule

        return False, None

    def get_active_rules(
        self, tool_name: str | None = None
    ) -> list[BrainRule]:
        """获取当前生效的 Brain 规则"""
        return self._adapter.get_rules(
            platform=self._platform,
            tool_name=tool_name,
        )

    # ========================================================================
    # 优化建议生成
    # ========================================================================

    def generate_optimization_advice(
        self,
        session_transcripts: list[dict[str, Any]] | None = None,
    ) -> list[OptimizationAdvice]:
        """基于历史数据生成优化建议

        分析最近的失败模式，生成 Prompt 补丁或配置调整建议。
        """
        advice_list: list[OptimizationAdvice] = []

        # 1. 分析高频失败模式
        failures = self._adapter.get_failure_sequences(min_occurrences=2)
        for seq in failures:
            advice = OptimizationAdvice(
                advice_type="prompt_patch",
                description=f"避免 {seq.tool_name} 的 {seq.error_type} 错误",
                prompt_patch=self._generate_prompt_patch(seq),
                affected_tools=[seq.tool_name],
                confidence=min(1.0, seq.occurrences / 5.0),
            )
            advice_list.append(advice)

        # 2. 分析成功特征向量
        successes = self._adapter.get_success_vectors(top_k=10)
        if successes:
            common_tools = self._find_common_tools(successes)
            if common_tools:
                advice = OptimizationAdvice(
                    advice_type="config_tweak",
                    description=f"优先使用高频成功工具: {', '.join(common_tools)}",
                    config_changes={"preferred_tools": common_tools},
                    affected_tools=common_tools,
                    confidence=0.8,
                )
                advice_list.append(advice)

        # 3. 保存建议
        for a in advice_list:
            self._adapter.save_advice(a)

        return advice_list

    # ========================================================================
    # 内部方法
    # ========================================================================

    def _compute_success_embedding(self, vec: SuccessVector) -> list[float]:
        """计算成功向量 embedding (简化版 TF-IDF)"""
        # 使用工具名称的 one-hot 编码作为简化 embedding
        all_tools = [
            "FileReadTool", "FileEditTool", "BashTool",
            "GrepTool", "GlobTool",
        ]
        embedding = [0.0] * len(all_tools)
        for i, tool in enumerate(all_tools):
            if tool in vec.tools_used:
                embedding[i] = 1.0
        return embedding

    def _jaccard_similarity(
        self, set_a: set[str], set_b: set[str]
    ) -> float:
        """计算 Jaccard 相似度"""
        if not set_a and not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _generate_rule_from_failure(
        self, seq: FailureSequence
    ) -> BrainRule | None:
        """从失败模式生成 Brain 规则"""
        error_type = seq.error_type
        template = RULE_TEMPLATES.get(error_type)

        if not template:
            # 通用规则模板
            template = (
                f"[BRAIN-RULE]: {seq.tool_name} 在 {self._platform} 环境下"
                f"连续出现 {seq.error_type} 时，应切换策略或检查环境配置。"
            )
            return BrainRule(
                rule_text=template,
                trigger_error=error_type,
                trigger_count=seq.occurrences,
                platform=self._platform,
                tool_name=seq.tool_name,
                severity="warning",
            )

        # 填充模板
        file_type = seq.context.get("file_type", "目标")
        module_name = seq.context.get("module_name", "未知")
        rule_text = template.format(
            platform=self._platform,
            file_type=file_type,
            module_name=module_name,
        )

        return BrainRule(
            rule_text=rule_text,
            trigger_error=error_type,
            trigger_count=seq.occurrences,
            platform=self._platform,
            tool_name=seq.tool_name,
            severity="warning" if seq.occurrences < 5 else "critical",
        )

    def _generate_prompt_patch(self, seq: FailureSequence) -> str:
        """生成 Prompt 补丁文本"""
        return (
            f"注意: {seq.tool_name} 在 {self._platform} 环境下容易触发 "
            f"{seq.error_type} (已出现 {seq.occurrences} 次)。\n"
            f"最近错误: {seq.error_messages[-1] if seq.error_messages else 'N/A'}\n"
            f"建议: 在执行前检查环境配置，准备好备选方案。"
        )

    def _find_common_tools(
        self, vectors: list[SuccessVector]
    ) -> list[str]:
        """找出高频成功工具"""
        tool_counts: dict[str, int] = {}
        for vec in vectors:
            for tool in vec.tools_used:
                tool_counts[tool] = tool_counts.get(tool, 0) + 1

        # 返回使用次数超过一半的工具
        threshold = len(vectors) // 2
        return [
            tool for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1])
            if count >= threshold
        ]
