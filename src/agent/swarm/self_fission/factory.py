"""AgentSynthesisFactory — Agent 合成工厂

根据语义分析结果，从模板动态创建专项 Agent 实例。

用法:
    factory = AgentSynthesisFactory(llm_config=config)
    agents = factory.synthesize(
        features=features,
        message_bus=message_bus,
        workdir=workdir,
    )
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .detectors.base import SemanticFeature
from .registry import AgentTemplate, SpecializedAgentRegistry

if TYPE_CHECKING:
    from ...llm import LLMConfig
    from ..message_bus import MessageBus
    from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class AgentSynthesisFactory:
    """Agent 合成工厂

    根据语义特征分析结果，从预设模板动态创建专项 Agent 实例。

    用法:
        factory = AgentSynthesisFactory(llm_config=config)
        agents = factory.synthesize(features, message_bus, workdir)
    """

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        registry: SpecializedAgentRegistry | None = None,
    ) -> None:
        """初始化合成工厂

        参数:
            llm_config: LLM 配置（用于创建 Agent 引擎）
            registry: Agent 模板注册表（为 None 时使用默认）
        """
        self.llm_config = llm_config
        self.registry = registry or SpecializedAgentRegistry()
        self._created_agents: dict[str, BaseAgent] = {}

    def synthesize(
        self,
        features: list[SemanticFeature],
        message_bus: MessageBus,
        workdir: Path,
        max_agents: int = 3,
    ) -> list[BaseAgent]:
        """根据语义特征合成专项 Agent

        参数:
            features: 语义特征列表（来自 SemanticCodeAnalyzer）
            message_bus: 消息总线（用于 Agent 间通信）
            workdir: 工作目录
            max_agents: 最大合成 Agent 数量

        返回:
            合成的 Agent 实例列表
        """
        if not features:
            return []

        # 收集所有满足阈值的标签
        triggered_tags = [f.tag for f in features]

        # 匹配模板
        matched_templates = self.registry.match_templates(triggered_tags)

        if not matched_templates:
            logger.debug("没有匹配的专项 Agent 模板")
            return []

        # 限制数量
        matched_templates = matched_templates[:max_agents]

        # 创建 Agent 实例
        agents: list[BaseAgent] = []
        for template in matched_templates:
            # 检查是否已创建
            if template.name in self._created_agents:
                logger.debug(f"Agent {template.name} 已存在，跳过")
                continue

            # 检查置信度
            max_confidence = self._get_max_confidence_for_tags(features, template.tags)
            if max_confidence < template.min_confidence:
                logger.debug(
                    f"Agent {template.name} 置信度不足 "
                    f"(max={max_confidence:.2f}, min={template.min_confidence:.2f})，跳过"
                )
                continue

            # 创建 Agent
            try:
                agent = self._create_agent_from_template(
                    template=template,
                    message_bus=message_bus,
                    workdir=workdir,
                )
                self._created_agents[template.name] = agent
                agents.append(agent)
                logger.info(f"成功合成专项 Agent: {template.name} (confidence={max_confidence:.2f})")
            except Exception as e:
                logger.error(f"合成 Agent {template.name} 失败: {e}")

        return agents

    def _get_max_confidence_for_tags(
        self,
        features: list[SemanticFeature],
        tags: list[str],
    ) -> float:
        """获取指定标签的最高置信度"""
        tag_set = set(tags)
        max_conf = 0.0
        for f in features:
            if f.tag in tag_set:
                max_conf = max(max_conf, f.confidence)
        return max_conf

    def _create_agent_from_template(
        self,
        template: AgentTemplate,
        message_bus: MessageBus,
        workdir: Path,
    ) -> BaseAgent:
        """从模板创建 Agent 实例

        根据模板的 base_role 创建对应的基础 Agent，
        并使用模板的 system_prompt 覆盖默认系统提示。

        参数:
            template: Agent 模板
            message_bus: 消息总线
            workdir: 工作目录

        返回:
            创建的 Agent 实例
        """
        from ..auditor import AuditorAgent

        agent = AuditorAgent(
            agent_id=f"specialized-{template.name.lower()}",
            message_bus=message_bus,
            workdir=workdir,
            llm_config=self.llm_config,
        )
        # 动态设置系统提示
        agent._system_prompt = template.system_prompt

        return agent
