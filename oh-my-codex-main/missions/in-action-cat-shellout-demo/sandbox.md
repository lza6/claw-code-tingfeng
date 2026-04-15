---
evaluator:
  command: node scripts/eval-in-action-cat-shellout-demo.js
  format: json
  keep_policy: pass_only
---
Stay tightly scoped to the autoresearch CLI loop cleanup.

Allowed changes:
- `src/cli/autoresearch.ts`
- focused autoresearch tests if needed

Avoid:
- unrelated refactors
- changing mission/runtime contracts unless required by the cleanup
- broad docs churn

A passing outcome is one where the shell-out is removed and the focused autoresearch tests pass.
