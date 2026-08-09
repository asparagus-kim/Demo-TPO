"""Simulated text-evidence generator.

Produces a `SimulatedText` that mirrors the structure of
`app.services.llm_service.aggregate_text_scores(...)` output:
    {E_text, T_text, M_text, c_text, n, q, d}

Instead of calling an LLM on synthetic reviews, we skip that layer entirely
and sample (E_text, T_text, M_text) as noisy observations of the hidden truth.
`c_text` is then computed from review count, informativeness, and consistency
using the same functional form as the real aggregator. This keeps the
agent's view of evidence quality realistic without needing to synthesize
Korean review text.
"""
from __future__ import annotations

import math
import random
from typing import Tuple

from .types import HiddenTruth, Scenario, SimulatedText


# Noise on the *observed* (text-derived) scores relative to truth. Larger
# than `synthetic_world.NOISE_SIGMA` because text evidence is noisier than
# the generative mean itself.
TEXT_NOISE_SIGMA: float = 0.10


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def simulate_text_evidence(
    scenario: Scenario,
    truth: HiddenTruth,
    *,
    rng: random.Random | None = None,
) -> SimulatedText:
    """Return a SimulatedText for the given scenario + hidden truth.

    The shape of `c_text` is deliberately aligned to `aggregate_text_scores`:
        c_text = min(1, 0.35 * log(1+N) + 0.35 * q + 0.30 * d)
    where N = number of reviews, q = mean informativeness, d = consistency.
    """
    if rng is None:
        rng = random.Random(scenario.seed ^ 0xBEEF)

    N = max(0, int(scenario.review_count))

    # Effective per-review noise shrinks as N grows (Central Limit intuition).
    denom = math.sqrt(max(N, 1))
    sigma = TEXT_NOISE_SIGMA / denom

    E_text = _clip01(truth.energy + rng.gauss(0.0, sigma))
    T_text = _clip01(truth.tempo + rng.gauss(0.0, sigma))
    M_text = _clip01(truth.mood + rng.gauss(0.0, sigma))

    if N == 0:
        # No reviews at all — text pipeline returns a neutral 0.5 with c_text=0.
        return SimulatedText(E_text=0.5, T_text=0.5, M_text=0.5, c_text=0.0, n=0)

    # Informativeness grows with count and length; here we just use a simple
    # monotone function of N plus a bit of noise.
    q = min(1.0, 0.4 + N / 40.0 + rng.gauss(0.0, 0.05))
    q = max(0.2, q)

    # Consistency: pretend the per-review std is proportional to sigma above.
    # In production this is `d = max(0, 1 - avg_std * 1.4)`.
    d = max(0.0, 1.0 - sigma * 1.4 * 2.0)

    c_text = min(1.0, 0.35 * math.log(1 + N) + 0.35 * q + 0.30 * d)
    return SimulatedText(
        E_text=E_text, T_text=T_text, M_text=M_text,
        c_text=float(c_text), n=N,
    )


def simulate_batch(
    scenarios,
    truths,
    *,
    rng: random.Random | None = None,
):
    if rng is None:
        rng = random.Random()
    out = []
    for s, t in zip(scenarios, truths):
        out.append(simulate_text_evidence(s, t, rng=rng))
    return out
