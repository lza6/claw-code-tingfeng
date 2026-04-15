# Mission
Optimize an adaptive sorting strategy across multiple deterministic input distributions.

Goal:
Improve the evaluator score for `playground/adaptive_sort_demo/` while preserving correct sorting across all benchmark cases.

Primary targets:
- `playground/adaptive_sort_demo/config.json`
- `playground/adaptive_sort_demo/sort_benchmark.py`

Success means:
1. the weighted cost score improves over the current kept baseline
2. correctness holds for every benchmark case
3. the strategy remains lightweight and deterministic
