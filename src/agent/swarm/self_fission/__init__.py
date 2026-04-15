"""Swarm 自裂变模块 — 基于代码语义分析的专项 Agent 自动合成

核心组件:
- SemanticCodeAnalyzer: 语义代码分析器
- FeatureDetector: 特征检测器协议
- AgentSynthesisFactory: Agent 合成工厂
- SpecializedAgentRegistry: 专项 Agent 角色模板库
- RLExperienceHub: 强化学习经验回传中心

用法:
    from src.agent.swarm.self_fission import SemanticCodeAnalyzer, AgentSynthesisFactory
    from src.agent.swarm.self_fission import RLExperienceHub

    analyzer = SemanticCodeAnalyzer()
    features = await analyzer.analyze(goal, workdir)

    factory = AgentSynthesisFactory(llm_config=config)
    agents = factory.synthesize(features, message_bus, workdir)

    # 经验回传
    hub = RLExperienceHub()
    hub.record_task_experience("实现 JWT 认证", "使用 PyJWT", success=True)
    best = hub.find_best_practices("认证")
"""
from .analyzer import SemanticCodeAnalyzer, SemanticFeature
from .detectors.base import CodeContext, FeatureDetector
from .factory import AgentSynthesisFactory
from .registry import SPECIALIZED_AGENT_TEMPLATES, SpecializedAgentRegistry
from .rl_experience import FailurePattern, RLExperienceHub, TaskExperience

__all__ = [
    'SPECIALIZED_AGENT_TEMPLATES',
    'AgentSynthesisFactory',
    'CodeContext',
    'FailurePattern',
    'FeatureDetector',
    'RLExperienceHub',
    'SemanticCodeAnalyzer',
    'SemanticFeature',
    'SpecializedAgentRegistry',
    'TaskExperience',
]
