---
evaluator:
  command: node scripts/eval-security-path-traversal.js
  format: json
  keep_policy: score_improvement
---

# Sandbox rules

- Keep changes focused on path validation and traversal rejection.
- No new dependencies.
- Prefer explicit validation and regression tests over architectural churn.
- Do not weaken existing guardrails to make tests pass.

# Evaluation policy

- `pass=true` means the targeted build and MCP path-safety test slice all passed.
- `score` is the fraction of targeted checks passing, from `0.00` to `1.00`.
- Higher scores are better.
