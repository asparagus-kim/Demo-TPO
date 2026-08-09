"""Hidden ground-truth ambience for synthetic scenarios.

The synthetic world decides, per scenario, what the "true" E/T/M values are.
The RL agent never sees this directly — it only sees (a) the scenario, (b) the
*simulated* text evidence, and (c) the current reward. The reward is what
implicitly couples the agent to the hidden truth.

Design:
    The hidden truth is *not* the same as the production priors. If it were,
    the optimal offsets would trivially be zero and PPO would have nothing to
    learn. Instead, we define a mildly different "true" world that:
      - shares the same high-level qualitative relationships (office trades
        → high tempo, 주점/바 → high energy, residential → higher mood),
      - but has different numeric values and a slightly different interaction
        structure so the current production priors are *close but not perfect*.
    This lets PPO converge to informative, interpretable offsets.

    All hidden values are deterministic given `(scenario, seed)` so evaluation
    is reproducible. A small amount of Gaussian noise is added to simulate
    unobservable shop-to-shop variation.
"""
from __future__ import annotations

import math
import random
from typing import Dict

from ...services import ambience_service as _amb
from .offsets import AXES
from .types import HiddenTruth, Scenario


# Hidden "world" priors — intentionally different from production priors so
# the agent has a real target to fit. These are the generative ground truth.
_TRUE_TRADE: Dict[str, Dict[str, float]] = {
    "오피스 밀집 상권":   {"E": 0.68, "T": 0.86, "M": 0.48},
    "주거 밀집 상권":     {"E": 0.38, "T": 0.34, "M": 0.78},
    "대학가/유흥 상권":   {"E": 0.90, "T": 0.72, "M": 0.64},
    "복합 오피스 상권":   {"E": 0.66, "T": 0.76, "M": 0.58},
    "관광특구 상권":      {"E": 0.82, "T": 0.66, "M": 0.82},
    "트렌드/패션 상권":   {"E": 0.78, "T": 0.68, "M": 0.88},
    "학원가 특화 상권":   {"E": 0.54, "T": 0.70, "M": 0.52},
    "지식산업센터 상권":  {"E": 0.58, "T": 0.80, "M": 0.46},
}

_TRUE_TYPE: Dict[str, Dict[str, float]] = {
    "카페":            {"E": 0.50, "T": 0.40, "M": 0.84},
    "테이크아웃 카페":  {"E": 0.70, "T": 0.88, "M": 0.60},
    "베이커리 카페":    {"E": 0.56, "T": 0.46, "M": 0.82},
    "일반 음식점":      {"E": 0.60, "T": 0.58, "M": 0.68},
    "패스트푸드":       {"E": 0.86, "T": 0.94, "M": 0.38},
    "주점/바":          {"E": 0.92, "T": 0.70, "M": 0.74},
    "디저트숍":         {"E": 0.52, "T": 0.38, "M": 0.88},
    "편의점형 F&B":     {"E": 0.66, "T": 0.90, "M": 0.34},
}

_TRUE_DAYPART: Dict[str, Dict[str, float]] = {
    "early_morning":  {"E": 0.42, "T": 0.50, "M": 0.60},
    "lunch":          {"E": 0.76, "T": 0.92, "M": 0.48},
    "afternoon":      {"E": 0.48, "T": 0.40, "M": 0.74},
    "dinner":         {"E": 0.74, "T": 0.60, "M": 0.72},
    "late_night":     {"E": 0.86, "T": 0.52, "M": 0.66},
}

_TRUE_WEATHER: Dict[str, Dict[str, float]] = {
    "sunny":      {"E": 0.64, "T": 0.58, "M": 0.72},
    "cloudy":     {"E": 0.50, "T": 0.48, "M": 0.56},
    "rainy":      {"E": 0.44, "T": 0.42, "M": 0.62},
    "snowy":      {"E": 0.38, "T": 0.34, "M": 0.70},
    "hot_humid":  {"E": 0.48, "T": 0.44, "M": 0.46},
    "cold_clear": {"E": 0.46, "T": 0.40, "M": 0.62},
}

# Fixed generative weights — again, subtly different from the production fuse
# weights so that the agent can't just copy the production priors and be
# optimal. Weights sum to 1.0 per axis.
_GEN_WEIGHTS: Dict[str, Dict[str, float]] = {
    "E": {"trade": 0.35, "type": 0.25, "daypart": 0.25, "weather": 0.15},
    "T": {"trade": 0.30, "type": 0.25, "daypart": 0.35, "weather": 0.10},
    "M": {"trade": 0.20, "type": 0.35, "daypart": 0.15, "weather": 0.30},
}

# Gaussian noise sigma — keep small so repeated samples of the same scenario
# cluster tightly around the generative mean.
NOISE_SIGMA: float = 0.04


def _active_daypart(scenario: Scenario) -> str:
    """Pick the daypart `hour_of_day` falls into, matching production windows."""
    h = scenario.hour_of_day
    if 6 <= h < 10:
        return "early_morning"
    if 10 <= h < 14:
        return "lunch"
    if 14 <= h < 17:
        return "afternoon"
    if 17 <= h < 21:
        return "dinner"
    return "late_night"


def _axis_value(axis: str, scenario: Scenario) -> float:
    w = _GEN_WEIGHTS[axis]
    trade = _TRUE_TRADE.get(scenario.trade_area, {"E": 0.55, "T": 0.55, "M": 0.60})
    btype = _TRUE_TYPE.get(scenario.business_type, {"E": 0.55, "T": 0.55, "M": 0.65})
    daypart = _TRUE_DAYPART[_active_daypart(scenario)]
    weather = _TRUE_WEATHER.get(scenario.weather, _TRUE_WEATHER["cloudy"])
    return (
        w["trade"] * trade[axis]
        + w["type"] * btype[axis]
        + w["daypart"] * daypart[axis]
        + w["weather"] * weather[axis]
    )


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def hidden_truth(scenario: Scenario, *, noisy: bool = True) -> HiddenTruth:
    """Compute the generative hidden E/T/M for a scenario.

    Pass `noisy=False` for a clean deterministic value (useful in evaluation).
    """
    rng = random.Random(scenario.seed ^ 0xA11CE)
    vals: Dict[str, float] = {}
    for axis in AXES:
        mean = _axis_value(axis, scenario)
        if noisy:
            mean += rng.gauss(0.0, NOISE_SIGMA)
        vals[axis] = _clip01(mean)
    return HiddenTruth(energy=vals["E"], tempo=vals["T"], mood=vals["M"])


def describe_world() -> Dict[str, Dict[str, Dict[str, float]]]:
    """Introspection helper — return the generative tables."""
    return {
        "trade": {k: {**v} for k, v in _TRUE_TRADE.items()},
        "type": {k: {**v} for k, v in _TRUE_TYPE.items()},
        "daypart": {k: {**v} for k, v in _TRUE_DAYPART.items()},
        "weather": {k: {**v} for k, v in _TRUE_WEATHER.items()},
    }
