---
evaluator:
  command: python3 scripts/eval-adaptive-sort-optimization.py
  format: json
  keep_policy: score_improvement
---
Stay tightly scoped to `playground/adaptive_sort_demo/`.

Allowed changes:
- hybrid sort dispatch logic
- threshold tuning
- lightweight deterministic heuristics
- small structural cleanups that directly support the optimization

Avoid:
- unrelated repository changes
- adding new dependencies
- changing the benchmark cases only to make the score easier

Treat this as an algorithm-engineering task: keep the benchmark deterministic and improve weighted cost across mixed data distributions.
