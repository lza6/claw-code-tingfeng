---
evaluator:
  command: python3 scripts/eval-ml-kaggle-model-optimization.py
  format: json
  keep_policy: score_improvement
---
Stay tightly scoped to the ML demo under `playground/ml_kaggle_demo/`.

Allowed changes:
- model selection and hyperparameters
- lightweight preprocessing in the current pipeline
- small structural cleanups inside the ML demo files if they support the optimization

Avoid:
- unrelated repository changes
- adding new Python dependencies
- changing the evaluator unless absolutely necessary to fix a real bug

Treat this like a Kaggle-style architecture search loop: inspect the current baseline, try one concrete model improvement, verify with the evaluator, and record either a candidate or a noop.
