---
evaluator:
  command: node scripts/eval-fresh-run-tagging.js
  format: json
  keep_policy: pass_only
---
Stay focused on fresh-run lane creation semantics, worktree naming, and targeted tests.
Avoid changing resume semantics unless strictly required by the lane naming contract.
