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


def fit_gp(X: np.ndarray, y: np.ndarray, length_scale: float = 0.22) -> GaussianProcessRegressor:
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


def infer_active_dimensions(X: np.ndarray, y: np.ndarray, top_k: int) -> list[int]:
    X_centered = X - X.mean(axis=0, keepdims=True)
    y_centered = y - y.mean()
    scale = np.maximum(np.std(X_centered, axis=0), 1e-8)
    standardized = X_centered / scale
    coeffs, *_ = np.linalg.lstsq(standardized, y_centered, rcond=None)
    order = np.argsort(np.abs(coeffs))[-top_k:]
    return sorted(int(idx) for idx in order)


def choose_anchor(X: np.ndarray, y: np.ndarray, mode: str) -> np.ndarray:
    if mode == 'center':
        return np.full(X.shape[1], 0.5, dtype=float)
    return X[int(np.argmax(y))].copy()


def run_random_search(config: dict[str, Any]) -> dict[str, Any]:
    dim = int(config.get('dimension', DIMENSION))
    budget = int(config.get('budget', 64))
    final_resamples = int(config.get('final_resamples', 24))
    seed = int(config.get('seed', 23))
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


def run_cem_search(config: dict[str, Any]) -> dict[str, Any]:
    dim = int(config.get('dimension', DIMENSION))
    budget = int(config.get('budget', 64))
    final_resamples = int(config.get('final_resamples', 24))
    seed = int(config.get('seed', 23))
    params = dict(config.get('params', {}))
    batch_size = int(params.get('cem_batch_size', 8))
    rng = np.random.default_rng(seed)

    mean = np.full(dim, 0.5, dtype=float)
    std = np.full(dim, 0.28, dtype=float)
    all_points: list[np.ndarray] = []
    all_scores: list[float] = []

    for offset in range(0, budget, batch_size):
        current_batch = min(batch_size, budget - offset)
        if offset == 0:
            points = sample_uniform(rng, current_batch, dim)
        else:
            points = np.clip(rng.normal(mean, std, size=(current_batch, dim)), 0.0, 1.0)

        scores = np.array([noisy_objective(point, rng) for point in points], dtype=float)
        all_points.append(points)
        all_scores.append(scores)

        X = np.vstack(all_points)
        y = np.concatenate(all_scores)
        elite = X[np.argsort(y)[-max(4, len(y) // 6):]]
        mean = elite.mean(axis=0)
        std = np.clip(elite.std(axis=0), 0.05, 0.25)

    X = np.vstack(all_points)
    y = np.concatenate(all_scores)
    incumbent = X[int(np.argmax(y))]
    resample_rng = np.random.default_rng(seed + 10_000)
    final_scores = np.array([noisy_objective(incumbent, resample_rng) for _ in range(final_resamples)], dtype=float)
    return {
        'algorithm': 'cem_search',
        'best_observed': float(np.max(y)),
        'best_mean': float(final_scores.mean()),
        'best_std': float(final_scores.std(ddof=0)),
        'best_noiseless': float(noiseless_objective(incumbent)),
        'incumbent': incumbent.tolist(),
    }


def run_screened_bayesian_gp(config: dict[str, Any]) -> dict[str, Any]:
    dim = int(config.get('dimension', DIMENSION))
    budget = int(config.get('budget', 64))
    final_resamples = int(config.get('final_resamples', 24))
    seed = int(config.get('seed', 23))
    params = dict(config.get('params', {}))

    n_initial_random = int(params.get('n_initial_random', 18))
    top_k = int(params.get('top_k', 6))
    candidate_pool_size = int(params.get('candidate_pool_size', 2500))
    final_candidate_pool_size = int(params.get('final_candidate_pool_size', max(candidate_pool_size, 5000)))
    acq_beta = float(params.get('acq_beta', 1.25))
    gp_length_scale = float(params.get('gp_length_scale', 0.22))
    inactive_value = float(params.get('inactive_value', 0.5))
    anchor_mode = str(params.get('anchor_mode', 'best_observed'))

    rng = np.random.default_rng(seed)
    X: list[np.ndarray] = []
    y: list[float] = []

    for _ in range(n_initial_random):
        x = sample_uniform(rng, 1, dim)[0]
        X.append(x)
        y.append(float(noisy_objective(x, rng)))

    X_array = np.asarray(X, dtype=float)
    y_array = np.asarray(y, dtype=float)
    active_dimensions = infer_active_dimensions(X_array, y_array, top_k)
    anchor = choose_anchor(X_array, y_array, anchor_mode)

    while len(X) < budget:
        X_array = np.asarray(X, dtype=float)
        y_array = np.asarray(y, dtype=float)
        gp = fit_gp(X_array[:, active_dimensions], y_array, length_scale=gp_length_scale)
        candidate_points = np.tile(anchor, (candidate_pool_size, 1))
        candidate_points[:, active_dimensions] = sample_subspace_uniform(
            rng,
            candidate_pool_size,
            dim,
            active_dimensions,
            inactive_value=inactive_value,
        )[:, active_dimensions]
        mu, std = gp.predict(candidate_points[:, active_dimensions], return_std=True)
        acquisition = mu + acq_beta * std
        x_next = candidate_points[int(np.argmax(acquisition))]
        X.append(x_next)
        y.append(float(noisy_objective(x_next, rng)))

    X_array = np.asarray(X, dtype=float)
    y_array = np.asarray(y, dtype=float)
    gp = fit_gp(X_array[:, active_dimensions], y_array, length_scale=gp_length_scale)
    final_candidate_rng = np.random.default_rng(seed + 12_345)
    final_candidates = np.tile(anchor, (final_candidate_pool_size, 1))
    final_candidates[:, active_dimensions] = sample_subspace_uniform(
        final_candidate_rng,
        final_candidate_pool_size,
        dim,
        active_dimensions,
        inactive_value=inactive_value,
    )[:, active_dimensions]
    final_candidates = np.vstack([final_candidates, X_array])
    final_mu = gp.predict(final_candidates[:, active_dimensions])
    incumbent = final_candidates[int(np.argmax(final_mu))]

    resample_rng = np.random.default_rng(seed + 10_000)
    final_scores = np.array([noisy_objective(incumbent, resample_rng) for _ in range(final_resamples)], dtype=float)
    return {
        'algorithm': 'screened_bayesian_gp',
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
    if algorithm == 'cem_search':
        return run_cem_search(config)
    if algorithm == 'screened_bayesian_gp':
        return run_screened_bayesian_gp(config)
    raise ValueError(f'Unsupported algorithm: {algorithm}')
