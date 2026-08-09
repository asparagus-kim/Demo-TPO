"""Gradient-free baselines for sanity-checking PPO.

Every PPO calibration project needs a comparison against simpler optimizers.
If PPO can't outperform random search and a CMA-style local search on this
synthetic task, it isn't earning its complexity.

This module provides two baselines:
    - `random_search(n_iters)` : sample flat offset vectors uniformly within
      bounds and keep the best-rewarding one.
    - `hillclimb(n_iters)` : coordinate-wise hill climbing with a shrinking
      step size. A compact proxy for CMA-ES without the dependency.
"""
from __future__ import annotations

import random
from typing import Callable, Tuple

import numpy as np

from .config import (
    DAYPART_WINDOW_SHIFT_BOUND,
    EnvConfig,
    OFFSET_BOUND_BASE,
    OFFSET_BOUND_DAYPART,
    OFFSET_BOUND_DEFAULT,
    OFFSET_BOUND_TRADE,
    OFFSET_BOUND_TYPE,
    OFFSET_BOUND_WEATHER,
    RewardWeights,
)
from .offsets import (
    OFFSET_VECTOR_DIM,
    OffsetParams,
    build_default_params,
    flat_bounds,
    flat_vector_to_offsets,
    offsets_to_flat_vector,
)
from .reward import compute_reward
from .scenario_generator import generate_batch
from .synthetic_world import hidden_truth
from .text_simulator import simulate_text_evidence


def _bounds() -> np.ndarray:
    return np.asarray(
        flat_bounds(
            base_bound=OFFSET_BOUND_BASE,
            trade_bound=OFFSET_BOUND_TRADE,
            type_bound=OFFSET_BOUND_TYPE,
            daypart_bound=OFFSET_BOUND_DAYPART,
            weather_bound=OFFSET_BOUND_WEATHER,
            default_bound=OFFSET_BOUND_DEFAULT,
            window_shift_bound=DAYPART_WINDOW_SHIFT_BOUND,
        ),
        dtype=np.float64,
    )


def _evaluator(n_scenarios: int, seed: int, reward_weights: RewardWeights) -> Callable[[np.ndarray], float]:
    rng = random.Random(seed)
    scenarios = generate_batch(n_scenarios, rng)
    truths = [hidden_truth(s, noisy=True) for s in scenarios]
    texts = [simulate_text_evidence(s, t, rng=rng) for s, t in zip(scenarios, truths)]

    def eval_vec(vec: np.ndarray) -> float:
        params = flat_vector_to_offsets(vec.tolist())
        br = compute_reward(
            params=params,
            scenarios=scenarios,
            truths=truths,
            texts=texts,
            stability_penalty=0.0,
            weights=reward_weights,
        )
        return br.total

    return eval_vec


def random_search(
    n_iters: int = 500,
    *,
    n_scenarios: int = 128,
    seed: int = 1234,
    reward_weights: RewardWeights | None = None,
) -> Tuple[OffsetParams, float]:
    """Return the best random-offset params and their total reward."""
    reward_weights = reward_weights or RewardWeights()
    rng = np.random.default_rng(seed)
    bounds = _bounds()
    eval_vec = _evaluator(n_scenarios, seed, reward_weights)

    best_vec = np.zeros(OFFSET_VECTOR_DIM, dtype=np.float64)
    best_reward = eval_vec(best_vec)
    for _ in range(n_iters):
        cand = rng.uniform(low=-bounds, high=bounds)
        r = eval_vec(cand)
        if r > best_reward:
            best_reward = r
            best_vec = cand
    return flat_vector_to_offsets(best_vec.tolist()), float(best_reward)


def hillclimb(
    n_iters: int = 300,
    *,
    n_scenarios: int = 128,
    seed: int = 4321,
    reward_weights: RewardWeights | None = None,
    start: OffsetParams | None = None,
    initial_step_scale: float = 0.5,
    shrink_every: int = 40,
    shrink_factor: float = 0.7,
) -> Tuple[OffsetParams, float]:
    """Coordinate-wise hill climb with a shrinking step."""
    reward_weights = reward_weights or RewardWeights()
    rng = np.random.default_rng(seed)
    bounds = _bounds()
    eval_vec = _evaluator(n_scenarios, seed, reward_weights)

    if start is None:
        x = np.zeros(OFFSET_VECTOR_DIM, dtype=np.float64)
    else:
        x = np.asarray(offsets_to_flat_vector(start), dtype=np.float64)
    best_reward = eval_vec(x)
    step_scale = initial_step_scale

    for it in range(n_iters):
        # Propose a single-coordinate perturbation
        coord = int(rng.integers(0, OFFSET_VECTOR_DIM))
        direction = 1.0 if rng.random() < 0.5 else -1.0
        trial = x.copy()
        trial[coord] += direction * step_scale * bounds[coord]
        trial = np.clip(trial, -bounds, bounds)
        r = eval_vec(trial)
        if r > best_reward:
            best_reward = r
            x = trial
        if (it + 1) % shrink_every == 0:
            step_scale *= shrink_factor

    return flat_vector_to_offsets(x.tolist()), float(best_reward)
