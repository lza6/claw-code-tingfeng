"""Autoresearch contracts for mission and sandbox definitions."""
import subprocess
from pathlib import Path
from typing import Any, Optional

AutoresearchKeepPolicy = "score_improvement" | "pass_only"


class AutoresearchError(Exception):
    """Base exception for autoresearch errors."""
    pass


MISSION_DIR_GIT_ERROR = "mission-dir must be inside a git repository."
SANDBOX_FRONTMATTER_ERROR = "sandbox.md must start with YAML frontmatter containing evaluator.command and evaluator.format=json."
EVALUATOR_BLOCK_ERROR = "sandbox.md frontmatter must define an evaluator block."
EVALUATOR_COMMAND_ERROR = "sandbox.md frontmatter evaluator.command is required."
EVALUATOR_FORMAT_REQUIRED_ERROR = "sandbox.md frontmatter evaluator.format is required and must be json in autoresearch v1."
EVALUATOR_FORMAT_JSON_ERROR = "sandbox.md frontmatter evaluator.format must be json in autoresearch v1."


def contract_error(message: str) -> AutoresearchError:
    return AutoresearchError(message)


def run_git(repo_path: Path, args: list[str]) -> str:
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as error:
        stderr = error.stderr.strip() if error.stderr else ""
        raise contract_error(stderr or MISSION_DIR_GIT_ERROR)


def slugify_mission_name(value: str) -> str:
    return (
        value.lower()
        .replace("_", "-")
        .replace(" ", "-")
        .replace("[^a-z0-9]+", "-")
        .replace("-+", "-")
        .strip("-")[:48] or "mission"
    )


def ensure_path_inside(parent_path: str, child_path: str) -> None:
    rel = Path(child_path).relative_to(parent_path)
    if str(rel).startswith(".."):
        raise contract_error(MISSION_DIR_GIT_ERROR)


def extract_frontmatter(content: str) -> tuple[str, str]:
    import re
    match = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$", content)
    if not match:
        raise contract_error(SANDBOX_FRONTMATTER_ERROR)
    return match.group(1) or "", match.group(2) or ""


def parse_simple_yaml_frontmatter(frontmatter: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_section: Optional[str] = None

    for raw_line in frontmatter.split("\n"):
        line = raw_line.replace("\t", "  ")
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue

        section_match = trimmed.match(r"^([A-Za-z0-9_-]+):\s*$")
        if section_match:
            current_section = section_match.group(1)
            result[current_section] = {}
            continue

        nested_match = re.match(r"^([A-Za-z0-9_-]+):\s*(.+)\s*$", trimmed)
        if not nested_match:
            raise AutoresearchError(f"Unsupported sandbox.md frontmatter line: {trimmed}")

        key = nested_match.group(1)
        value = nested_match.group(2).strip("'\"")
        if line.startswith(" ") or line.startswith("\t"):
            if not current_section:
                raise AutoresearchError(f"Nested sandbox.md frontmatter key requires a parent section: {trimmed}")
            if current_section in result and isinstance(result[current_section], dict):
                result[current_section][key] = value
            continue

        result[key] = value
        current_section = None

    return result


def parse_keep_policy(raw: Optional[str]) -> Optional[AutoresearchKeepPolicy]:
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized == "pass_only":
        return "pass_only"
    if normalized == "score_improvement":
        return "score_improvement"
    raise contract_error("sandbox.md frontmatter evaluator.keep_policy must be one of: score_improvement, pass_only.")


class AutoresearchEvaluatorContract:
    """Contract for the evaluator command."""
    command: str
    format: str = "json"
    keep_policy: Optional[AutoresearchKeepPolicy] = None


class ParsedSandboxContract:
    """Parsed sandbox.md contract."""
    frontmatter: dict[str, Any]
    evaluator: AutoresearchEvaluatorContract
    body: str


class AutoresearchEvaluatorResult:
    """Result from evaluator command."""
    pass_: bool
    score: Optional[float] = None


def parse_sandbox_contract(content: str) -> ParsedSandboxContract:
    frontmatter, body = extract_frontmatter(content)
    parsed_frontmatter = parse_simple_yaml_frontmatter(frontmatter)

    evaluator_raw = parsed_frontmatter.get("evaluator")
    if not evaluator_raw or not isinstance(evaluator_raw, dict):
        raise contract_error(EVALUATOR_BLOCK_ERROR)

    command = evaluator_raw.get("command", "").strip() if isinstance(evaluator_raw.get("command"), str) else ""
    format_ = evaluator_raw.get("format", "").strip().lower() if isinstance(evaluator_raw.get("format"), str) else ""
    keep_policy = parse_keep_policy(evaluator_raw.get("keep_policy"))

    if not command:
        raise contract_error(EVALUATOR_COMMAND_ERROR)
    if not format_:
        raise contract_error(EVALUATOR_FORMAT_REQUIRED_ERROR)
    if format_ != "json":
        raise contract_error(EVALUATOR_FORMAT_JSON_ERROR)

    return ParsedSandboxContract(
        frontmatter=parsed_frontmatter,
        evaluator=AutoresearchEvaluatorContract(
            command=command,
            format="json",
            keep_policy=keep_policy,
        ),
        body=body,
    )


def parse_evaluator_result(raw: str) -> AutoresearchEvaluatorResult:
    import json
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise contract_error("Evaluator output must be valid JSON with required boolean pass and optional numeric score.")

    if not parsed or not isinstance(parsed, dict):
        raise contract_error("Evaluator output must be a JSON object.")

    pass_ = parsed.get("pass")
    if not isinstance(pass_, bool):
        raise contract_error("Evaluator output must include boolean pass.")

    score = parsed.get("score")
    if score is not None and not isinstance(score, (int, float)):
        raise contract_error("Evaluator output score must be numeric when provided.")

    return AutoresearchEvaluatorResult(pass_=pass_, score=float(score) if score is not None else None)


class AutoresearchMissionContract:
    """Full mission contract with paths and content."""
    mission_dir: str
    repo_root: str
    mission_file: str
    sandbox_file: str
    mission_relative_dir: str
    mission_content: str
    sandbox_content: str
    sandbox: ParsedSandboxContract
    mission_slug: str


async def load_autoresearch_mission_contract(mission_dir_arg: str) -> AutoresearchMissionContract:
    """Load a mission contract from a directory."""
    import asyncio
    from pathlib import Path

    mission_dir = Path(mission_dir_arg).resolve()
    if not mission_dir.exists():
        raise contract_error(f"mission-dir does not exist: {mission_dir}")

    repo_root = run_git(mission_dir, ["rev-parse", "--show-toplevel"])
    ensure_path_inside(repo_root, str(mission_dir))

    mission_file = mission_dir / "mission.md"
    sandbox_file = mission_dir / "sandbox.md"

    if not mission_file.exists():
        raise contract_error(f"mission.md is required inside mission-dir: {mission_file}")
    if not sandbox_file.exists():
        raise contract_error(f"sandbox.md is required inside mission-dir: {sandbox_file}")

    mission_content = mission_file.read_text(encoding="utf-8")
    sandbox_content = sandbox_file.read_text(encoding="utf-8")
    sandbox = parse_sandbox_contract(sandbox_content)

    from pathlib import PurePath
    mission_relative_dir = str(PurePath(mission_dir).relative_to(repo_root))
    mission_slug = slugify_mission_name(mission_relative_dir)

    return AutoresearchMissionContract(
        mission_dir=str(mission_dir),
        repo_root=repo_root,
        mission_file=str(mission_file),
        sandbox_file=str(sandbox_file),
        mission_relative_dir=mission_relative_dir,
        mission_content=mission_content,
        sandbox_content=sandbox_content,
        sandbox=sandbox,
        mission_slug=mission_slug,
    )