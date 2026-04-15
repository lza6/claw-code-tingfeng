from __future__ import annotations

import numpy as np

DIMENSION = 24
INFORMATIVE_DIMS = (1, 5, 11, 17)
NOISE_STD = 0.08


def validate_point(x: np.ndarray) -> np.ndarray:
    arr = np.asarray(x, dtype=float)
    if arr.shape != (DIMENSION,):
        raise ValueError(f"expected shape ({DIMENSION},), got {arr.shape}")
    return np.clip(arr, 0.0, 1.0)


def noiseless_objective(x: np.ndarray) -> float:
    x = validate_point(x)
    a = x[1]
    b = x[5]
    c = x[11]
    d = x[17]

    basin = 2.6 * np.exp(-((a - 0.78) ** 2) / 0.012 - ((b - 0.18) ** 2) / 0.018)
    ridge = 1.1 * np.exp(-((c - 0.31) ** 2) / 0.02)
    wave = 0.55 * np.cos(5.0 * np.pi * d)
    interaction = 0.7 * np.sin(3.5 * np.pi * a * c) + 0.45 * np.cos(2.0 * np.pi * b * d)
    penalties = (
        0.9 * (a - 0.78) ** 2
        + 0.6 * (b - 0.18) ** 2
        + 0.55 * (c - 0.31) ** 2
        + 0.45 * (d - 0.64) ** 2
    )
    return float(basin + ridge + wave + interaction - penalties)


def noisy_objective(x: np.ndarray, rng: np.random.Generator) -> float:
    return noiseless_objective(x) + float(rng.normal(0.0, NOISE_STD))
