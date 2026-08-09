"""Export learned OffsetParams → JSON under `outputs/rl_calibration/learned_params/`.

The exported file is the *source of truth* for downstream promotion. It is
NOT automatically applied to the production `ambience_service` — a human
operator reviews the diff (see `load_for_production_preview()`), and if
approved, copies the effective table values into `ambience_service.py` via
a PR. This keeps RL out of the request path by default.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ...services import ambience_service as _amb
from .config import LEARNED_PARAMS_DIR, ensure_output_dirs
from .offsets import (
    OffsetParams,
    apply_offsets,
    build_default_params,
    flat_vector_layout,
    offsets_to_flat_vector,
)


SCHEMA_VERSION = "1.0.0"


def params_to_dict(params: OffsetParams) -> Dict[str, Any]:
    """Serialize an OffsetParams to a plain nested dict."""
    return {
        "base": dict(params.base),
        "trade_offsets": {k: dict(v) for k, v in params.trade_offsets.items()},
        "business_type_offsets": {k: dict(v) for k, v in params.business_type_offsets.items()},
        "daypart_offsets": {k: dict(v) for k, v in params.daypart_offsets.items()},
        "weather_offsets": {k: dict(v) for k, v in params.weather_offsets.items()},
        "default_trade_offsets": dict(params.default_trade_offsets),
        "default_type_offsets": dict(params.default_type_offsets),
        "daypart_window_shifts": dict(params.daypart_window_shifts),
    }


def params_from_dict(d: Dict[str, Any]) -> OffsetParams:
    p = build_default_params()
    if "base" in d: p.base.update(d["base"])
    if "trade_offsets" in d:
        for k, v in d["trade_offsets"].items():
            p.trade_offsets.setdefault(k, {}).update(v)
    if "business_type_offsets" in d:
        for k, v in d["business_type_offsets"].items():
            p.business_type_offsets.setdefault(k, {}).update(v)
    if "daypart_offsets" in d:
        for k, v in d["daypart_offsets"].items():
            p.daypart_offsets.setdefault(k, {}).update(v)
    if "weather_offsets" in d:
        for k, v in d["weather_offsets"].items():
            p.weather_offsets.setdefault(k, {}).update(v)
    if "default_trade_offsets" in d:
        p.default_trade_offsets.update(d["default_trade_offsets"])
    if "default_type_offsets" in d:
        p.default_type_offsets.update(d["default_type_offsets"])
    if "daypart_window_shifts" in d:
        p.daypart_window_shifts.update(d["daypart_window_shifts"])
    return p


def export(
    params: OffsetParams,
    *,
    name: str = "learned_offsets",
    metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write `{name}.json` under LEARNED_PARAMS_DIR.

    The file captures both offsets and the *effective* prior tables so that a
    reviewer can see "what would the priors look like if we promote this?"
    without running any code.
    """
    ensure_output_dirs()
    effective = apply_offsets(params)
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "offsets": params_to_dict(params),
        "effective": effective,
        "production_baseline": {
            "trade": {k: dict(v) for k, v in _amb.TRADE_AREA_PRIORS.items()},
            "type": {k: dict(v) for k, v in _amb.BUSINESS_TYPE_PRIORS.items()},
            "daypart": {k: dict(v) for k, v in _amb.DAYPART_PRIORS.items()},
            "weather": {k: dict(v) for k, v in _amb.WEATHER_PRIORS.items()},
            "default_trade": dict(_amb.DEFAULT_TRADE),
            "default_type": dict(_amb.DEFAULT_TYPE),
        },
        "flat_vector": offsets_to_flat_vector(params),
        "flat_layout": [
            {"kind": kind, "keys": list(keys)}
            for kind, keys in flat_vector_layout()
        ],
        "metadata": metadata or {},
    }
    path = LEARNED_PARAMS_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load(path: Path) -> OffsetParams:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return params_from_dict(data["offsets"])


def diff_summary(params: OffsetParams) -> Dict[str, Any]:
    """Return a human-readable diff between effective tables and baseline.

    Only lists entries where the absolute delta > 0.01 so reviewers aren't
    drowned in near-zero offsets.
    """
    eff = apply_offsets(params)
    out: Dict[str, Any] = {"trade": {}, "type": {}, "daypart": {}, "weather": {}}
    for k, v in eff["trade"].items():
        base = _amb.TRADE_AREA_PRIORS.get(k, {})
        deltas = {a: round(v[a] - base[a], 3) for a in ("E", "T", "M") if a in base}
        if any(abs(x) > 0.01 for x in deltas.values()):
            out["trade"][k] = deltas
    for k, v in eff["type"].items():
        base = _amb.BUSINESS_TYPE_PRIORS.get(k, {})
        deltas = {a: round(v[a] - base[a], 3) for a in ("E", "T", "M") if a in base}
        if any(abs(x) > 0.01 for x in deltas.values()):
            out["type"][k] = deltas
    for k, v in eff["daypart"].items():
        base = _amb.DAYPART_PRIORS.get(k, {})
        deltas = {a: round(v[a] - base[a], 3) for a in ("E", "T", "M") if a in base}
        if any(abs(x) > 0.01 for x in deltas.values()):
            out["daypart"][k] = deltas
    for k, v in eff["weather"].items():
        base = _amb.WEATHER_PRIORS.get(k, {})
        deltas = {a: round(v[a] - base[a], 3) for a in ("E", "T", "M") if a in base}
        if any(abs(x) > 0.01 for x in deltas.values()):
            out["weather"][k] = deltas
    return out
