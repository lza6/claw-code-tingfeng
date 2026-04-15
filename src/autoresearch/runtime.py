"""Autoresearch runtime for running self-improving experiments."""
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.autoresearch.contracts import (
    AutoresearchError,
    AutoresearchEvaluatorContract,
    AutoresearchEvaluatorResult,
    AutoresearchKeepPolicy,
    AutoresearchMissionContract,
    load_autoresearch_mission_contract,
    parse_evaluator_result,
    slugify_mission_name,
)


AutoresearchCandidateStatus = "candidate" | "noop" | "abort" | "interrupted"
AutoresearchDecisionStatus = "baseline" | "keep" | "discard" | "ambiguous" | "noop" | "abort" | "interrupted" | "error"
AutoresearchRunStatus = "running" | "stopped" | "completed" | "failed"


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def build_autoresearch_run_tag(date: Optional[datetime] = None) -> str:
    date = date or datetime.now()
    iso = date.isoformat().replace("-", "").replace(":", "")
    return iso.replace(".000Z", "Z").replace("T", "T")


def build_run_id(mission_slug: str, run_tag: str) -> str:
    return f"{mission_slug}-{run_tag.lower()}"


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
        raise AutoresearchError(stderr or f"git {args} failed")


def try_resolve_git_commit(worktree_path: Path, ref: str) -> Optional[str]:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def read_git_short_head(worktree_path: Path) -> str:
    return run_git(worktree_path, ["rev-parse", "--short=7", "HEAD"])


def read_git_full_head(worktree_path: Path) -> str:
    return run_git(worktree_path, ["rev-parse", "HEAD"])


def git_status_lines(worktree_path: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AutoresearchError(f"git status failed for {worktree_path}")
    return [line.strip() for line in result.stdout.split("\n") if line.strip()]


AUTORESEARCH_WORKTREE_EXCLUDES = ["results.tsv", "run.log", "node_modules", ".omx/"]


def is_allowed_runtime_dirty_line(line: str) -> bool:
    if len(line) < 4:
        return False
    path = line[3:].strip()
    return line.startswith("?? ") and any(
        exclude.endswith("/") and (path.startswith(exclude) or path == exclude[:-1])
        or path == exclude
        for exclude in AUTORESEARCH_WORKTREE_EXCLUDES
    )


def assert_reset_safe_worktree(worktree_path: Path) -> None:
    lines = git_status_lines(worktree_path)
    blocking = [line for line in lines if not is_allowed_runtime_dirty_line(line)]
    if blocking:
        raise AutoresearchError(f"autoresearch_reset_requires_clean_worktree:{worktree_path}:{' | '.join(blocking)}")


def ensure_parent_dir(file_path: Path) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)


def write_json_file(file_path: Path, value: Any) -> None:
    ensure_parent_dir(file_path)
    file_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def read_json_file(file_path: Path) -> Any:
    return json.loads(file_path.read_text(encoding="utf-8"))


@dataclass
class AutoresearchEvaluationRecord:
    command: str
    ran_at: str
    status: "pass" | "fail" | "error"
    pass_: Optional[bool] = None
    score: Optional[float] = None
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    parse_error: Optional[str] = None


@dataclass
class AutoresearchCandidateArtifact:
    status: AutoresearchCandidateStatus
    candidate_commit: Optional[str]
    base_commit: str
    description: str
    notes: list[str]
    created_at: str


@dataclass
class AutoresearchLedgerEntry:
    iteration: int
    kind: "baseline" | "iteration"
    decision: AutoresearchDecisionStatus
    decision_reason: str
    candidate_status: AutoresearchCandidateStatus | "baseline"
    base_commit: str
    candidate_commit: Optional[str]
    kept_commit: str
    keep_policy: AutoresearchKeepPolicy
    evaluator: Optional[AutoresearchEvaluationRecord]
    created_at: str
    notes: list[str]
    description: str


@dataclass
class AutoresearchRunManifest:
    schema_version: int = 1
    run_id: str = ""
    run_tag: str = ""
    mission_dir: str = ""
    mission_file: str = ""
    sandbox_file: str = ""
    repo_root: str = ""
    worktree_path: str = ""
    mission_slug: str = ""
    branch_name: str = ""
    baseline_commit: str = ""
    last_kept_commit: str = ""
    last_kept_score: Optional[float] = None
    latest_candidate_commit: Optional[str] = None
    results_file: str = ""
    instructions_file: str = ""
    manifest_file: str = ""
    ledger_file: str = ""
    latest_evaluator_file: str = ""
    candidate_file: str = ""
    evaluator: Optional[AutoresearchEvaluatorContract] = None
    keep_policy: AutoresearchKeepPolicy = "score_improvement"
    status: AutoresearchRunStatus = "running"
    stop_reason: Optional[str] = None
    iteration: int = 0
    created_at: str = ""
    updated_at: str = ""
    completed_at: Optional[str] = None


AUTORESEARCH_RESULTS_HEADER = "iteration\tcommit\tpass\tscore\tstatus\tdescription\n"


async def initialize_autoresearch_results_file(results_file: Path) -> None:
    if results_file.exists():
        return
    ensure_parent_dir(results_file)
    results_file.write_text(AUTORESEARCH_RESULTS_HEADER, encoding="utf-8")


async def append_autoresearch_results_row(
    results_file: Path,
    row: dict,
) -> None:
    existing = results_file.read_text(encoding="utf-8") if results_file.exists() else AUTORESEARCH_RESULTS_HEADER
    row_text = f"{row['iteration']}\t{row['commit']}\t{row.get('pass', '')}\t{row.get('score', '')}\t{row['status']}\t{row['description']}\n"
    results_file.write_text(existing + row_text, encoding="utf-8")


def trim_content(value: str, max_length: int = 4000) -> str:
    trimmed = value.strip()
    return trimmed[:max_length] + "\n..." if len(trimmed) > max_length else trimmed


async def append_autoresearch_ledger_entry(ledger_file: Path, entry: AutoresearchLedgerEntry) -> None:
    if ledger_file.exists():
        parsed = read_json_file(ledger_file)
        entries = parsed.get("entries", [])
    else:
        parsed = {"schema_version": 1, "entries": []}
        entries = []

    entries.append({
        "iteration": entry.iteration,
        "kind": entry.kind,
        "decision": entry.decision,
        "decision_reason": entry.decision_reason,
        "candidate_status": entry.candidate_status,
        "base_commit": entry.base_commit,
        "candidate_commit": entry.candidate_commit,
        "kept_commit": entry.kept_commit,
        "keep_policy": entry.keep_policy,
        "evaluator": {
            "command": entry.evaluator.command,
            "ran_at": entry.evaluator.ran_at,
            "status": entry.evaluator.status,
            "pass": entry.evaluator.pass_,
            "score": entry.evaluator.score,
            "exit_code": entry.evaluator.exit_code,
            "stdout": entry.evaluator.stdout,
            "stderr": entry.evaluator.stderr,
            "parse_error": entry.evaluator.parse_error,
        } if entry.evaluator else None,
        "created_at": entry.created_at,
        "notes": entry.notes,
        "description": entry.description,
    })
    parsed["entries"] = entries
    write_json_file(ledger_file, parsed)


async def read_autoresearch_ledger_entries(ledger_file: Path) -> list[dict]:
    if not ledger_file.exists():
        return []
    return read_json_file(ledger_file).get("entries", [])


def comparable_score(prev: Optional[float], current: Optional[float]) -> bool:
    return isinstance(prev, (int, float)) and isinstance(current, (int, float))


def decide_autoresearch_outcome(
    manifest: dict,
    candidate: AutoresearchCandidateArtifact,
    evaluation: Optional[AutoresearchEvaluationRecord],
) -> dict:
    keep_policy = manifest.get("keep_policy", "score_improvement")
    last_kept_score = manifest.get("last_kept_score")

    if candidate.status == "abort":
        return {"decision": "abort", "reason": "candidate requested abort", "keep": False, "notes": ["run stopped by candidate"]}
    if candidate.status == "noop":
        return {"decision": "noop", "reason": "candidate reported noop", "keep": False, "notes": ["no code change proposed"]}
    if candidate.status == "interrupted":
        return {"decision": "interrupted", "reason": "candidate session interrupted", "keep": False, "notes": ["inspect worktree cleanliness"]}

    if not evaluation or evaluation.status == "error":
        return {"decision": "discard", "reason": "evaluator error", "keep": False, "evaluator": evaluation}
    if not evaluation.pass_:
        return {"decision": "discard", "reason": "evaluator failed", "keep": False, "evaluator": evaluation}

    if keep_policy == "pass_only":
        return {"decision": "keep", "reason": "pass_only policy accepted", "keep": True, "evaluator": evaluation}

    if not comparable_score(last_kept_score, evaluation.score):
        return {"decision": "ambiguous", "reason": "no comparable score", "keep": False, "evaluator": evaluation}

    if evaluation.score and last_kept_score and evaluation.score > last_kept_score:
        return {"decision": "keep", "reason": "score improved", "keep": True, "evaluator": evaluation}

    return {"decision": "discard", "reason": "score not improved", "keep": False, "evaluator": evaluation}


async def run_autoresearch_evaluator(
    contract: AutoresearchMissionContract,
    worktree_path: Path,
    ledger_file: Optional[Path] = None,
    latest_evaluator_file: Optional[Path] = None,
) -> AutoresearchEvaluationRecord:
    ran_at = now_iso()
    evaluator_command = contract.sandbox.evaluator.command

    result = subprocess.run(
        evaluator_command,
        cwd=worktree_path,
        shell=True,
        capture_output=True,
        text=True,
        max_buffer=1024 * 1024,
    )

    stdout = result.stdout.strip() if result.stdout else ""
    stderr = result.stderr.strip() if result.stderr else ""

    record: AutoresearchEvaluationRecord
    if result.returncode != 0:
        record = AutoresearchEvaluationRecord(
            command=evaluator_command,
            ran_at=ran_at,
            status="error",
            exit_code=result.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    else:
        try:
            parsed = parse_evaluator_result(stdout)
            record = AutoresearchEvaluationRecord(
                command=evaluator_command,
                ran_at=ran_at,
                status="pass" if parsed.pass_ else "fail",
                pass_=parsed.pass_,
                score=parsed.score,
                exit_code=result.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        except AutoresearchError as e:
            record = AutoresearchEvaluationRecord(
                command=evaluator_command,
                ran_at=ran_at,
                status="error",
                exit_code=result.returncode,
                stdout=stdout,
                stderr=stderr,
                parse_error=str(e),
            )

    if latest_evaluator_file:
        write_json_file(latest_evaluator_file, {"command": record.command, "ran_at": record.ran_at, "status": record.status})

    return record


def build_autoresearch_instructions(
    contract: AutoresearchMissionContract,
    context: dict,
) -> str:
    return f"""# OMX Autoresearch Supervisor Instructions

Run ID: {context['run_id']}
Mission directory: {contract.mission_dir}
Mission file: {contract.mission_file}
Sandbox file: {contract.sandbox_file}
Mission slug: {contract.mission_slug}
Iteration: {context['iteration']}
Baseline commit: {context['baseline_commit']}
Last kept commit: {context['last_kept_commit']}
Last kept score: {context.get('last_kept_score', 'n/a')}
Results file: {context['results_file']}
Candidate artifact: {context['candidate_file']}
Keep policy: {context['keep_policy']}

Previous iteration: {context.get('previous_iteration_outcome', 'none yet')}

Operate as a thin autoresearch experiment worker for exactly one experiment cycle.
Do not loop forever inside this session. Make at most one candidate commit, then write the candidate artifact JSON and exit.

Candidate artifact contract:
- Write JSON to the candidate artifact path above.
- status: candidate | noop | abort | interrupted
- candidate_commit: string | null
- base_commit: current base commit before your edits
- description: short one-line summary
- notes: array of short strings
- created_at: ISO timestamp

Mission content:
{trim_content(contract.mission_content)}

Sandbox policy:
{trim_content(contract.sandbox.body or contract.sandbox_content)}
"""


async def prepare_autoresearch_runtime(
    contract: AutoresearchMissionContract,
    project_root: Path,
    worktree_path: Path,
    options: Optional[dict] = None,
) -> dict:
    options = options or {}
    run_tag = options.get("run_tag") or build_autoresearch_run_tag()
    run_id = build_run_id(contract.mission_slug, run_tag)

    baseline_commit = read_git_short_head(worktree_path)
    branch_name = run_git(worktree_path, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    run_dir = project_root / ".omx" / "logs" / "autoresearch" / run_id

    instructions_file = run_dir / "bootstrap-instructions.md"
    manifest_file = run_dir / "manifest.json"
    ledger_file = run_dir / "iteration-ledger.json"
    latest_evaluator_file = run_dir / "latest-evaluator-result.json"
    candidate_file = run_dir / "candidate.json"
    results_file = worktree_path / "results.tsv"

    keep_policy = contract.sandbox.evaluator.keep_policy or "score_improvement"

    run_dir.mkdir(parents=True, exist_ok=True)
    await initialize_autoresearch_results_file(results_file)

    write_json_file(candidate_file, {
        "status": "noop",
        "candidate_commit": None,
        "base_commit": baseline_commit,
        "description": "not-yet-written",
        "notes": ["candidate artifact will be overwritten by the launched session"],
        "created_at": now_iso(),
    })

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "run_tag": run_tag,
        "mission_dir": contract.mission_dir,
        "mission_file": contract.mission_file,
        "sandbox_file": contract.sandbox_file,
        "repo_root": str(project_root),
        "worktree_path": str(worktree_path),
        "mission_slug": contract.mission_slug,
        "branch_name": branch_name,
        "baseline_commit": baseline_commit,
        "last_kept_commit": read_git_full_head(worktree_path),
        "last_kept_score": None,
        "latest_candidate_commit": None,
        "results_file": str(results_file),
        "instructions_file": str(instructions_file),
        "manifest_file": str(manifest_file),
        "ledger_file": str(ledger_file),
        "latest_evaluator_file": str(latest_evaluator_file),
        "candidate_file": str(candidate_file),
        "evaluator": {
            "command": contract.sandbox.evaluator.command,
            "format": contract.sandbox.evaluator.format,
            "keep_policy": keep_policy,
        },
        "keep_policy": keep_policy,
        "status": "running",
        "stop_reason": None,
        "iteration": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "completed_at": None,
    }

    write_json_file(manifest_file, manifest)
    write_json_file(ledger_file, {"schema_version": 1, "run_id": run_id, "created_at": now_iso(), "entries": []})
    write_json_file(latest_evaluator_file, {"run_id": run_id, "status": "not-yet-run", "updated_at": now_iso()})

    evaluation = await run_autoresearch_evaluator(contract, worktree_path, ledger_file, latest_evaluator_file)

    manifest["last_kept_score"] = evaluation.score if evaluation.pass_ and evaluation.score else None
    write_json_file(manifest_file, manifest)

    await append_autoresearch_results_row(results_file, {
        "iteration": 0,
        "commit": baseline_commit,
        "pass": evaluation.pass_,
        "score": evaluation.score,
        "status": "baseline" if evaluation.status != "error" else "error",
        "description": "initial baseline evaluation",
    })

    instructions = build_autoresearch_instructions(contract, {
        "run_id": run_id,
        "iteration": 1,
        "baseline_commit": baseline_commit,
        "last_kept_commit": manifest["last_kept_commit"],
        "last_kept_score": manifest["last_kept_score"],
        "results_file": str(results_file),
        "candidate_file": str(candidate_file),
        "keep_policy": keep_policy,
    })
    instructions_file.write_text(instructions + "\n", encoding="utf-8")

    return {
        "run_id": run_id,
        "run_tag": run_tag,
        "run_dir": str(run_dir),
        "manifest": manifest,
        "worktree_path": str(worktree_path),
    }


async def process_autoresearch_candidate(
    contract: AutoresearchMissionContract,
    manifest: dict,
    project_root: Path,
) -> AutoresearchDecisionStatus:
    worktree_path = Path(manifest["worktree_path"])
    manifest_file = Path(manifest["manifest_file"])
    ledger_file = Path(manifest["ledger_file"])
    candidate_file = Path(manifest["candidate_file"])
    results_file = Path(manifest["results_file"])
    latest_evaluator_file = Path(manifest["latest_evaluator_file"])

    if not candidate_file.exists():
        raise AutoresearchError(f"autoresearch_candidate_missing:{candidate_file}")

    candidate_data = read_json_file(candidate_file)
    candidate = AutoresearchCandidateArtifact(
        status=candidate_data["status"],
        candidate_commit=candidate_data["candidate_commit"],
        base_commit=candidate_data["base_commit"],
        description=candidate_data["description"],
        notes=candidate_data["notes"],
        created_at=candidate_data["created_at"],
    )

    resolved_base = try_resolve_git_commit(worktree_path, candidate.base_commit)
    if not resolved_base:
        raise AutoresearchError(f"candidate base_commit does not resolve: {candidate.base_commit}")
    if resolved_base != manifest.get("last_kept_commit"):
        raise AutoresearchError(f"base_commit mismatch: {resolved_base} != {manifest.get('last_kept_commit')}")

    manifest["iteration"] = manifest.get("iteration", 0) + 1
    manifest["latest_candidate_commit"] = candidate.candidate_commit

    if candidate.status != "candidate":
        return candidate.status

    evaluation = await run_autoresearch_evaluator(contract, worktree_path, ledger_file, latest_evaluator_file)
    write_json_file(latest_evaluator_file, {"command": evaluation.command, "ran_at": evaluation.ran_at, "status": evaluation.status})

    decision = decide_autoresearch_outcome(manifest, candidate, evaluation)

    if decision["keep"]:
        manifest["last_kept_commit"] = read_git_full_head(worktree_path)
        manifest["last_kept_score"] = evaluation.score if evaluation.score else manifest.get("last_kept_score")
    else:
        subprocess.run(["git", "reset", "--hard", manifest["last_kept_commit"]], cwd=worktree_path)

    await append_autoresearch_results_row(results_file, {
        "iteration": manifest["iteration"],
        "commit": read_git_short_head(worktree_path),
        "pass": evaluation.pass_,
        "score": evaluation.score,
        "status": decision["decision"],
        "description": candidate.description,
    })

    manifest["updated_at"] = now_iso()
    write_json_file(manifest_file, manifest)

    return decision["decision"]


def parse_autoresearch_candidate_artifact(raw: str) -> AutoresearchCandidateArtifact:
    data = json.loads(raw)
    return AutoresearchCandidateArtifact(
        status=data["status"],
        candidate_commit=data["candidate_commit"],
        base_commit=data["base_commit"],
        description=data["description"],
        notes=data["notes"],
        created_at=data["created_at"],
    )