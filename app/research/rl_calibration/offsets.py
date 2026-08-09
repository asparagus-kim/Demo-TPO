"""Offset-based parameterization of ambience priors.

Design rule (chosen at project spec time):
    Action-space encoding is **Option A: learn offsets, not raw tables**.

The neutral base is the *current production prior set* from
`app.services.ambience_service`. Offsets are added per-axis (E, T, M) on top
of those neutral bases, and the *effective* prior tables used by the fusion
math are `clip(base + offset, 0, 1)`.

This keeps the search space well-conditioned:
    - zero-offsets ≡ current production behavior,
    - small offsets ≡ small, explainable deviations,
    - the RL agent never needs to rediscover the baseline from scratch.

Vector layout (for PPO's fixed-size action / observation):
    [base(3) | trade(8*3) | type(8*3) | daypart(5*3) | weather(6*3) |
     default_trade(3) | default_type(3) | window_shifts(5)]

That is 3 + 24 + 24 + 15 + 18 + 3 + 3 + 5 = 95 scalars.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from ...services import ambience_service as _amb


# ------------------------------------------------------------------- keys
TRADE_KEYS: List[str] = list(_amb.TRADE_AREA_PRIORS.keys())
TYPE_KEYS: List[str] = list(_amb.BUSINESS_TYPE_PRIORS.keys())
DAYPART_KEYS: List[str] = [name for name, _, _ in _amb.DAYPART_WINDOWS]
WEATHER_KEYS: List[str] = list(_amb.WEATHER_PRIORS.keys())
AXES: Tuple[str, str, str] = ("E", "T", "M")

# Daypart window edges we're willing to shift (keep the set small & named):
WINDOW_SHIFT_KEYS: List[str] = [
    "early_morning_end",
    "lunch_start",
    "lunch_end",
    "dinner_start",
    "late_night_start",
]


def _neutral_base() -> Dict[str, float]:
    """Central base = arithmetic mean of the production DEFAULT_TRADE/DEFAULT_TYPE."""
    out: Dict[str, float] = {}
    for a in AXES:
        out[a] = 0.5 * (_amb.DEFAULT_TRADE[a] + _amb.DEFAULT_TYPE[a])
    return out


# ------------------------------------------------------------------- container
@dataclass
class OffsetParams:
    """Container that the RL agent manipulates. All offsets default to zero.

    `base` is a *small* global shift — think of it as recalibrating the neutral
    midpoint. All other offsets are added to the production prior entries.
    """
    base: Dict[str, float] = field(default_factory=lambda: {a: 0.0 for a in AXES})
    trade_offsets: Dict[str, Dict[str, float]] = field(default_factory=dict)
    business_type_offsets: Dict[str, Dict[str, float]] = field(default_factory=dict)
    daypart_offsets: Dict[str, Dict[str, float]] = field(default_factory=dict)
    weather_offsets: Dict[str, Dict[str, float]] = field(default_factory=dict)
    default_trade_offsets: Dict[str, float] = field(default_factory=lambda: {a: 0.0 for a in AXES})
    default_type_offsets: Dict[str, float] = field(default_factory=lambda: {a: 0.0 for a in AXES})
    daypart_window_shifts: Dict[str, float] = field(default_factory=lambda: {k: 0.0 for k in WINDOW_SHIFT_KEYS})

    def clone(self) -> "OffsetParams":
        return OffsetParams(
            base={**self.base},
            trade_offsets={k: {**v} for k, v in self.trade_offsets.items()},
            business_type_offsets={k: {**v} for k, v in self.business_type_offsets.items()},
            daypart_offsets={k: {**v} for k, v in self.daypart_offsets.items()},
            weather_offsets={k: {**v} for k, v in self.weather_offsets.items()},
            default_trade_offsets={**self.default_trade_offsets},
            default_type_offsets={**self.default_type_offsets},
            daypart_window_shifts={**self.daypart_window_shifts},
        )

    def total_magnitude(self) -> float:
        """L1 sum over every offset scalar — used by the anti-extremeness reward."""
        mag = sum(abs(v) for v in self.base.values())
        for d in (self.trade_offsets, self.business_type_offsets,
                  self.daypart_offsets, self.weather_offsets):
            for axis_map in d.values():
                mag += sum(abs(v) for v in axis_map.values())
        mag += sum(abs(v) for v in self.default_trade_offsets.values())
        mag += sum(abs(v) for v in self.default_type_offsets.values())
        mag += sum(abs(v) for v in self.daypart_window_shifts.values())
        return mag


def build_default_params() -> OffsetParams:
    """Return an OffsetParams with zero offsets at every key the agent may touch."""
    p = OffsetParams()
    for k in TRADE_KEYS:
        p.trade_offsets[k] = {a: 0.0 for a in AXES}
    for k in TYPE_KEYS:
        p.business_type_offsets[k] = {a: 0.0 for a in AXES}
    for k in DAYPART_KEYS:
        p.daypart_offsets[k] = {a: 0.0 for a in AXES}
    for k in WEATHER_KEYS:
        p.weather_offsets[k] = {a: 0.0 for a in AXES}
    # base already [0,0,0], defaults already zero, window shifts already zero
    return p


# ------------------------------------------------------------------- apply
def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def apply_offsets(params: OffsetParams) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Compose offsets onto the production priors to get *effective* tables.

    Returns a dict keyed by table name:
        {"trade": {...}, "type": {...}, "daypart": {...}, "weather": {...},
         "default_trade": {...}, "default_type": {...}, "base": {...}}

    The `base` contribution is applied uniformly to every trade/type prior
    (so a positive base["E"] raises the baseline energy across all areas).
    """
    eff: Dict[str, Dict[str, Dict[str, float]]] = {
        "trade": {},
        "type": {},
        "daypart": {},
        "weather": {},
    }

    for key, prior in _amb.TRADE_AREA_PRIORS.items():
        off = params.trade_offsets.get(key, {a: 0.0 for a in AXES})
        eff["trade"][key] = {
            a: _clip01(prior[a] + params.base.get(a, 0.0) + off.get(a, 0.0))
            for a in AXES
        }
    for key, prior in _amb.BUSINESS_TYPE_PRIORS.items():
        off = params.business_type_offsets.get(key, {a: 0.0 for a in AXES})
        eff["type"][key] = {
            a: _clip01(prior[a] + params.base.get(a, 0.0) + off.get(a, 0.0))
            for a in AXES
        }
    for key, prior in _amb.DAYPART_PRIORS.items():
        off = params.daypart_offsets.get(key, {a: 0.0 for a in AXES})
        eff["daypart"][key] = {a: _clip01(prior[a] + off.get(a, 0.0)) for a in AXES}
    for key, prior in _amb.WEATHER_PRIORS.items():
        off = params.weather_offsets.get(key, {a: 0.0 for a in AXES})
        eff["weather"][key] = {a: _clip01(prior[a] + off.get(a, 0.0)) for a in AXES}

    eff["default_trade"] = {
        a: _clip01(_amb.DEFAULT_TRADE[a] + params.base.get(a, 0.0)
                   + params.default_trade_offsets.get(a, 0.0))
        for a in AXES
    }
    eff["default_type"] = {
        a: _clip01(_amb.DEFAULT_TYPE[a] + params.base.get(a, 0.0)
                   + params.default_type_offsets.get(a, 0.0))
        for a in AXES
    }
    eff["base"] = {a: params.base.get(a, 0.0) for a in AXES}
    return eff


def effective_priors_from_params(params: OffsetParams):
    """Alias returning (trade, type, daypart, weather, default_trade, default_type).

    Used by `environment.CalibrationEnv` to feed a *copy* of ambience_service
    with RL-learned priors without mutating the production module globals.
    """
    eff = apply_offsets(params)
    return (
        eff["trade"], eff["type"], eff["daypart"], eff["weather"],
        eff["default_trade"], eff["default_type"],
    )


def effective_daypart_windows(params: OffsetParams) -> List[Tuple[str, int, int]]:
    """Return a shifted copy of DAYPART_WINDOWS according to learned window shifts.

    The shifts are clipped so that each daypart retains a positive width of at
    least 1 hour and boundaries stay monotone. (The learned values come in as
    real-valued hours; we round to the nearest int because the production
    `compute_daypart_weights` is integer-hour-based.)
    """
    s = params.daypart_window_shifts
    em_end = int(round(10 + s.get("early_morning_end", 0.0)))
    lu_start = int(round(11 + s.get("lunch_start", 0.0)))
    lu_end = int(round(14 + s.get("lunch_end", 0.0)))
    di_start = int(round(17 + s.get("dinner_start", 0.0)))
    ln_start = int(round(21 + s.get("late_night_start", 0.0)))

    # Enforce monotone, >=1-hour windows: early_morning < lunch < afternoon < dinner < late_night
    em_end = max(7, min(em_end, 11))
    lu_start = max(em_end, min(lu_start, 13))
    lu_end = max(lu_start + 1, min(lu_end, 16))
    di_start = max(lu_end, min(di_start, 20))
    ln_start = max(di_start + 1, min(ln_start, 23))

    return [
        ("early_morning", 6, em_end),
        ("lunch", lu_start, lu_end),
        ("afternoon", lu_end, di_start),
        ("dinner", di_start, ln_start),
        ("late_night", ln_start, ln_start + 5),  # preserve original 5-hour late span
    ]


# ------------------------------------------------------------------- flat vector
#
# Fixed, canonical ordering so PPO's action_head output and observation_head
# input both see the same indices. Keep this in sync with OFFSET_VECTOR_DIM.

def _flat_order() -> List[Tuple[str, Tuple]]:
    """Produces [(kind, key_tuple), ...] in canonical order."""
    order: List[Tuple[str, Tuple]] = []
    for a in AXES:
        order.append(("base", (a,)))
    for k in TRADE_KEYS:
        for a in AXES:
            order.append(("trade", (k, a)))
    for k in TYPE_KEYS:
        for a in AXES:
            order.append(("type", (k, a)))
    for k in DAYPART_KEYS:
        for a in AXES:
            order.append(("daypart", (k, a)))
    for k in WEATHER_KEYS:
        for a in AXES:
            order.append(("weather", (k, a)))
    for a in AXES:
        order.append(("default_trade", (a,)))
    for a in AXES:
        order.append(("default_type", (a,)))
    for k in WINDOW_SHIFT_KEYS:
        order.append(("window_shift", (k,)))
    return order


_FLAT_ORDER: List[Tuple[str, Tuple]] = _flat_order()
OFFSET_VECTOR_DIM: int = len(_FLAT_ORDER)


def offsets_to_flat_vector(params: OffsetParams) -> List[float]:
    """Serialize every scalar offset into a fixed-length list."""
    out: List[float] = []
    for kind, keys in _FLAT_ORDER:
        if kind == "base":
            (a,) = keys
            out.append(params.base.get(a, 0.0))
        elif kind == "trade":
            k, a = keys
            out.append(params.trade_offsets.get(k, {}).get(a, 0.0))
        elif kind == "type":
            k, a = keys
            out.append(params.business_type_offsets.get(k, {}).get(a, 0.0))
        elif kind == "daypart":
            k, a = keys
            out.append(params.daypart_offsets.get(k, {}).get(a, 0.0))
        elif kind == "weather":
            k, a = keys
            out.append(params.weather_offsets.get(k, {}).get(a, 0.0))
        elif kind == "default_trade":
            (a,) = keys
            out.append(params.default_trade_offsets.get(a, 0.0))
        elif kind == "default_type":
            (a,) = keys
            out.append(params.default_type_offsets.get(a, 0.0))
        elif kind == "window_shift":
            (k,) = keys
            out.append(params.daypart_window_shifts.get(k, 0.0))
    return out


def flat_vector_to_offsets(vec: Iterable[float]) -> OffsetParams:
    """Inverse of offsets_to_flat_vector — rebuilds a fresh OffsetParams."""
    vec = list(vec)
    if len(vec) != OFFSET_VECTOR_DIM:
        raise ValueError(f"expected length {OFFSET_VECTOR_DIM}, got {len(vec)}")
    p = build_default_params()
    for i, (kind, keys) in enumerate(_FLAT_ORDER):
        v = float(vec[i])
        if kind == "base":
            (a,) = keys
            p.base[a] = v
        elif kind == "trade":
            k, a = keys
            p.trade_offsets.setdefault(k, {a2: 0.0 for a2 in AXES})[a] = v
        elif kind == "type":
            k, a = keys
            p.business_type_offsets.setdefault(k, {a2: 0.0 for a2 in AXES})[a] = v
        elif kind == "daypart":
            k, a = keys
            p.daypart_offsets.setdefault(k, {a2: 0.0 for a2 in AXES})[a] = v
        elif kind == "weather":
            k, a = keys
            p.weather_offsets.setdefault(k, {a2: 0.0 for a2 in AXES})[a] = v
        elif kind == "default_trade":
            (a,) = keys
            p.default_trade_offsets[a] = v
        elif kind == "default_type":
            (a,) = keys
            p.default_type_offsets[a] = v
        elif kind == "window_shift":
            (k,) = keys
            p.daypart_window_shifts[k] = v
    return p


def flat_vector_layout() -> List[Tuple[str, Tuple]]:
    """Expose the canonical index layout for UI / debugging."""
    return list(_FLAT_ORDER)


# ------------------------------------------------------------------- bounds
def flat_bounds(
    base_bound: float,
    trade_bound: float,
    type_bound: float,
    daypart_bound: float,
    weather_bound: float,
    default_bound: float,
    window_shift_bound: float,
) -> List[float]:
    """Per-index magnitude bound — same shape as the flat vector."""
    bounds: List[float] = []
    for kind, _keys in _FLAT_ORDER:
        if kind == "base":
            bounds.append(base_bound)
        elif kind == "trade":
            bounds.append(trade_bound)
        elif kind == "type":
            bounds.append(type_bound)
        elif kind == "daypart":
            bounds.append(daypart_bound)
        elif kind == "weather":
            bounds.append(weather_bound)
        elif kind == "default_trade":
            bounds.append(default_bound)
        elif kind == "default_type":
            bounds.append(default_bound)
        elif kind == "window_shift":
            bounds.append(window_shift_bound)
    return bounds
