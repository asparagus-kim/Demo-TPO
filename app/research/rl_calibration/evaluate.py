"""Evaluation utilities for learned offset parameters.

`evaluate_params(params, n_scenarios)` returns a dict with:
    - mean per-axis MSE on fresh noisy scenarios
    - mean per-axis MSE on clean (noise-free) scenarios
    - mean semantic-constraint violation + per-constraint breakdown
    - comparison against baseline (zero offsets ≡ production priors)
    - stability under repeated noise draws

`rollout_policy(trainer, env, n_episodes)` runs the trained policy greedily
(mean action, no sampling) to capture the offsets the agent ends with.
"""
from __future__ import annotations

import json
import random
import statistics
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from .config import REPORT_DIR, ensure_output_dirs
from .constraints import evaluate_constraints
from .environment import CalibrationEnv
from .fusion_bridge import fuse_with_params
from .offsets import (
    OffsetParams,
    apply_offsets,
    build_default_params,
    flat_vector_to_offsets,
    offsets_to_flat_vector,
)
from .reward import RewardBreakdown, compute_reward
from .scenario_generator import generate_batch
from .synthetic_world import hidden_truth
from .text_simulator import simulate_text_evidence


def _scenarios_truths_texts(n: int, seed: int, noisy: bool = True):
    rng = random.Random(seed)
    scenarios = generate_batch(n, rng)
    truths = [hidden_truth(s, noisy=noisy) for s in scenarios]
    texts = [simulate_text_evidence(s, t, rng=rng) for s, t in zip(scenarios, truths)]
    return scenarios, truths, texts


def evaluate_params(
    params: OffsetParams,
    *,
    n_scenarios: int = 400,
    seed: int = 424242,
    reference: Optional[OffsetParams] = None,
) -> Dict[str, object]:
    """Evaluate `params` and compare against a reference (default = zero offsets)."""
    reference = reference or build_default_params()

    # Noise-on fit
    sc_n, tr_n, tx_n = _scenarios_truths_texts(n_scenarios, seed, noisy=True)
    se_params = {"E": 0.0, "T": 0.0, "M": 0.0}
    se_ref = {"E": 0.0, "T": 0.0, "M": 0.0}
    for s, t, x in zip(sc_n, tr_n, tx_n):
        pe, pt, pm = fuse_with_params(params, s, x)
        re_, rt, rm = fuse_with_params(reference, s, x)
        se_params["E"] += (pe - t.energy) ** 2
        se_params["T"] += (pt - t.tempo) ** 2
        se_params["M"] += (pm - t.mood) ** 2
        se_ref["E"] += (re_ - t.energy) ** 2
        se_ref["T"] += (rt - t.tempo) ** 2
        se_ref["M"] += (rm - t.mood) ** 2
    for d in (se_params, se_ref):
        for k in d:
            d[k] /= max(n_scenarios, 1)

    # Noise-off fit
    sc_c, tr_c, tx_c = _scenarios_truths_texts(n_scenarios, seed + 1, noisy=False)
    se_clean_params = {"E": 0.0, "T": 0.0, "M": 0.0}
    for s, t, x in zip(sc_c, tr_c, tx_c):
        pe, pt, pm = fuse_with_params(params, s, x)
        se_clean_params["E"] += (pe - t.energy) ** 2
        se_clean_params["T"] += (pt - t.tempo) ** 2
        se_clean_params["M"] += (pm - t.mood) ** 2
    for k in se_clean_params:
        se_clean_params[k] /= max(n_scenarios, 1)

    # Constraints
    eff = apply_offsets(params)
    cons_mean, cons_per = evaluate_constraints(eff)
    ref_eff = apply_offsets(reference)
    ref_cons_mean, _ = evaluate_constraints(ref_eff)

    # Stability: run the evaluation 3x with different noise seeds → report std
    stability_mses = []
    for k in range(3):
        sc, tr, tx = _scenarios_truths_texts(128, seed + 100 + k, noisy=True)
        se = 0.0
        for s, t, x in zip(sc, tr, tx):
            pe, pt, pm = fuse_with_params(params, s, x)
            se += ((pe - t.energy) ** 2 + (pt - t.tempo) ** 2 + (pm - t.mood) ** 2) / 3.0
        stability_mses.append(se / 128)

    stability_std = statistics.stdev(stability_mses) if len(stability_mses) >= 2 else 0.0

    return {
        "n_scenarios": n_scenarios,
        "mse_noisy_learned": se_params,
        "mse_noisy_reference": se_ref,
        "mse_clean_learned": se_clean_params,
        "constraint_mean_learned": cons_mean,
        "constraint_mean_reference": ref_cons_mean,
        "constraint_breakdown_learned": cons_per,
        "offsets_l1": params.total_magnitude(),
        "stability_mse_std": stability_std,
        "stability_mses": stability_mses,
    }


def rollout_policy(
    trainer,
    env: CalibrationEnv,
    *,
    n_episodes: int = 10,
    greedy: bool = True,
) -> OffsetParams:
    """Run the trained policy and return the *best* offset params encountered.

    "Best" = highest episode-final total reward. Greedy mode uses the policy
    mean; stochastic mode samples. For deployment you want greedy.
    """
    best_params: Optional[OffsetParams] = None
    best_reward = -float("inf")
    for ep in range(n_episodes):
        obs = env.reset()
        done = False
        while not done:
            if greedy:
                mu, _ = trainer.policy.forward(obs)
                act = mu
            else:
                act, _ = trainer.policy.sample(obs, trainer.rng)
            obs, reward, done, _info = env.step(act)
        if reward > best_reward:
            best_reward = reward
            best_params = env.current_params()
    return best_params or build_default_params()


def write_report(
    report: Dict[str, object],
    *,
    name: str = "eval_report",
) -> Path:
    ensure_output_dirs()
    path = REPORT_DIR / f"{name}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path
