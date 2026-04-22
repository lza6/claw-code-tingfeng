"""Role Router for team orchestration

汲取 oh-my-codex-main/src/team/role-router.ts

Provides two layers:
- Layer 1: Prompt loading utilities (load_role_prompt, is_known_role, list_available_roles)
- Layer 2: Heuristic role routing (route_task_to_role, compute_worker_role_assignments)
"""

from __future__ import annotations

import re
from pathlib import Path

from .roles import AgentRole

# Role name validation pattern: lowercase alphanumeric with hyphens
SAFE_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


class RoleRouterResult:
    """Result of role routing decision"""

    def __init__(
        self,
        role: AgentRole,
        confidence: str,
        reason: str,
    ):
        self.role = role
        self.confidence = confidence  # "high" | "medium" | "low"
        self.reason = reason

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "confidence": self.confidence,
            "reason": self.reason,
        }


# Keyword-to-role mapping
# Order matters: first match wins within a category, but higher keyword count wins across categories
ROLE_KEYWORDS = [
    {
        "role": "test-engineer",
        "keywords": [
            "test",
            "spec",
            "coverage",
            "tdd",
            "pytest",
            "unittest",
            "e2e",
            "테스트",
            "커버리지",
            "测试",
        ],
    },
    {
        "role": "designer",
        "keywords": [
            "ui",
            "component",
            "layout",
            "css",
            "design",
            "responsive",
            "tailwind",
            "react",
            "frontend",
            "styling",
            "ux",
            "디자인",
            "레이아웃",
            "컴포넌트",
        ],
    },
    {
        "role": "build-fixer",
        "keywords": [
            "build",
            "compile",
            "type error",
            "typescript error",
            "build error",
            "compilation",
            "빌드",
            "컴파일",
            "타입 오류",
        ],
    },
    {
        "role": "debugger",
        "keywords": [
            "debug",
            "investigate",
            "root cause",
            "regression",
            "stack trace",
            "bisect",
            "diagnose",
            "디버그",
            "조사",
            "원인",
        ],
    },
    {
        "role": "writer",
        "keywords": [
            "doc",
            "readme",
            "migration guide",
            "changelog",
            "comment",
            "documentation",
            "api doc",
            "문서",
            "가이드",
            "변경로그",
        ],
    },
    {
        "role": "quality-reviewer",
        "keywords": [
            "review",
            "audit",
            "quality",
            "lint",
            "anti-pattern",
            "code review",
            "검토",
            "리뷰",
        ],
    },
    {
        "role": "security-reviewer",
        "keywords": [
            "security",
            "owasp",
            "xss",
            "injection",
            "cve",
            "vulnerability",
            "보안",
            "취약점",
        ],
    },
    {
        "role": "code-simplifier",
        "keywords": [
            "refactor",
            "simplify",
            "clean up",
            "reduce complexity",
            "consolidate",
            "리팩터",
            "단순화",
        ],
    },
]

# Intent detection patterns
IMPLEMENTATION_INTENT = re.compile(
    r"\b(?:add|build|create|fix|implement|make|migrate|repair|ship|support|update|wire)\b"
    r"|(?:구현|추가|수정|업데이트|지원)",
    re.IGNORECASE,
)
REVIEW_INTENT = re.compile(
    r"\b(?:audit|check|inspect|review|validate|verify)\b|(?:검토|리뷰|감사|확인|검증)",
    re.IGNORECASE,
)
PRIMARY_TEST_INTENT = re.compile(
    r"^(?:add|create|expand|improve|increase|write)\b.*\b(?:tests?|specs?|coverage)\b"
    r"|^(?:테스트\s*(?:추가|작성)|커버리지\s*추가)",
    re.IGNORECASE,
)
DOCS_INTENT = re.compile(
    r"\b(?:docs?|documentation|readme|guide|changelog)\b|(?:문서|가이드|README|변경로그)",
    re.IGNORECASE,
)
PRIMARY_DOCS_INTENT = re.compile(
    r"^(?:document|draft|write|update)\b.*\b(?:docs?|documentation|readme|guide|changelog)\b"
    r"|^(?:문서\s*(?:업데이트|작성)|README\s*업데이트|가이드\s*작성)",
    re.IGNORECASE,
)
DEBUG_INTENT = re.compile(
    r"\b(?:debug|diagnose|investigate|root cause|trace|bisect)\b|(?:디버그|조사|원인)",
    re.IGNORECASE,
)
DESIGN_INTENT = re.compile(
    r"\b(?:design|layout|style)\b|\b(?:build|create)\b.*\b(?:ui|component|frontend)\b"
    r"|(?:디자인|레이아웃|스타일|컴포넌트)",
    re.IGNORECASE,
)


def load_role_prompt(role: str, prompts_dir: Path) -> str | None:
    """Load behavioral prompt content for a given agent role

    Args:
        role: Role name (must match SAFE_ROLE_PATTERN)
        prompts_dir: Directory containing role prompt files

    Returns:
        Prompt content string or None if not found/invalid
    """
    if not SAFE_ROLE_PATTERN.match(role):
        return None

    prompt_file = prompts_dir / f"{role}.md"
    try:
        if prompt_file.exists():
            return prompt_file.read_text().strip() or None
    except Exception:
        pass
    return None


def is_known_role(role: str, prompts_dir: Path) -> bool:
    """Check whether a role has a corresponding prompt file

    Args:
        role: Role name
        prompts_dir: Directory containing role prompt files

    Returns:
        True if the role prompt file exists
    """
    if not SAFE_ROLE_PATTERN.match(role):
        return False
    return (prompts_dir / f"{role}.md").exists()


async def list_available_roles(prompts_dir: Path) -> list[str]:
    """List all available roles by scanning the prompts directory

    Args:
        prompts_dir: Directory containing role prompt files

    Returns:
        Sorted list of role names (filename without .md extension)
    """
    if not prompts_dir.exists():
        return []

    roles = []
    for file in prompts_dir.glob("*.md"):
        if SAFE_ROLE_PATTERN.match(file.stem):
            roles.append(file.stem)

    return sorted(roles)


def route_task_to_role(task_description: str) -> RoleRouterResult:
    """Route a task description to an appropriate agent role

    Uses keyword matching and intent detection to determine the best role.

    Args:
        task_description: Natural language task description

    Returns:
        RoleRouterResult with role, confidence, and reason
    """
    desc_lower = task_description.lower()
    scores: dict[str, int] = {}

    # Count keyword matches
    for entry in ROLE_KEYWORDS:
        role = entry["role"]
        keywords = entry["keywords"]
        score = sum(1 for kw in keywords if kw.lower() in desc_lower)
        if score > 0:
            scores[role] = score

    if scores:
        # Find role with highest score
        best_role = max(scores, key=scores.get)
        confidence = "high" if scores[best_role] >= 2 else "medium"
        return RoleRouterResult(
            role=best_role,
            confidence=confidence,
            reason=f"Keyword match: {scores[best_role]} keywords found",
        )

    # Fallback: detect intent patterns
    if DEBUG_INTENT.search(task_description):
        return RoleRouterResult(
            role="debugger",
            confidence="low",
            reason="Debug intent detected",
        )
    if DESIGN_INTENT.search(task_description):
        return RoleRouterResult(
            role="designer",
            confidence="low",
            reason="Design intent detected",
        )
    if PRIMARY_TEST_INTENT.search(task_description):
        return RoleRouterResult(
            role="test-engineer",
            confidence="low",
            reason="Test intent detected",
        )
    if DOCS_INTENT.search(task_description):
        return RoleRouterResult(
            role="writer",
            confidence="low",
            reason="Documentation intent detected",
        )
    if REVIEW_INTENT.search(task_description):
        return RoleRouterResult(
            role="quality-reviewer",
            confidence="low",
            reason="Review intent detected",
        )

    # Default
    return RoleRouterResult(
        role="executor",
        confidence="low",
        reason="No specific role matched, defaulting to executor",
    )


def compute_worker_role_assignments(
    workers: list[str],
    tasks: list[dict],
    role_hints: dict | None = None,
) -> dict:
    """Compute role assignments for workers based on tasks

    Args:
        workers: List of worker names/IDs
        tasks: List of task dictionaries with 'description' and optional 'role' key
        role_hints: Optional mapping of worker -> preferred role

    Returns:
        Dictionary mapping worker name -> assigned role
    """
    assignments = {}
    role_counts: dict[str, int] = {}

    for i, worker in enumerate(workers):
        # Try role hint first
        if role_hints and worker in role_hints:
            assignments[worker] = role_hints[worker]
            role_counts[role_hints[worker]] = role_counts.get(role_hints[worker], 0) + 1
            continue

        # Assign based on task at same index (round-robin with role matching)
        if i < len(tasks):
            task = tasks[i]
            task_role = task.get("role")
            if task_role:
                # Check if this role is already over-assigned
                current_count = role_counts.get(task_role, 0)
                # Simple balancing: prefer roles with fewer assignments
                assignments[worker] = task_role
                role_counts[task_role] = current_count + 1
            else:
                # Route based on description
                result = route_task_to_role(task.get("description", ""))
                assignments[worker] = result.role
                role_counts[result.role] = role_counts.get(result.role, 0) + 1
        else:
            # No task, assign default
            assignments[worker] = "executor"

    return assignments
