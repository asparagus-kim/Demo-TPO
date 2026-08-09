"""Dataclasses for the synthetic calibration pipeline.

These intentionally mirror — but do NOT replace — the production pydantic
schemas in `app.schemas`. The calibration subsystem operates on plain dataclasses
so it can be sampled millions of times without pydantic validation overhead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Scenario:
    """Synthetic shop context — all the inputs needed to compute a fused score."""
    trade_area: str
    business_type: str
    business_hours: List[Tuple[int, int]]   # list of (start_hour, end_hour_maybe>24)
    weather: str                             # key into WEATHER_PRIORS (or unknown)
    hour_of_day: int                         # 0..23 — "current" hour for daypart peak
    review_count: int                        # how many synthetic reviews exist
    # Latent seed used by the text simulator to produce consistent evidence.
    seed: int = 0

    def describe(self) -> str:
        hours = ", ".join(f"{s:02d}-{e:02d}" for s, e in self.business_hours) or "n/a"
        return (
            f"Scenario(trade={self.trade_area!r}, type={self.business_type!r}, "
            f"hours=[{hours}], weather={self.weather}, hour={self.hour_of_day}, n_reviews={self.review_count})"
        )


@dataclass
class HiddenTruth:
    """Ground-truth ambience the synthetic world 'knows' — kept hidden from the agent."""
    energy: float   # [0,1]
    tempo: float    # [0,1]
    mood: float     # [0,1]

    def as_dict(self) -> Dict[str, float]:
        return {"E": self.energy, "T": self.tempo, "M": self.mood}


@dataclass
class SimulatedText:
    """What the text-evidence pipeline would have produced, faked from HiddenTruth."""
    E_text: float
    T_text: float
    M_text: float
    c_text: float
    n: int

    def as_dict(self) -> Dict[str, float]:
        return {
            "E_text": self.E_text,
            "T_text": self.T_text,
            "M_text": self.M_text,
            "c_text": self.c_text,
            "n": float(self.n),
        }


@dataclass
class StepResult:
    """Single PPO environment step output."""
    observation: List[float]
    reward: float
    done: bool
    info: Dict[str, float] = field(default_factory=dict)
