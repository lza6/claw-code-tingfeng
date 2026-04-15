"""
Agent Prompts - Agent Prompt 模板库

从 oh-my-codex-main/prompts/ 目录转换而来。
提供所有 Agent 角色的 prompt 模板。
"""

from pathlib import Path
from typing import Optional

# Prompt 目录
PROMPTS_DIR = Path(__file__).parent

# Prompt 文件映射
PROMPT_FILES: dict[str, str] = {
    "analyst": "analyst.md",
    "api-reviewer": "api-reviewer.md",
    "architect": "architect.md",
    "build-fixer": "build-fixer.md",
    "code-reviewer": "code-reviewer.md",
    "code-simplifier": "code-simplifier.md",
    "critic": "critic.md",
    "debugger": "debugger.md",
    "dependency-expert": "dependency-expert.md",
    "designer": "designer.md",
    "executor": "executor.md",
    "explore": "explore.md",
    "explore-harness": "explore-harness.md",
    "git-master": "git-master.md",
    "information-architect": "information-architect.md",
    "performance-reviewer": "performance-reviewer.md",
    "planner": "planner.md",
    "product-analyst": "product-analyst.md",
    "product-manager": "product-manager.md",
    "qa-tester": "qa-tester.md",
    "quality-reviewer": "quality-reviewer.md",
    "quality-strategist": "quality-strategist.md",
    "researcher": "researcher.md",
    "security-reviewer": "security-reviewer.md",
    "sisyphus-lite": "sisyphus-lite.md",
    "style-reviewer": "style-reviewer.md",
    "team-executor": "team-executor.md",
    "team-orchestrator": "team-orchestrator.md",
    "test-engineer": "test-engineer.md",
    "ux-researcher": "ux-researcher.md",
    "verifier": "verifier.md",
    "vision": "vision.md",
    "writer": "writer.md",
}

# Prompt 缓存
_prompt_cache: dict[str, str] = {}


def get_prompt(agent_name: str) -> Optional[str]:
    """获取指定 Agent 的 Prompt

    Args:
        agent_name: Agent 名称 (如 "analyst", "planner" 等)

    Returns:
        Prompt 字符串，如果不存在则返回 None
    """
    if agent_name in _prompt_cache:
        return _prompt_cache[agent_name]

    filename = PROMPT_FILES.get(agent_name)
    if not filename:
        return None

    prompt_path = PROMPTS_DIR / filename
    if not prompt_path.exists():
        return None

    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()
        _prompt_cache[agent_name] = content
        return content
    except Exception:
        return None


def load_prompts() -> dict[str, str]:
    """加载所有可用的 Prompts

    Returns:
        Agent 名称到 Prompt 内容的字典
    """
    prompts = {}
    for agent_name in PROMPT_FILES.keys():
        prompt = get_prompt(agent_name)
        if prompt:
            prompts[agent_name] = prompt
    return prompts


def list_available_prompts() -> list[str]:
    """列出所有可用的 Prompt 名称

    Returns:
        可用的 Agent 名称列表
    """
    return list(PROMPT_FILES.keys())


def clear_prompt_cache() -> None:
    """清空 Prompt 缓存"""
    global _prompt_cache
    _prompt_cache = {}


# ===== 导出 =====
__all__ = [
    "get_prompt",
    "load_prompts",
    "list_available_prompts",
    "clear_prompt_cache",
    "PROMPT_FILES",
]