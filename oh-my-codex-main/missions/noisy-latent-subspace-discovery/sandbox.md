---
evaluator:
  command: PYTHONDONTWRITEBYTECODE=1 python3 scripts/eval-noisy-latent-subspace-discovery.py
  format: json
  keep_policy: score_improvement
---
Stay tightly scoped to `playground/bayesopt_latent_discovery_demo/`.

Allowed changes:
- search strategy
- screening / structure-discovery logic
- acquisition logic
- search hyperparameters and config
- small structural refactors in the demo if they directly support optimization

Avoid:
- unrelated repository edits
- adding new Python dependencies
- increasing the evaluation budget just to win the score

Treat this as a harder research problem than explicit active-dimension search: the useful directions are mixed through latent structure, the objective is noisy, and the solution must discover useful coordinates or subspaces under a finite budget.
