"""Human-inspectable dump of the synthetic data fed into PPO.

Generates N records by calling the three synthetic generators and writes
them to disk in three complementary formats so the operator can open
whichever suits their workflow:

    outputs/rl_calibration/synthetic_samples/
        <name>_synthetic_samples.json   full fidelity, UTF-8
        <name>_synthetic_samples.csv    flat per-row view for spreadsheets
        <name>_synthetic_samples.md     readable preview with distribution table

Each record is the round-trip of one scenario through:

    1.  scenario_generator.generate_batch(n, rng)
                  -> Scenario(trade_area, business_type, business_hours,
                              weather, hour_of_day, review_count, seed)
    2.  synthetic_world.hidden_truth(scenario, noisy=...)
                  -> HiddenTruth(energy, tempo, mood)
        (both noisy and clean variants captured; the env uses noisy)
    3.  text_simulator.simulate_text_evidence(scenario, truth, rng)
                  -> SimulatedText(E_text, T_text, M_text, c_text, n)

Nothing in this module is on the PPO training hot path — it runs once,
up front, purely for inspection.
"""
from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .config import OUTPUT_ROOT
from .scenario_generator import generate_batch
from .synthetic_world import hidden_truth
from .text_simulator import simulate_text_evidence
from .types import HiddenTruth, Scenario, SimulatedText


SAMPLES_DIR: Path = OUTPUT_ROOT / "synthetic_samples"


def _active_daypart(hour_of_day: int) -> str:
    """Return the production daypart label for a given hour — mirrors `synthetic_world._active_daypart`."""
    if 6 <= hour_of_day < 10:
        return "early_morning"
    if 10 <= hour_of_day < 14:
        return "lunch"
    if 14 <= hour_of_day < 17:
        return "afternoon"
    if 17 <= hour_of_day < 21:
        return "dinner"
    return "late_night"


def _scenario_to_dict(s: Scenario) -> Dict[str, Any]:
    return {
        "trade_area": s.trade_area,
        "business_type": s.business_type,
        "business_hours": [list(h) for h in s.business_hours],
        "weather": s.weather,
        "hour_of_day": s.hour_of_day,
        "review_count": s.review_count,
        "seed": s.seed,
    }


def _hours_string(s: Scenario) -> str:
    return ";".join(f"{a:02d}-{b:02d}" for a, b in s.business_hours) or "none"


def _count_by(items: List[Any], key) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items:
        k = key(it)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def dump_synthetic_samples(
    *,
    name: str,
    n: int = 128,
    seed: int = 20260423,
    verbose: bool = True,
) -> Dict[str, Path]:
    """Generate `n` synthetic samples and persist them for visual inspection.

    Writes three files into `outputs/rl_calibration/synthetic_samples/`
    and returns their paths as a dict with keys ``{"json", "csv", "md"}``.

    The JSON is the authoritative record (full fields, no rounding). The
    CSV mirrors the same rows flattened for spreadsheet viewing. The MD
    is a quick-scan preview showing the first 20 rows plus distribution
    counts over trade area, business type, weather, and daypart.
    """
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    # 1. Generate scenarios, both truth variants, and the simulated text.
    scenarios: List[Scenario] = generate_batch(n, rng)
    truths_noisy: List[HiddenTruth] = [hidden_truth(s, noisy=True) for s in scenarios]
    truths_clean: List[HiddenTruth] = [hidden_truth(s, noisy=False) for s in scenarios]
    texts: List[SimulatedText] = [
        simulate_text_evidence(s, t, rng=rng)
        for s, t in zip(scenarios, truths_noisy)
    ]

    # 2. Distribution summary — great for a one-glance sanity check.
    summary: Dict[str, Dict[str, int]] = {
        "trade_area_counts": _count_by(scenarios, lambda s: s.trade_area),
        "business_type_counts": _count_by(scenarios, lambda s: s.business_type),
        "weather_counts": _count_by(scenarios, lambda s: s.weather),
        "daypart_counts": _count_by(scenarios, lambda s: _active_daypart(s.hour_of_day)),
    }

    # 3. Per-sample records.
    records: List[Dict[str, Any]] = []
    for i, (s, tn, tc, x) in enumerate(zip(scenarios, truths_noisy, truths_clean, texts)):
        records.append({
            "index": i,
            "scenario": _scenario_to_dict(s),
            "active_daypart": _active_daypart(s.hour_of_day),
            "hidden_truth_clean": tc.as_dict(),
            "hidden_truth_noisy": tn.as_dict(),
            "simulated_text": x.as_dict(),
        })

    generated_at = datetime.now(timezone.utc).isoformat()

    # 4. JSON — full fidelity, UTF-8 so Korean keys round-trip.
    json_path = SAMPLES_DIR / f"{name}_synthetic_samples.json"
    payload: Dict[str, Any] = {
        "metadata": {
            "name": name,
            "seed": seed,
            "n_samples": n,
            "generated_at": generated_at,
            "field_notes": {
                "scenario": "inputs to fuse_with_params() — same shape the production "
                            "request pipeline would see for one shop.",
                "hidden_truth_clean": "noiseless generative target per scenario (useful "
                                      "for debugging the fit quality vs pure mean).",
                "hidden_truth_noisy": "the noisy per-sample target actually used inside "
                                      "the reward MSE during PPO training.",
                "simulated_text": "the observation PPO sees via the env — matches the "
                                  "shape of app.services.llm_service.aggregate_text_scores.",
                "active_daypart": "resolved daypart bucket for scenario.hour_of_day — "
                                  "decides which row of _TRUE_DAYPART is consulted.",
            },
        },
        "summary": summary,
        "samples": records,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 5. CSV — one row per sample, flattened.
    csv_path = SAMPLES_DIR / f"{name}_synthetic_samples.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "index", "trade_area", "business_type", "business_hours",
            "weather", "hour_of_day", "active_daypart", "review_count",
            "scenario_seed",
            "truth_clean_E", "truth_clean_T", "truth_clean_M",
            "truth_noisy_E", "truth_noisy_T", "truth_noisy_M",
            "text_E", "text_T", "text_M", "text_c", "text_n",
        ])
        for rec, s, tn, tc, x in zip(records, scenarios, truths_noisy,
                                     truths_clean, texts):
            w.writerow([
                rec["index"],
                s.trade_area, s.business_type, _hours_string(s),
                s.weather, s.hour_of_day, rec["active_daypart"],
                s.review_count, s.seed,
                f"{tc.energy:.4f}", f"{tc.tempo:.4f}", f"{tc.mood:.4f}",
                f"{tn.energy:.4f}", f"{tn.tempo:.4f}", f"{tn.mood:.4f}",
                f"{x.E_text:.4f}", f"{x.T_text:.4f}", f"{x.M_text:.4f}",
                f"{x.c_text:.4f}", x.n,
            ])

    # 6. Markdown preview — readable without any tooling.
    md_path = SAMPLES_DIR / f"{name}_synthetic_samples.md"
    md: List[str] = []
    md.append(f"# Synthetic samples — `{name}`")
    md.append("")
    md.append(
        f"_Generated {generated_at} with seed {seed}; {n} samples total._"
    )
    md.append("")
    md.append("## Pipeline per sample")
    md.append("")
    md.append(
        "1. `scenario_generator.generate_batch(n, rng)` → "
        "`Scenario(trade_area, business_type, business_hours, weather, hour_of_day, review_count, seed)`"
    )
    md.append(
        "2. `synthetic_world.hidden_truth(scenario, noisy=True|False)` → "
        "`HiddenTruth(energy, tempo, mood)` — both variants captured below."
    )
    md.append(
        "3. `text_simulator.simulate_text_evidence(scenario, truth, rng)` → "
        "`SimulatedText(E_text, T_text, M_text, c_text, n)`"
    )
    md.append("")

    md.append("## Distribution summary")
    md.append("")
    for title, counts in (
        ("Trade area", summary["trade_area_counts"]),
        ("Business type", summary["business_type_counts"]),
        ("Weather", summary["weather_counts"]),
        ("Active daypart", summary["daypart_counts"]),
    ):
        md.append(f"### {title}")
        md.append("")
        md.append("| key | count |")
        md.append("| --- | ---: |")
        for k, c in counts.items():
            md.append(f"| {k} | {c} |")
        md.append("")

    preview_n = min(20, n)
    md.append(f"## Preview — first {preview_n} samples")
    md.append("")
    md.append(
        "Truth columns are shown as `E/T/M`. Text column is `E/T/M/c`. "
        "See the CSV and JSON for all `{n}` samples.".replace("{n}", str(n))
    )
    md.append("")
    md.append(
        "| # | trade_area | business_type | hours | wx | hr | daypart | n_rev | "
        "truth_clean (E/T/M) | truth_noisy (E/T/M) | text (E/T/M/c) |"
    )
    md.append(
        "| ---: | --- | --- | --- | --- | ---: | --- | ---: | --- | --- | --- |"
    )
    for rec, s, tn, tc, x in zip(records[:preview_n], scenarios[:preview_n],
                                 truths_noisy[:preview_n], truths_clean[:preview_n],
                                 texts[:preview_n]):
        clean_str = f"{tc.energy:.2f}/{tc.tempo:.2f}/{tc.mood:.2f}"
        noisy_str = f"{tn.energy:.2f}/{tn.tempo:.2f}/{tn.mood:.2f}"
        text_str = f"{x.E_text:.2f}/{x.T_text:.2f}/{x.M_text:.2f}/{x.c_text:.2f}"
        md.append(
            f"| {rec['index']} | {s.trade_area} | {s.business_type} | "
            f"{_hours_string(s)} | {s.weather} | {s.hour_of_day} | "
            f"{rec['active_daypart']} | {s.review_count} | "
            f"{clean_str} | {noisy_str} | {text_str} |"
        )
    md.append("")
    md.append(
        f"Full data: `{json_path.name}` (JSON) and `{csv_path.name}` (CSV) in this folder."
    )
    md.append("")
    md_path.write_text("\n".join(md), encoding="utf-8")

    if verbose:
        try:
            print(f"[synthetic-dump] wrote {n} samples to {SAMPLES_DIR}")
            print(f"    JSON : {json_path}")
            print(f"    CSV  : {csv_path}")
            print(f"    MD   : {md_path}")
        except UnicodeEncodeError:
            # CP949 consoles can choke on some characters; degrade cleanly.
            pass

    return {"json": json_path, "csv": csv_path, "md": md_path}
