"""Autoresearch - Self-improving experiment runtime.

Integration from oh-my-codex-main/src/autoresearch/:
- contracts.py: Mission and sandbox contract definitions
- runtime.py: Runtime for running self-improving experiments

Usage:
```python
from src.autoresearch import load_autoresearch_mission_contract, prepare_autoresearch_runtime

contract = await load_autoresearch_mission_contract("./my-mission")
result = await prepare_autoresearch_runtime(contract, project_root, worktree_path)
```
"""
from src.autoresearch.contracts import (
    AutoresearchError,
    load_autoresearch_mission_contract,
    parse_evaluator_result,
    parse_sandbox_contract,
    slugify_mission_name,
)
from src.autoresearch.runtime import (
    build_autoresearch_run_tag,
    decide_autoresearch_outcome,
    process_autoresearch_candidate,
    run_autoresearch_evaluator,
)

__all__ = [
    "AutoresearchError",
    "build_autoresearch_run_tag",
    "decide_autoresearch_outcome",
    "load_autoresearch_mission_contract",
    "parse_evaluator_result",
    "parse_sandbox_contract",
    "process_autoresearch_candidate",
    "run_autoresearch_evaluator",
    "slugify_mission_name",
]
