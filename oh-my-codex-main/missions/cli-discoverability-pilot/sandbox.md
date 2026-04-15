---
evaluator:
  command: node scripts/eval-cli-discoverability.js
  format: json
  keep_policy: score_improvement
---

# Sandbox rules

- Keep changes focused on CLI discoverability only.
- Prefer the smallest reviewable diff.
- Do not add dependencies.
- Preserve command semantics; this mission is about discoverability, not feature redesign.
- The evaluator rewards passing the targeted build + CLI discoverability test slice.

# Evaluation policy

- `pass=true` means the targeted build and discoverability tests all passed.
- `score` is the fraction of targeted checks passing, from `0.00` to `1.00`.
- Higher scores are better.
