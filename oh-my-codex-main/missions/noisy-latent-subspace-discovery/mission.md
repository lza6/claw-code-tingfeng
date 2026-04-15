# Mission
Optimize a noisy high-dimensional black-box search problem where the useful structure is latent rather than exposed as obvious active coordinates.

Goal:
Beat the current kept score on `playground/bayesopt_latent_discovery_demo/` under a fixed evaluation budget, even though the objective depends on hidden mixed directions instead of directly named informative dimensions.

Primary targets:
- `playground/bayesopt_latent_discovery_demo/config.json`
- `playground/bayesopt_latent_discovery_demo/optimizer.py`
- `playground/bayesopt_latent_discovery_demo/run_search.py`
- `playground/bayesopt_latent_discovery_demo/problem.py`

Success means:
1. the evaluator score improves over the current kept baseline
2. the strategy stays deterministic and budget-respecting
3. the search handles latent structure better than naive random search
