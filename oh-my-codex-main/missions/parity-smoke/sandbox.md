---
evaluator:
  command: node scripts/eval-parity-smoke.js
  format: json
  keep_policy: pass_only
---
Keep this mission lightweight and fast.
Prefer minimal changes only if needed to restore the smoke path.
