"""Composite reward for the PPO calibration environment.

Reward = w_fit    * (-MSE against hidden truth, averaged over scenarios)
       + w_cons   * (-mean semantic constraint violation)
       + w_stab   * (-step-to-step offset drift, supplied by env)
       + w_reg    * (-L1 magnitude of the full offset vector)
       + w_bounds * (-fraction of clipped entries in effective tables)

Each term is negative-when-bad, so higher reward is better. The weights come
from `config.RewardWeights`. This is intentionally a pure function — the env
handles stateful bookkeeping (previous offsets, cumulative drift).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .config import RewardWeights
from .constraints import evaluate_constraints
from .fusion_bridge import fuse_with_params
from .offsets import OffsetParams, apply_offsets
from .types import HiddenTruth, Scenario, SimulatedText


@dataclass
class RewardBreakdown:
    total: float
    fit: float
    constraint: float
    stability: float
    regularization: float
    bounds: float
    per_axis_mse: Dict[str, float]
    constraint_violations: Dict[str, float]

    def as_dict(self) -> Dict[str, float]:
        return {
            "total": self.total,
            "fit": self.fit,
            "constraint": self.constraint,
            "stability": self.stability,
            "regularization": self.regularization,
            "bounds": self.bounds,
            **{f"mse_{k}": v for k, v in self.per_axis_mse.items()},
        }


def _mse(preds: List[Tuple[float, float, float]],
         truths: List[HiddenTruth]) -> Tuple[float, Dict[str, float]]:
    if not preds:
        return 0.0, {"E": 0.0, "T": 0.0, "M": 0.0}
    se_e = se_t = se_m = 0.0
    for (e, t, m), truth in zip(preds, truths):
        se_e += (e - truth.energy) ** 2
        se_t += (t - truth.tempo) ** 2
        se_m += (m - truth.mood) ** 2
    n = len(preds)
    per = {"E": se_e / n, "T": se_t / n, "M": se_m / n}
    return (per["E"] + per["T"] + per["M"]) / 3.0, per


def _bounds_fraction_clipped(params: OffsetParams) -> float:
    """Fraction of effective-table entries that hit the 0 or 1 clip."""
    eff = apply_offsets(params)
    n = 0
    clipped = 0
    for tbl_name in ("trade", "type", "daypart", "weather"):
        for vals in eff[tbl_name].values():
            for v in vals.values():
                n += 1
                if v <= 1e-9 or v >= 1.0 - 1e-9:
                    clipped += 1
    for tbl_name in ("default_trade", "default_type"):
        for v in eff[tbl_name].values():
            n += 1
            if v <= 1e-9 or v >= 1.0 - 1e-9:
                clipped += 1
    return clipped / max(n, 1)


def compute_reward(
    *,
    params: OffsetParams,
    scenarios: List[Scenario],
    truths: List[HiddenTruth],
    texts: List[SimulatedText],
    stability_penalty: float,
    weights: RewardWeights,
) -> RewardBreakdown:
    """Evaluate the current `params` against a batch of synthetic scenarios.

    `stability_penalty` is the L2 norm of (flat_offset_now - flat_offset_prev),
    computed by the env over the most recent environment step.
    """
    preds = [fuse_with_params(params, s, t) for s, t in zip(scenarios, texts)]
    fit_mse, per_axis = _mse(preds, truths)
    fit_term = -fit_mse

    eff = apply_offsets(params)
    cons_mean, cons_per = evaluate_constraints(eff)
    cons_term = -cons_mean

    stab_term = -stability_penalty

    reg_term = -params.total_magnitude() / 64.0  # normalize by rough max L1

    bounds_term = -_bounds_fraction_clipped(params)

    total = (
        weights.fit * fit_term
        + weights.constraint * cons_term
        + weights.stability * stab_term
        + weights.regularization * reg_term
        + weights.bounds_penalty * bounds_term
    )

    return RewardBreakdown(
        total=total,
        fit=fit_term,
        constraint=cons_term,
        stability=stab_term,
        regularization=reg_term,
        bounds=bounds_term,
        per_axis_mse=per_axis,
        constraint_violations=cons_per,
    )
