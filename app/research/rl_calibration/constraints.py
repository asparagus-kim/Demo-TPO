"""Semantic constraint checks on effective priors.

These are qualitative relationships that must hold regardless of what the
ground-truth world looks like — they encode product knowledge ("a takeaway
café must have higher tempo than a dessert shop"). Violations subtract from
the PPO reward and are logged in evaluation reports.

Each constraint returns a violation score in [0,1] where 0 = satisfied and
larger = worse. The aggregate constraint *loss* is the mean of those scores.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple


Table = Dict[str, Dict[str, float]]
ConstraintFn = Callable[[Dict[str, Table]], float]


@dataclass
class Constraint:
    name: str
    description: str
    check: ConstraintFn


def _hinge(lhs: float, rhs: float, margin: float = 0.02) -> float:
    """Soft hinge: 0 when lhs >= rhs + margin, grows linearly otherwise.

    We use `margin` so that constraints bind *strictly* rather than just
    loosely matching ties. Clamped to [0,1].
    """
    gap = (rhs + margin) - lhs
    if gap <= 0.0:
        return 0.0
    return min(1.0, gap / max(margin, 1e-6))


def _trade(eff: Dict[str, Table], key: str, axis: str) -> float:
    return eff["trade"][key][axis]


def _type(eff: Dict[str, Table], key: str, axis: str) -> float:
    return eff["type"][key][axis]


def _daypart(eff: Dict[str, Table], key: str, axis: str) -> float:
    return eff["daypart"][key][axis]


def _weather(eff: Dict[str, Table], key: str, axis: str) -> float:
    return eff["weather"][key][axis]


# ------------------------------------------------------------------- rules
def _office_tempo_over_residential(eff):
    # Office trades should be higher-tempo than residential.
    return _hinge(_trade(eff, "오피스 밀집 상권", "T"),
                  _trade(eff, "주거 밀집 상권", "T"))


def _nightlife_energy_over_residential(eff):
    return _hinge(_trade(eff, "대학가/유흥 상권", "E"),
                  _trade(eff, "주거 밀집 상권", "E"))


def _residential_mood_over_office(eff):
    # Residential trades should feel cozier (higher mood) than office trades.
    return _hinge(_trade(eff, "주거 밀집 상권", "M"),
                  _trade(eff, "오피스 밀집 상권", "M"))


def _takeaway_tempo_over_cafe(eff):
    return _hinge(_type(eff, "테이크아웃 카페", "T"),
                  _type(eff, "카페", "T"))


def _bar_energy_over_dessert(eff):
    return _hinge(_type(eff, "주점/바", "E"),
                  _type(eff, "디저트숍", "E"))


def _dessert_mood_over_fastfood(eff):
    return _hinge(_type(eff, "디저트숍", "M"),
                  _type(eff, "패스트푸드", "M"))


def _fastfood_tempo_over_bakery(eff):
    return _hinge(_type(eff, "패스트푸드", "T"),
                  _type(eff, "베이커리 카페", "T"))


def _lunch_tempo_over_afternoon(eff):
    return _hinge(_daypart(eff, "lunch", "T"),
                  _daypart(eff, "afternoon", "T"))


def _latenight_energy_over_morning(eff):
    return _hinge(_daypart(eff, "late_night", "E"),
                  _daypart(eff, "early_morning", "E"))


def _afternoon_mood_over_lunch(eff):
    # Relaxed afternoons feel cozier than the lunch-rush hour.
    return _hinge(_daypart(eff, "afternoon", "M"),
                  _daypart(eff, "lunch", "M"))


def _sunny_mood_over_rainy(eff):
    return _hinge(_weather(eff, "sunny", "M"),
                  _weather(eff, "rainy", "M"))


def _rainy_tempo_under_sunny(eff):
    # Rainy weather slows everyone down → tempo should be lower than sunny.
    return _hinge(_weather(eff, "sunny", "T"),
                  _weather(eff, "rainy", "T"))


CONSTRAINTS: List[Constraint] = [
    Constraint("office_tempo>residential_tempo",
               "Office trades should outpace residential areas on tempo.",
               _office_tempo_over_residential),
    Constraint("nightlife_energy>residential_energy",
               "Nightlife districts should be more energetic than residential.",
               _nightlife_energy_over_residential),
    Constraint("residential_mood>office_mood",
               "Residential areas should feel warmer than pure office areas.",
               _residential_mood_over_office),
    Constraint("takeaway_tempo>cafe_tempo",
               "Takeaway cafés must rank higher on tempo than sit-down cafés.",
               _takeaway_tempo_over_cafe),
    Constraint("bar_energy>dessert_energy",
               "Bars must rank higher on energy than dessert shops.",
               _bar_energy_over_dessert),
    Constraint("dessert_mood>fastfood_mood",
               "Dessert shops must rank higher on mood than fast-food.",
               _dessert_mood_over_fastfood),
    Constraint("fastfood_tempo>bakery_tempo",
               "Fast-food must rank higher on tempo than a bakery café.",
               _fastfood_tempo_over_bakery),
    Constraint("lunch_tempo>afternoon_tempo",
               "Lunch daypart should outpace afternoon on tempo.",
               _lunch_tempo_over_afternoon),
    Constraint("late_night_energy>early_morning_energy",
               "Late-night daypart should out-energize early morning.",
               _latenight_energy_over_morning),
    Constraint("afternoon_mood>lunch_mood",
               "Afternoon should feel cozier than the lunch rush.",
               _afternoon_mood_over_lunch),
    Constraint("sunny_mood>rainy_mood",
               "Sunny weather should feel better than rainy weather on mood.",
               _sunny_mood_over_rainy),
    Constraint("sunny_tempo>rainy_tempo",
               "Rainy weather slows tempo relative to sunny.",
               _rainy_tempo_under_sunny),
]


def evaluate_constraints(effective: Dict[str, Table]) -> Tuple[float, Dict[str, float]]:
    """Return `(mean_violation, per_constraint_violations)`.

    A return value of `0` for `mean_violation` means every constraint holds.
    """
    per: Dict[str, float] = {}
    for c in CONSTRAINTS:
        try:
            per[c.name] = float(c.check(effective))
        except KeyError:
            # If a required key is missing (e.g. custom effective table), skip.
            per[c.name] = 0.0
    if not per:
        return 0.0, per
    mean_v = sum(per.values()) / len(per)
    return mean_v, per


def num_constraints() -> int:
    return len(CONSTRAINTS)
