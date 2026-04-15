---
evaluator:
  command: node scripts/eval-resume-dirty-guard.js
  format: json
  keep_policy: pass_only
---
Only change autoresearch resume validation, related runtime helpers, and targeted tests.
Do not broaden scope into full loop behavior.
