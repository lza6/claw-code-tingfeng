from __future__ import annotations

import numpy as np

DIMENSION = 32
NOISE_STD = 0.10

# Fixed latent mixing matrix. Rows are normalized to keep scales stable.
_PROJECTION = np.array([
    [0.04, -0.02, 0.10, -0.01, 0.03, 0.18, -0.08, 0.06, 0.02, -0.03, 0.01, 0.16, -0.02, 0.05, -0.04, 0.09, 0.03, 0.21, -0.05, 0.02, 0.04, -0.03, 0.07, 0.01, -0.02, 0.11, -0.06, 0.03, 0.08, -0.01, 0.02, 0.04],
    [-0.03, 0.12, 0.05, -0.02, 0.07, -0.14, 0.09, 0.01, -0.04, 0.10, 0.03, -0.11, 0.06, 0.02, -0.05, 0.13, -0.07, 0.04, 0.08, -0.02, 0.15, 0.01, -0.03, 0.05, 0.09, -0.04, 0.02, 0.11, -0.06, 0.07, 0.03, -0.01],
    [0.02, 0.06, -0.04, 0.13, 0.08, -0.01, 0.05, 0.15, -0.07, 0.03, 0.09, 0.02, 0.11, -0.05, 0.04, 0.07, -0.02, 0.12, 0.06, 0.01, -0.03, 0.14, 0.05, -0.06, 0.02, 0.08, 0.10, -0.04, 0.03, 0.09, -0.01, 0.16],
    [0.11, -0.05, 0.03, 0.07, -0.02, 0.04, 0.13, -0.06, 0.01, 0.09, -0.04, 0.05, 0.02, 0.12, -0.03, 0.08, 0.06, -0.01, 0.10, 0.04, -0.05, 0.07, 0.03, 0.14, -0.02, 0.06, 0.01, 0.09, -0.04, 0.05, 0.13, -0.03],
], dtype=float)
PROJECTION = _PROJECTION / np.linalg.norm(_PROJECTION, axis=1, keepdims=True)


def validate_point(x: np.ndarray) -> np.ndarray:
    arr = np.asarray(x, dtype=float)
    if arr.shape != (DIMENSION,):
        raise ValueError(f"expected shape ({DIMENSION},), got {arr.shape}")
    return np.clip(arr, 0.0, 1.0)


def latent_coordinates(x: np.ndarray) -> np.ndarray:
    x = validate_point(x)
    centered = x - 0.5
    return PROJECTION @ centered


def noiseless_objective(x: np.ndarray) -> float:
    z0, z1, z2, z3 = latent_coordinates(x)
    basin = 3.0 * np.exp(-((z0 - 0.11) ** 2) / 0.010 - ((z1 + 0.18) ** 2) / 0.016)
    ridge = 1.25 * np.exp(-((z2 - 0.04) ** 2) / 0.024)
    wave = 0.60 * np.cos(6.0 * np.pi * z3)
    interaction = 0.55 * np.sin(10.0 * (z0 + 0.5) * (z2 + 0.5)) + 0.40 * np.cos(8.0 * (z1 + 0.5) * (z3 + 0.5))
    penalties = 0.95 * (z0 - 0.11) ** 2 + 0.75 * (z1 + 0.18) ** 2 + 0.60 * (z2 - 0.04) ** 2 + 0.35 * (z3 - 0.07) ** 2
    return float(basin + ridge + wave + interaction - penalties)


def noisy_objective(x: np.ndarray, rng: np.random.Generator) -> float:
    return noiseless_objective(x) + float(rng.normal(0.0, NOISE_STD))
