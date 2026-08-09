"""Synthetic scenario generator.

Produces shop contexts (trade area, business type, business hours, weather,
hour-of-day, review count) by sampling from distributions calibrated against
the production priors. Determinism is controlled via a seeded `random.Random`
so PPO rollouts are reproducible.

We deliberately sample business_type *conditioned* on trade_area so that e.g.
`대학가/유흥 상권` leans toward `주점/바` and `오피스 밀집 상권` leans toward
café/takeaway — this gives the agent a meaningful joint distribution to fit
rather than a uniform mixture.
"""
from __future__ import annotations

import random
from typing import List, Optional, Tuple

from .offsets import DAYPART_KEYS, TRADE_KEYS, TYPE_KEYS, WEATHER_KEYS
from .types import Scenario


# --- Conditional type mixtures --------------------------------------------
# Weights are intentionally *not* uniform — they encode the synthetic "world's"
# belief that certain trade areas prefer certain shop types.
_TYPE_MIX_BY_TRADE: dict = {
    "오피스 밀집 상권":    {"카페": 0.22, "테이크아웃 카페": 0.30, "패스트푸드": 0.20,
                       "편의점형 F&B": 0.12, "일반 음식점": 0.10, "베이커리 카페": 0.06},
    "주거 밀집 상권":      {"카페": 0.28, "일반 음식점": 0.25, "베이커리 카페": 0.15,
                       "디저트숍": 0.15, "편의점형 F&B": 0.10, "테이크아웃 카페": 0.07},
    "대학가/유흥 상권":    {"주점/바": 0.35, "카페": 0.18, "패스트푸드": 0.15,
                       "일반 음식점": 0.15, "디저트숍": 0.10, "테이크아웃 카페": 0.07},
    "복합 오피스 상권":    {"카페": 0.25, "테이크아웃 카페": 0.25, "일반 음식점": 0.18,
                       "패스트푸드": 0.15, "베이커리 카페": 0.10, "편의점형 F&B": 0.07},
    "관광특구 상권":       {"카페": 0.22, "디저트숍": 0.20, "일반 음식점": 0.20,
                       "주점/바": 0.18, "베이커리 카페": 0.12, "테이크아웃 카페": 0.08},
    "트렌드/패션 상권":    {"카페": 0.30, "디저트숍": 0.25, "베이커리 카페": 0.15,
                       "일반 음식점": 0.12, "주점/바": 0.10, "테이크아웃 카페": 0.08},
    "학원가 특화 상권":    {"테이크아웃 카페": 0.30, "카페": 0.25, "편의점형 F&B": 0.15,
                       "패스트푸드": 0.15, "디저트숍": 0.10, "일반 음식점": 0.05},
    "지식산업센터 상권":  {"테이크아웃 카페": 0.35, "카페": 0.25, "편의점형 F&B": 0.18,
                       "패스트푸드": 0.12, "일반 음식점": 0.07, "베이커리 카페": 0.03},
}

# Trade area prior — uniform-ish, but we bias lightly toward more common ones.
_TRADE_WEIGHTS: dict = {
    "오피스 밀집 상권": 0.17, "주거 밀집 상권": 0.22, "대학가/유흥 상권": 0.12,
    "복합 오피스 상권": 0.12, "관광특구 상권": 0.08, "트렌드/패션 상권": 0.10,
    "학원가 특화 상권": 0.10, "지식산업센터 상권": 0.09,
}

# Weather prior — reflects rough climatological frequency in urban Korea.
_WEATHER_WEIGHTS: dict = {
    "sunny": 0.30, "cloudy": 0.28, "rainy": 0.12, "snowy": 0.05,
    "hot_humid": 0.15, "cold_clear": 0.10,
}


def _weighted_choice(rng: random.Random, weights: dict) -> str:
    keys = list(weights.keys())
    vals = list(weights.values())
    total = sum(vals) or 1.0
    r = rng.random() * total
    cum = 0.0
    for k, v in zip(keys, vals):
        cum += v
        if r <= cum:
            return k
    return keys[-1]


def _sample_business_hours(rng: random.Random, business_type: str) -> List[Tuple[int, int]]:
    """Return (start, end) pairs. `end` may exceed 24 when a shop wraps midnight.

    The distributions here are intentionally coarse — they only need to cover
    the hour ranges the production `compute_daypart_weights` cares about.
    """
    if business_type == "주점/바":
        # Late-opening, late-closing — usually single window, wraps midnight.
        start = rng.choice([17, 18, 18, 19, 20])
        end = start + rng.choice([5, 6, 7, 8])
        return [(start, end)]
    if business_type == "테이크아웃 카페":
        start = rng.choice([6, 6, 7, 7, 8])
        end = rng.choice([18, 19, 20, 20, 21])
        return [(start, end)]
    if business_type in ("카페", "베이커리 카페"):
        start = rng.choice([7, 8, 8, 9, 10])
        end = rng.choice([20, 21, 21, 22, 22])
        return [(start, end)]
    if business_type == "패스트푸드":
        start = rng.choice([10, 10, 11, 11])
        end = rng.choice([21, 22, 23, 24])
        return [(start, end)]
    if business_type == "디저트숍":
        start = rng.choice([11, 11, 12, 12])
        end = rng.choice([20, 21, 21, 22])
        return [(start, end)]
    if business_type == "편의점형 F&B":
        start = rng.choice([6, 7, 7, 8])
        end = rng.choice([22, 23, 23, 24])
        return [(start, end)]
    # "일반 음식점" and any non-F&B fallback
    start = rng.choice([10, 11, 11, 12])
    end = rng.choice([20, 21, 22, 22])
    return [(start, end)]


def generate_scenario(rng: Optional[random.Random] = None, *, seed: Optional[int] = None) -> Scenario:
    """Sample a single synthetic Scenario.

    Pass either `rng` (for repeated sampling in one episode) or `seed` (for
    one-off deterministic use in tests).
    """
    if rng is None:
        rng = random.Random(seed)

    trade = _weighted_choice(rng, _TRADE_WEIGHTS)
    mix = _TYPE_MIX_BY_TRADE.get(trade, {"카페": 1.0})
    btype = _weighted_choice(rng, mix)
    hours = _sample_business_hours(rng, btype)
    weather = _weighted_choice(rng, _WEATHER_WEIGHTS)
    hour_of_day = rng.randint(0, 23)
    # Review count is zero-inflated: roughly 20% of synthetic shops have
    # very sparse evidence so the agent sees a realistic range of c_text.
    if rng.random() < 0.20:
        n_reviews = rng.randint(0, 2)
    else:
        n_reviews = rng.randint(3, 40)

    return Scenario(
        trade_area=trade,
        business_type=btype,
        business_hours=hours,
        weather=weather,
        hour_of_day=hour_of_day,
        review_count=n_reviews,
        seed=rng.randint(0, 10**9),
    )


def generate_batch(n: int, rng: Optional[random.Random] = None, *, seed: Optional[int] = None) -> List[Scenario]:
    """Sample `n` scenarios sharing one RNG so correlated draws stay consistent."""
    if rng is None:
        rng = random.Random(seed)
    return [generate_scenario(rng) for _ in range(n)]
