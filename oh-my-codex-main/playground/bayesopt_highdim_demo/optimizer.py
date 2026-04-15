from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

from problem import DIMENSION, NOISE_STD, noisy_objective, noiseless_objective

CONFIG_PATH = Path(__file__).with_name('config.json')


def load_config(path: str | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else CONFIG_PATH
    return json.loads(cfg_path.read_text())


def sample_uniform(rng: np.random.Generator, n: int, dim: int = DIMENSION) -> np.ndarray:
    return rng.random((n, dim))


def resolve_active_dimensions(dim: int, raw: Any) -> list[int]:
    if raw is None:
        return list(range(dim))
    active = [int(v) for v in raw]
    if not active:
        raise ValueError('active_dimensions cannot be empty')
    if any(v < 0 or v >= dim for v in active):
        raise ValueError(f'active_dimensions must stay within [0, {dim})')
    return sorted(dict.fromkeys(active))


def sample_subspace_uniform(
    rng: np.random.Generator,
    n: int,
    dim: int,
    active_dimensions: list[int],
    inactive_value: float = 0.5,
) -> np.ndarray:
    points = np.full((n, dim), inactive_value, dtype=float)
    points[:, active_dimensions] = rng.random((n, len(active_dimensions)))
    return points


def fit_gp(X: np.ndarray, y: np.ndarray, length_scale: float = 0.18) -> GaussianProcessRegressor:
    kernel = (
        ConstantKernel(1.0, constant_value_bounds='fixed')
        * Matern(length_scale=np.full(X.shape[1], length_scale), length_scale_bounds='fixed', nu=2.5)
        + WhiteKernel(noise_level=NOISE_STD ** 2, noise_level_bounds='fixed')
    )
    gp = GaussianProcessRegressor(
        kernel=kernel,
        normalize_y=True,
        alpha=1e-6,
        random_state=0,
        optimizer=None,
    )
    gp.fit(X, y)
    return gp


def run_random_search(config: dict[str, Any]) -> dict[str, Any]:
    dim = int(config.get('dimension', DIMENSION))
    budget = int(config.get('budget', 48))
    final_resamples = int(config.get('final_resamples', 24))
    seed = int(config.get('seed', 17))
    rng = np.random.default_rng(seed)

    points = sample_uniform(rng, budget, dim)
    observations = np.array([noisy_objective(point, rng) for point in points], dtype=float)
    incumbent_index = int(np.argmax(observations))
    incumbent = points[incumbent_index]

    resample_rng = np.random.default_rng(seed + 10_000)
    final_scores = np.array([noisy_objective(incumbent, resample_rng) for _ in range(final_resamples)], dtype=float)
    return {
        'algorithm': 'random_search',
        'best_observed': float(observations[incumbent_index]),
        'best_mean': float(final_scores.mean()),
        'best_std': float(final_scores.std(ddof=0)),
        'best_noiseless': float(noiseless_objective(incumbent)),
        'incumbent': incumbent.tolist(),
    }


def run_bayesian_gp(config: dict[str, Any]) -> dict[str, Any]:
    dim = int(config.get('dimension', DIMENSION))
    budget = int(config.get('budget', 48))
    final_resamples = int(config.get('final_resamples', 24))
    seed = int(config.get('seed', 17))
    params = dict(config.get('params', {}))

    n_initial_random = int(params.get('n_initial_random', 10))
    candidate_pool_size = int(params.get('candidate_pool_size', 1500))
    final_candidate_pool_size = int(params.get('final_candidate_pool_size', max(candidate_pool_size, 4000)))
    acq_beta = float(params.get('acq_beta', 1.5))
    gp_length_scale = float(params.get('gp_length_scale', 0.18))
    inactive_value = float(params.get('inactive_value', 0.5))
    active_dimensions = resolve_active_dimensions(dim, params.get('active_dimensions'))

    rng = np.random.default_rng(seed)
    X: list[np.ndarray] = []
    y: list[float] = []

    while len(X) < budget:
        if len(X) < n_initial_random:
            x_next = sample_subspace_uniform(rng, 1, dim, active_dimensions, inactive_value=inactive_value)[0]
        else:
            X_array = np.asarray(X, dtype=float)
            y_array = np.asarray(y, dtype=float)
            gp = fit_gp(X_array[:, active_dimensions], y_array, length_scale=gp_length_scale)
            candidate_points = sample_subspace_uniform(
                rng,
                candidate_pool_size,
                dim,
                active_dimensions,
                inactive_value=inactive_value,
            )
            mu, std = gp.predict(candidate_points[:, active_dimensions], return_std=True)
            acquisition = mu + acq_beta * std
            x_next = candidate_points[int(np.argmax(acquisition))]

        X.append(x_next)
        y.append(float(noisy_objective(x_next, rng)))

    X_array = np.asarray(X, dtype=float)
    y_array = np.asarray(y, dtype=float)
    gp = fit_gp(X_array[:, active_dimensions], y_array, length_scale=gp_length_scale)
    final_candidate_rng = np.random.default_rng(seed + 12_345)
    final_candidates = sample_subspace_uniform(
        final_candidate_rng,
        final_candidate_pool_size,
        dim,
        active_dimensions,
        inactive_value=inactive_value,
    )
    final_candidates = np.vstack([final_candidates, X_array])
    final_mu = gp.predict(final_candidates[:, active_dimensions])
    incumbent = final_candidates[int(np.argmax(final_mu))]
    resample_rng = np.random.default_rng(seed + 10_000)
    final_scores = np.array([noisy_objective(incumbent, resample_rng) for _ in range(final_resamples)], dtype=float)
    return {
        'algorithm': 'bayesian_gp',
        'active_dimensions': active_dimensions,
        'best_observed': float(np.max(y_array)),
        'best_mean': float(final_scores.mean()),
        'best_std': float(final_scores.std(ddof=0)),
        'best_noiseless': float(noiseless_objective(incumbent)),
        'incumbent': incumbent.tolist(),
    }


def run_search(config: dict[str, Any]) -> dict[str, Any]:
    algorithm = config.get('algorithm', 'random_search')
    if algorithm == 'random_search':
        return run_random_search(config)
    if algorithm == 'bayesian_gp':
        return run_bayesian_gp(config)
    raise ValueError(f'Unsupported algorithm: {algorithm}')
