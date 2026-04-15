---
evaluator:
  command: node scripts/eval-parity-sweep.js
  format: json
---
Stay within autoresearch runtime/CLI/worktree/docs/tests.

Allowed files:
- src/cli/autoresearch.ts
- src/autoresearch/*
- src/team/worktree.ts
- src/modes/base.ts
- relevant autoresearch/worktree/mode/CLI tests
- README.md
- docs/contracts/autoresearch-command-contract.md
- related help fixtures

Avoid unrelated refactors or broad documentation churn.
