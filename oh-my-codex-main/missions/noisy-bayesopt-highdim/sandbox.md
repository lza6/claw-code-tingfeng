---
evaluator:
  command: PYTHONDONTWRITEBYTECODE=1 python3 scripts/eval-noisy-bayesopt-highdim.py
  format: json
  keep_policy: score_improvement
---
Stay tightly scoped to `playground/bayesopt_highdim_demo/`.

Allowed changes:
- search strategy
- acquisition logic
- active-dimension logic
- search hyperparameters and config
- small structural refactors in the demo if they directly support optimization

Avoid:
- unrelated repository edits
- adding new Python dependencies
- increasing the evaluation budget just to win the score

Treat this as a harder research problem: noisy objective, many irrelevant dimensions, limited evaluations, and real tradeoffs between exploration, exploitation, and dimensionality handling.
