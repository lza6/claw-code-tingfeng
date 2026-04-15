# Mission
Optimize a Kaggle-style tabular classification pipeline inside this repository.

Goal:
Improve the baseline ROC AUC of the demo model in `playground/ml_kaggle_demo/` on a fixed, deterministic validation split.

Primary targets:
- `playground/ml_kaggle_demo/config.json`
- `playground/ml_kaggle_demo/model_factory.py`
- `playground/ml_kaggle_demo/train.py`

Success means:
1. the evaluator score (ROC AUC) improves over the current kept baseline
2. the solution stays deterministic and reproducible
3. the changes remain focused on model architecture / feature pipeline choices rather than unrelated repository edits
