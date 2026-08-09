"""Thin wrapper that runs the production fusion math with *learned* priors.

We deliberately do NOT monkey-patch `app.services.ambience_service` globals —
that would bleed RL-specific parameters into the production request pipeline.
Instead, we reproduce the (small, pure) body of `ambience_service.fuse` here,
but sourced from the effective (offset-applied) prior tables.

Keep this file in lock-step with `ambience_service.fuse`. If the production
fusion formula ever changes, update both sides together — otherwise the RL
training loop will optimize against a stale model.
"""
from __future__ import annotations

from typing import Dict, Tuple

from ...services import ambience_service as _amb
from .offsets import OffsetParams, apply_offsets, effective_daypart_windows
from .types import Scenario, SimulatedText


Table = Dict[str, Dict[str, float]]


def _compute_daypart_weights(
    hour_windows,
    windows,
) -> Dict[str, float]:
    """Re-implementation of `ambience_service.compute_daypart_weights` over
    dynamic (learned) `windows`. Same logic as the production version."""
    weights: Dict[str, float] = {name: 0.0 for name, _, _ in windows}
    if not hour_windows:
        return weights
    for start, end in hour_windows:
        for name, d_start, d_end in windows:
            overlap = max(0, min(end, d_end) - max(start, d_start))
            if overlap > 0:
                weights[name] += overlap
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def _daypart_fusion(weights: Dict[str, float], daypart_priors: Table) -> Dict[str, float]:
    total = sum(weights.values())
    if total < 1e-9:
        return {"E": 0.55, "T": 0.55, "M": 0.60}
    E = sum(weights[name] * daypart_priors[name]["E"] for name in weights) / total
    T = sum(weights[name] * daypart_priors[name]["T"] for name in weights) / total
    M = sum(weights[name] * daypart_priors[name]["M"] for name in weights) / total
    return {"E": E, "T": T, "M": M}


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def fuse_with_params(
    params: OffsetParams,
    scenario: Scenario,
    text: SimulatedText,
) -> Tuple[float, float, float]:
    """Run production fusion math using `params` as the active prior set.

    Returns `(E, T, M)` as floats in [0,1] (not the 0..100 integer form used
    by the user-facing pydantic schema).
    """
    eff = apply_offsets(params)
    windows = effective_daypart_windows(params)

    trade_table: Table = eff["trade"]
    type_table: Table = eff["type"]
    daypart_table: Table = eff["daypart"]
    weather_table: Table = eff["weather"]
    default_trade = eff["default_trade"]
    default_type = eff["default_type"]

    area_prior = trade_table.get(scenario.trade_area, default_trade)
    type_prior = type_table.get(scenario.business_type, default_type)

    weights = _compute_daypart_weights(scenario.business_hours, windows)
    time_prior = _daypart_fusion(weights, daypart_table)
    weather_prior = weather_table.get(
        scenario.weather, weather_table.get("cloudy", {"E": 0.52, "T": 0.50, "M": 0.56})
    )

    E_text = text.E_text
    T_text = text.T_text
    M_text = text.M_text
    c_text = text.c_text

    # Same mixing weights as production `fuse`. If production changes these
    # weights, update them here too.
    E_raw = (0.50 * E_text + 0.20 * area_prior["E"] + 0.15 * type_prior["E"]
             + 0.10 * time_prior["E"] + 0.05 * weather_prior["E"])
    T_raw = (0.50 * T_text + 0.20 * area_prior["T"] + 0.15 * type_prior["T"]
             + 0.10 * time_prior["T"] + 0.05 * weather_prior["T"])
    M_raw = (0.50 * M_text + 0.15 * area_prior["M"] + 0.20 * type_prior["M"]
             + 0.05 * time_prior["M"] + 0.10 * weather_prior["M"])

    E_prior_only = 0.55 * area_prior["E"] + 0.45 * type_prior["E"]
    T_prior_only = 0.55 * area_prior["T"] + 0.45 * type_prior["T"]
    M_prior_only = 0.45 * area_prior["M"] + 0.55 * type_prior["M"]

    E = c_text * E_raw + (1 - c_text) * E_prior_only
    T = c_text * T_raw + (1 - c_text) * T_prior_only
    M = c_text * M_raw + (1 - c_text) * M_prior_only

    return _clip01(E), _clip01(T), _clip01(M)
