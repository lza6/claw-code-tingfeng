"""
Prompt Guidance Contract - 提示词指导合约

从 oh-my-codex-main/src/hooks/prompt-guidance-contract.ts 转换而来。
定义提示词模板合约验证。
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class GuidanceSurfaceContract:
    """指导表面合约"""
    id: str
    path: str
    required_patterns: list[re.Pattern]


def rx(pattern: str) -> re.Pattern:
    """创建正则表达式"""
    return re.compile(pattern, re.I)


# ===== 合约模式 =====

ROOT_TEMPLATE_PATTERNS = [
    rx(r"compact, information-dense responses"),
    rx(r"clear, low-risk, reversible next steps"),
    rx(r"local overrides?.*non-conflicting instructions"),
    rx(r"Choose the lane before acting"),
    rx(r"Solo execute"),
    rx(r"Outside active `team`/`swarm` mode, use `executor`"),
    rx(r"Reserve `worker` strictly for active `team`/`swarm` sessions"),
    rx(r"Leader responsibilities"),
    rx(r"Worker responsibilities"),
    rx(r"Stop / escalate"),
    rx(r"Default update/final shape"),
    rx(r"do not skip prerequisites|task is grounded and verified"),
    rx(r"concise evidence summaries"),
]

CORE_ROLE_PATTERNS = {
    "executor": [
        rx(r"compact, information-dense outputs"),
        rx(r"local overrides?.*non-conflicting constraints"),
        rx(r"task is grounded and verified"),
    ],
    "planner": [
        rx(r"compact, information-dense plan summaries"),
        rx(r"local overrides?.*non-conflicting constraints"),
        rx(r"plan is grounded in evidence"),
    ],
    "verifier": [
        rx(r"concise, evidence-dense summaries"),
        rx(r"verdict is grounded"),
        rx(r"non-conflicting acceptance criteria"),
    ],
}

WAVE_TWO_PATTERNS = [
    rx(r"Default final-output shape: concise and evidence-dense"),
    rx(r"Treat newer user task updates as local overrides"),
    rx(r"user says `continue`"),
]

CATALOG_PATTERNS = [
    rx(r"Default final-output shape: concise and evidence-dense"),
    rx(r"Treat newer user task updates as local overrides"),
    rx(r"user says `continue`"),
]

SKILL_PATTERNS = [
    rx(r"concise, evidence-dense progress and completion reporting"),
    rx(r"local overrides for the active workflow branch"),
    rx(r"user says `continue`"),
]


# ===== 合约定义 =====

ROOT_TEMPLATE_CONTRACTS = [
    GuidanceSurfaceContract(id="agents-root", path="AGENTS.md", required_patterns=ROOT_TEMPLATE_PATTERNS),
    GuidanceSurfaceContract(id="agents-template", path="templates/AGENTS.md", required_patterns=ROOT_TEMPLATE_PATTERNS),
]

CORE_ROLE_CONTRACTS = [
    GuidanceSurfaceContract(id="executor", path="prompts/executor.md", required_patterns=CORE_ROLE_PATTERNS["executor"]),
    GuidanceSurfaceContract(id="planner", path="prompts/planner.md", required_patterns=CORE_ROLE_PATTERNS["planner"]),
    GuidanceSurfaceContract(id="verifier", path="prompts/verifier.md", required_patterns=CORE_ROLE_PATTERNS["verifier"]),
]

SCENARIO_ROLE_CONTRACTS = [
    GuidanceSurfaceContract(
        id="executor-scenarios",
        path="prompts/executor.md",
        required_patterns=[
            rx(r"user says `continue`"),
            rx(r"make a PR targeting dev"),
            rx(r"merge to dev if CI green"),
            rx(r"confirm CI is green, then merge"),
        ],
    ),
    GuidanceSurfaceContract(
        id="planner-scenarios",
        path="prompts/planner.md",
        required_patterns=[
            rx(r"user says `continue`"),
            rx(r"user says `make a PR`"),
            rx(r"user says `merge if CI green`"),
            rx(r"scoped condition on the next operational step"),
        ],
    ),
    GuidanceSurfaceContract(
        id="verifier-scenarios",
        path="prompts/verifier.md",
        required_patterns=[
            rx(r"user says `merge if CI green`"),
            rx(r"confirm they are green"),
            rx(r"user says `continue`"),
            rx(r"keep gathering the required evidence"),
        ],
    ),
]

WAVE_TWO_CONTRACTS = [
    GuidanceSurfaceContract(id=name, path=f"prompts/{name}.md", required_patterns=WAVE_TWO_PATTERNS)
    for name in ["architect", "critic", "debugger", "test-engineer", "code-reviewer", "quality-reviewer", "security-reviewer", "researcher", "explore"]
]

CATALOG_CONTRACTS = [
    GuidanceSurfaceContract(id=name, path=f"prompts/{name}.md", required_patterns=CATALOG_PATTERNS)
    for name in [
        "analyst", "api-reviewer", "build-fixer", "dependency-expert", "designer", "git-master",
        "information-architect", "performance-reviewer", "product-analyst", "product-manager",
        "qa-tester", "quality-strategist", "style-reviewer", "ux-researcher", "vision", "writer",
    ]
]

LEGACY_PROMPT_CONTRACTS = [
    GuidanceSurfaceContract(
        id="code-simplifier",
        path="prompts/code-simplifier.md",
        required_patterns=[
            rx(r"local overrides for the active simplification scope"),
            rx(r"simplification result is grounded"),
            rx(r"<Scenario_Examples>"),
        ],
    ),
]

SPECIALIZED_PROMPT_CONTRACTS = [
    GuidanceSurfaceContract(
        id="sisyphus-lite",
        path="prompts/sisyphus-lite.md",
        required_patterns=[
            rx(r"compact, information-dense outputs"),
            rx(r"Treat newer user instructions as local overrides"),
            rx(r"No evidence = not complete"),
            rx(r"specialized worker behavior prompt|worker behavior prompt"),
        ],
    ),
]

SKILL_CONTRACTS = [
    GuidanceSurfaceContract(id=name, path=f"skills/{name}/SKILL.md", required_patterns=SKILL_PATTERNS)
    for name in ["analyze", "autopilot", "build-fix", "code-review", "plan", "ralph", "ralplan", "security-review", "team", "ultraqa"]
]


# ===== 验证函数 =====

def validate_contract(content: str, contract: GuidanceSurfaceContract) -> tuple[bool, list[str]]:
    """验证内容是否符合合约"""
    missing = []
    for pattern in contract.required_patterns:
        if not pattern.search(content):
            missing.append(pattern.pattern)
    return len(missing) == 0, missing


def get_all_contracts() -> list[GuidanceSurfaceContract]:
    """获取所有合约"""
    return (
        ROOT_TEMPLATE_CONTRACTS
        + CORE_ROLE_CONTRACTS
        + SCENARIO_ROLE_CONTRACTS
        + WAVE_TWO_CONTRACTS
        + CATALOG_CONTRACTS
        + LEGACY_PROMPT_CONTRACTS
        + SPECIALIZED_PROMPT_CONTRACTS
        + SKILL_CONTRACTS
    )


# ===== 导出 =====
__all__ = [
    "GuidanceSurfaceContract",
    "ROOT_TEMPLATE_CONTRACTS",
    "CORE_ROLE_CONTRACTS",
    "SCENARIO_ROLE_CONTRACTS",
    "WAVE_TWO_CONTRACTS",
    "CATALOG_CONTRACTS",
    "LEGACY_PROMPT_CONTRACTS",
    "SPECIALIZED_PROMPT_CONTRACTS",
    "SKILL_CONTRACTS",
    "validate_contract",
    "get_all_contracts",
]
