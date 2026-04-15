# Mission
Optimize a noisy high-dimensional black-box search problem with a fixed evaluation budget.

Goal:
Beat the current kept score on the `playground/bayesopt_highdim_demo/` benchmark, where only a few dimensions are informative and observations are noisy.

Primary targets:
- `playground/bayesopt_highdim_demo/config.json`
- `playground/bayesopt_highdim_demo/optimizer.py`
- `playground/bayesopt_highdim_demo/run_search.py`
- `playground/bayesopt_highdim_demo/problem.py`

Success means:
1. the evaluator score improves over the current kept baseline
2. the solution remains deterministic and budget-respecting
3. the search strategy handles the curse of dimensionality better than naive random search
