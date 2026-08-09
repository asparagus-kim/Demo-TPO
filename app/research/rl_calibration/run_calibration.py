"""End-to-end RL calibration pipeline + Markdown decision report.

Runs steps 1-4 in one go:
    1. PPO training
    2. Greedy rollout of the trained policy
    3. Evaluation (MSE, constraints, stability)
    4. Baseline sanity checks (random search, hill-climb)

On top of the raw exports, this script writes a single human-readable Markdown
report under ``outputs/rl_calibration/reports/<name>.md`` containing:
    - the training curves (PNG),
    - a summary-statistics table comparing learned vs production baseline,
    - per-constraint violation breakdown,
    - a prioritized diff of prior-table entries that would change if the
      learned offsets were promoted,
    - a baseline sanity-check table,
    - a textual recommendation ("PROMOTE" / "INSPECT" / "REJECT") with the
      numeric rationale behind it.

Usage:
    python -m app.research.rl_calibration.run_calibration --name ambience_v1
    python -m app.research.rl_calibration.run_calibration --name short_run \\
        --updates 5 --rollout-steps 128 --baseline-iters 100

The `.md` file is the primary artifact the operator reads before deciding to
run `apply_to_production.py`.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .baseline_search import hillclimb, random_search
from .config import (
    CHECKPOINT_DIR,
    EnvConfig,
    LEARNED_PARAMS_DIR,
    PPOConfig,
    REPORT_DIR,
    RewardWeights,
    ensure_output_dirs,
)
from .environment import CalibrationEnv
from .evaluate import evaluate_params, rollout_policy, write_report
from .export_params import diff_summary, export
from .offsets import OffsetParams, build_default_params
from .ppo_train import PPOTrainer, train as ppo_train
from .synthetic_dump import dump_synthetic_samples


def _safe_print(msg: str) -> None:
    """Print to stdout, degrading gracefully on non-UTF-8 consoles (e.g. CP949)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(__import__("sys").stdout, "encoding", "ascii") or "ascii"
        print(msg.encode(enc, errors="replace").decode(enc, errors="replace"))


# --------------------------------------------------------------- plots (optional)
def _plot_training_curves(history: List[Dict[str, Any]], out_png: Path) -> bool:
    """Render training curves. Returns True if the PNG was written."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless backend — safe in CI / servers
        import matplotlib.pyplot as plt
    except Exception:
        return False
    if not history:
        return False

    updates = [h["update"] for h in history]
    fig, axes = plt.subplots(2, 2, figsize=(10, 6))
    axes = axes.flatten()

    axes[0].plot(updates, [h["avg_reward"] for h in history], marker="o")
    axes[0].set_title("Average reward")
    axes[0].set_xlabel("update"); axes[0].set_ylabel("reward")
    axes[0].grid(alpha=0.3)

    axes[1].plot(updates, [h["policy_loss"] for h in history], label="policy", marker="o")
    axes[1].plot(updates, [h["value_loss"] for h in history], label="value", marker="s")
    axes[1].set_title("Losses")
    axes[1].set_xlabel("update"); axes[1].legend(); axes[1].grid(alpha=0.3)

    axes[2].plot(updates, [h["entropy"] for h in history], marker="o", color="tab:green")
    axes[2].set_title("Policy entropy")
    axes[2].set_xlabel("update"); axes[2].grid(alpha=0.3)

    axes[3].plot(updates, [h["kl"] for h in history], marker="o", color="tab:red")
    axes[3].set_title("Approx KL")
    axes[3].set_xlabel("update"); axes[3].grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_png, dpi=120)
    plt.close(fig)
    return True


def _plot_mse_bars(learned: Dict[str, float], reference: Dict[str, float], out_png: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False
    axes = ("E", "T", "M")
    learned_vals = [learned[a] for a in axes]
    ref_vals = [reference[a] for a in axes]
    x = range(len(axes))
    fig, ax = plt.subplots(figsize=(6, 4))
    width = 0.36
    ax.bar([i - width / 2 for i in x], ref_vals, width=width, label="current (reference)", color="tab:gray")
    ax.bar([i + width / 2 for i in x], learned_vals, width=width, label="learned", color="tab:blue")
    ax.set_xticks(list(x))
    ax.set_xticklabels(axes)
    ax.set_title("Mean squared error vs synthetic truth, by axis")
    ax.set_ylabel("MSE")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)
    plt.close(fig)
    return True


# --------------------------------------------------------------- markdown helpers
def _md_table(header: List[str], rows: List[List[Any]]) -> str:
    def _cell(v: Any) -> str:
        if isinstance(v, float):
            return f"{v:+.4f}" if abs(v) < 10 else f"{v:.2f}"
        return str(v)
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for row in rows:
        out.append("| " + " | ".join(_cell(v) for v in row) + " |")
    return "\n".join(out)


def _sum_axes(d: Dict[str, float]) -> float:
    return sum(d.values())


def _mean_axes(d: Dict[str, float]) -> float:
    return _sum_axes(d) / max(len(d), 1)


# --------------------------------------------------------------- recommendation
def _recommendation(
    eval_report: Dict[str, Any],
    baseline_rewards: Dict[str, float],
    ppo_final_reward: float,
) -> Tuple[str, List[str]]:
    """Produce a promote/inspect/reject verdict with numeric rationale."""
    reasons: List[str] = []
    verdict = "PROMOTE"

    # 1. Fit improvement: mean MSE across axes, learned vs reference.
    mse_l = _mean_axes(eval_report["mse_noisy_learned"])
    mse_r = _mean_axes(eval_report["mse_noisy_reference"])
    if mse_r <= 0:
        fit_pct = 0.0
    else:
        fit_pct = (mse_r - mse_l) / mse_r * 100.0
    if fit_pct < 0:
        verdict = "REJECT"
        reasons.append(f"learned MSE is *worse* than baseline by {-fit_pct:.1f}%.")
    elif fit_pct < 1.0:
        verdict = "INSPECT" if verdict == "PROMOTE" else verdict
        reasons.append(f"learned MSE improvement is small ({fit_pct:.1f}%) — may not justify a change.")
    else:
        reasons.append(f"learned MSE improves over baseline by {fit_pct:.1f}%.")

    # 2. Constraint regressions: any learned violation strictly worse than ref?
    cons_l = eval_report["constraint_mean_learned"]
    cons_r = eval_report["constraint_mean_reference"]
    if cons_l > cons_r + 1e-6:
        verdict = "REJECT"
        reasons.append(
            f"semantic constraint violations got *worse*: {cons_r:.3f} → {cons_l:.3f}."
        )
    elif cons_l > 0.0:
        if verdict == "PROMOTE":
            verdict = "INSPECT"
        reasons.append(
            f"learned params still violate some semantic constraints (mean={cons_l:.3f})."
        )
    else:
        reasons.append("learned params satisfy every semantic constraint.")

    # 3. Stability: high noise-induced std means the fit is fragile.
    stab_std = eval_report["stability_mse_std"]
    if stab_std > 0.01:
        if verdict == "PROMOTE":
            verdict = "INSPECT"
        reasons.append(f"stability std across noise draws is high ({stab_std:.4f}).")
    else:
        reasons.append(f"stability std across noise draws is low ({stab_std:.4f}).")

    # 4. Baselines: PPO should at least tie simple search. If it loses badly,
    # treat as a signal to inspect rather than promote.
    best_baseline = max(baseline_rewards.values()) if baseline_rewards else -math.inf
    if best_baseline > ppo_final_reward + 0.01:
        if verdict == "PROMOTE":
            verdict = "INSPECT"
        reasons.append(
            f"a gradient-free baseline ({best_baseline:+.3f}) beat PPO ({ppo_final_reward:+.3f})."
        )
    else:
        reasons.append(
            f"PPO ({ppo_final_reward:+.3f}) matches or beats every gradient-free baseline."
        )

    return verdict, reasons


# --------------------------------------------------------------- report writer
def _format_diff_section(diff: Dict[str, Dict[str, Dict[str, float]]]) -> str:
    """Render the diff_summary dict as readable markdown."""
    blocks: List[str] = []
    for section_label, section in (
        ("Trade-area prior deltas", diff.get("trade", {})),
        ("Business-type prior deltas", diff.get("type", {})),
        ("Daypart prior deltas", diff.get("daypart", {})),
        ("Weather prior deltas", diff.get("weather", {})),
    ):
        blocks.append(f"#### {section_label}")
        if not section:
            blocks.append("_No entries changed by more than ±0.01._\n")
            continue
        rows = [[key, d.get("E", 0.0), d.get("T", 0.0), d.get("M", 0.0)]
                for key, d in sorted(section.items(),
                                     key=lambda kv: -max(abs(v) for v in kv[1].values()))]
        blocks.append(_md_table(["key", "ΔE", "ΔT", "ΔM"], rows) + "\n")
    return "\n".join(blocks)


def _build_report(
    *,
    name: str,
    run_started: datetime,
    run_finished: datetime,
    ppo_cfg: PPOConfig,
    env_cfg: EnvConfig,
    history: List[Dict[str, Any]],
    eval_report: Dict[str, Any],
    diff: Dict[str, Any],
    baseline_rewards: Dict[str, float],
    ppo_final_reward: float,
    offsets_l1: float,
    learned_json_path: Path,
    training_png_rel: Optional[str],
    mse_png_rel: Optional[str],
    verdict: str,
    rationale: List[str],
    sample_paths: Optional[Dict[str, Path]] = None,
    sample_dump_n: int = 0,
) -> str:
    lines: List[str] = []

    lines.append(f"# RL Calibration Report — `{name}`")
    lines.append("")
    lines.append(
        f"_Run started {run_started.isoformat()} → finished "
        f"{run_finished.isoformat()} "
        f"(elapsed {(run_finished - run_started).total_seconds():.1f}s)._"
    )
    lines.append("")

    # ---- verdict ----
    verdict_badge = {"PROMOTE": "✅ PROMOTE", "INSPECT": "⚠️ INSPECT",
                     "REJECT": "❌ REJECT"}[verdict]
    lines.append(f"## Recommendation: **{verdict_badge}**")
    lines.append("")
    for r in rationale:
        lines.append(f"- {r}")
    lines.append("")
    lines.append(
        f"Exported offsets: `{learned_json_path.as_posix()}`. "
        f"To apply: `python -m app.research.rl_calibration.apply_to_production "
        f"--from {learned_json_path.as_posix()}`."
    )
    lines.append("")

    # ---- synthetic samples ----
    if sample_paths:
        lines.append("## Synthetic samples (inputs to PPO)")
        lines.append("")
        lines.append(
            f"A snapshot of **{sample_dump_n}** synthetic samples — the "
            "round-trip of `generate_batch` → `hidden_truth` → "
            "`simulate_text_evidence` — was dumped for inspection:"
        )
        lines.append("")
        for label, key, desc in (
            ("Markdown preview",    "md",   "readable; first 20 rows + distribution counts"),
            ("Full JSON",           "json", "every field, UTF-8, safe for Korean keys"),
            ("Flat CSV",            "csv",  "one row per sample, opens cleanly in Excel / sheets"),
        ):
            p = sample_paths.get(key)
            if p is None:
                continue
            rel = f"../synthetic_samples/{p.name}"
            lines.append(f"- **{label}** — [`{p.name}`]({rel}) — {desc}")
        lines.append("")
        lines.append(
            "The synthetic samples were generated *before* PPO training using "
            f"seed `{ppo_cfg.seed}`, so they reproduce bit-for-bit on reruns "
            "with the same seed."
        )
        lines.append("")

    # ---- configuration ----
    lines.append("## Configuration")
    lines.append("")
    lines.append(_md_table(
        ["knob", "value"],
        [
            ["ppo.total_updates", ppo_cfg.total_updates],
            ["ppo.rollout_steps", ppo_cfg.rollout_steps],
            ["ppo.minibatch_size", ppo_cfg.minibatch_size],
            ["ppo.epochs_per_update", ppo_cfg.epochs_per_update],
            ["ppo.gamma", ppo_cfg.gamma],
            ["ppo.gae_lambda", ppo_cfg.gae_lambda],
            ["ppo.clip_eps", ppo_cfg.clip_eps],
            ["ppo.policy_lr", ppo_cfg.policy_lr],
            ["ppo.value_lr", ppo_cfg.value_lr],
            ["ppo.entropy_coef", ppo_cfg.entropy_coef],
            ["env.episode_length", env_cfg.episode_length],
            ["env.scenarios_per_episode", env_cfg.scenarios_per_episode],
            ["env.action_scale", env_cfg.action_scale],
        ],
    ))
    lines.append("")

    # ---- training curves ----
    lines.append("## Training dynamics")
    lines.append("")
    if training_png_rel is not None:
        lines.append(f"![training curves]({training_png_rel})")
        lines.append("")
    final = history[-1] if history else {}
    first = history[0] if history else {}
    lines.append(_md_table(
        ["metric", "first update", "last update"],
        [
            ["avg_reward", first.get("avg_reward", float("nan")),
             final.get("avg_reward", float("nan"))],
            ["policy_loss", first.get("policy_loss", float("nan")),
             final.get("policy_loss", float("nan"))],
            ["value_loss", first.get("value_loss", float("nan")),
             final.get("value_loss", float("nan"))],
            ["entropy", first.get("entropy", float("nan")),
             final.get("entropy", float("nan"))],
            ["kl", first.get("kl", float("nan")), final.get("kl", float("nan"))],
        ],
    ))
    lines.append("")

    # ---- fit summary ----
    lines.append("## Fit to synthetic ground truth")
    lines.append("")
    if mse_png_rel is not None:
        lines.append(f"![per-axis MSE]({mse_png_rel})")
        lines.append("")
    mse_l = eval_report["mse_noisy_learned"]
    mse_r = eval_report["mse_noisy_reference"]
    mse_lc = eval_report["mse_clean_learned"]
    rows = []
    for a in ("E", "T", "M"):
        if mse_r[a] <= 0:
            pct = 0.0
        else:
            pct = (mse_r[a] - mse_l[a]) / mse_r[a] * 100.0
        rows.append([a, mse_r[a], mse_l[a], mse_lc[a], f"{pct:+.1f}%"])
    lines.append(_md_table(
        ["axis", "MSE reference (noisy)", "MSE learned (noisy)",
         "MSE learned (clean)", "Δ vs reference"],
        rows,
    ))
    lines.append("")
    lines.append(f"Stability MSE std across noise draws: **{eval_report['stability_mse_std']:.4f}** "
                 f"(lower = more robust).")
    lines.append("")
    lines.append(f"Offset L1 magnitude: **{offsets_l1:.3f}** "
                 f"(0 = no change vs production).")
    lines.append("")

    # ---- constraints ----
    lines.append("## Semantic-constraint breakdown")
    lines.append("")
    lines.append(
        f"Mean violation: baseline **{eval_report['constraint_mean_reference']:.3f}**, "
        f"learned **{eval_report['constraint_mean_learned']:.3f}**. "
        f"A violation score of 0 means the rule holds; larger = worse."
    )
    lines.append("")
    cons_rows = [[name, v] for name, v in sorted(
        eval_report["constraint_breakdown_learned"].items(),
        key=lambda kv: -kv[1])]
    lines.append(_md_table(["constraint", "learned violation"], cons_rows))
    lines.append("")

    # ---- diff ----
    lines.append("## What would change in `ambience_service.py`")
    lines.append("")
    lines.append(
        "Only entries whose absolute delta exceeds **0.01** are listed. "
        "Δ values are the shift the learned offsets would apply to the "
        "current production prior tables."
    )
    lines.append("")
    lines.append(_format_diff_section(diff))

    # ---- baselines ----
    lines.append("## Sanity check against gradient-free baselines")
    lines.append("")
    rows = [["PPO (final update avg reward)", ppo_final_reward]]
    for bname, br in baseline_rewards.items():
        rows.append([bname, br])
    lines.append(_md_table(["method", "reward"], rows))
    lines.append("")
    lines.append(
        "Rewards are the composite PPO reward (fit + constraints + stability + "
        "regularization + bounds). Higher is better. If a gradient-free method "
        "beats PPO, treat the learned params as suspect."
    )
    lines.append("")

    # ---- footer ----
    lines.append("---")
    lines.append("")
    lines.append(
        "This report and all intermediate artifacts live under "
        "`outputs/rl_calibration/`. The learned offsets JSON is the file "
        "consumed by `apply_to_production.py`. To revert any promoted change, "
        "run `python -m app.research.rl_calibration.apply_to_production --restore`."
    )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- main pipeline
def run(
    *,
    name: str = "ambience_v1",
    total_updates: int = 1,
    rollout_steps: int = 512,
    episode_length: int = 16,
    scenarios_per_episode: int = 8,
    rollout_episodes: int = 20,
    eval_scenarios: int = 400,
    baseline_iters: int = 300,
    baseline_scenarios: int = 128,
    sample_dump_n: int = 128,
    seed: int = 20260423,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Run the full pipeline and write the Markdown report.

    Returns a dict with paths and headline numbers so callers can assert on
    them programmatically.
    """
    ensure_output_dirs()
    t0 = datetime.now(timezone.utc)

    ppo_cfg = PPOConfig(
        seed=seed,
        total_updates=total_updates,
        rollout_steps=rollout_steps,
    )
    env_cfg = EnvConfig(
        episode_length=episode_length,
        scenarios_per_episode=scenarios_per_episode,
    )

    sample_paths: Optional[Dict[str, Path]] = None
    if sample_dump_n > 0:
        if verbose:
            print(f"[0/4] Dumping {sample_dump_n} synthetic samples for visual inspection")
        sample_paths = dump_synthetic_samples(
            name=name, n=sample_dump_n, seed=seed, verbose=verbose,
        )
    elif verbose:
        print("[0/4] Skipping synthetic-sample dump (--sample-dump-n 0)")

    if verbose:
        print(f"[1/4] PPO training: updates={total_updates} rollout_steps={rollout_steps}")
    trainer, env, history = ppo_train(
        ppo_cfg=ppo_cfg,
        env_cfg=env_cfg,
        save_name=name,
        verbose=verbose,
    )
    ppo_final_reward = history[-1]["avg_reward"] if history else float("nan")

    if verbose:
        print(f"[2/4] Rolling out greedy policy for {rollout_episodes} episodes")
    best_params: OffsetParams = rollout_policy(
        trainer, env, n_episodes=rollout_episodes, greedy=True,
    )

    if verbose:
        print(f"[3/4] Evaluating on {eval_scenarios} synthetic scenarios")
    eval_report = evaluate_params(best_params, n_scenarios=eval_scenarios, seed=seed + 1)
    write_report(eval_report, name=name + "_eval")

    # Always export — the JSON is required for apply_to_production.py.
    learned_json_path = export(
        best_params,
        name=name,
        metadata={"run_name": name, "ppo_updates": total_updates, "seed": seed},
    )
    diff = diff_summary(best_params)

    if verbose:
        print(f"[4/4] Baseline sanity checks: random_search + hillclimb "
              f"(iters={baseline_iters}, scenarios={baseline_scenarios})")
    _, rs_reward = random_search(
        n_iters=baseline_iters, n_scenarios=baseline_scenarios, seed=seed + 2,
    )
    _, hc_reward = hillclimb(
        n_iters=baseline_iters, n_scenarios=baseline_scenarios, seed=seed + 3,
    )
    baseline_rewards = {"random_search": rs_reward, "hillclimb": hc_reward}

    # ---- plots ----
    training_png = REPORT_DIR / f"{name}_training_curves.png"
    mse_png = REPORT_DIR / f"{name}_mse_bars.png"
    ok_train = _plot_training_curves(history, training_png)
    ok_mse = _plot_mse_bars(
        eval_report["mse_noisy_learned"],
        eval_report["mse_noisy_reference"],
        mse_png,
    )

    verdict, rationale = _recommendation(eval_report, baseline_rewards, ppo_final_reward)

    t1 = datetime.now(timezone.utc)
    md = _build_report(
        name=name,
        run_started=t0,
        run_finished=t1,
        ppo_cfg=ppo_cfg,
        env_cfg=env_cfg,
        history=history,
        eval_report=eval_report,
        diff=diff,
        baseline_rewards=baseline_rewards,
        ppo_final_reward=ppo_final_reward,
        offsets_l1=best_params.total_magnitude(),
        learned_json_path=learned_json_path,
        training_png_rel=training_png.name if ok_train else None,
        mse_png_rel=mse_png.name if ok_mse else None,
        verdict=verdict,
        rationale=rationale,
        sample_paths=sample_paths,
        sample_dump_n=sample_dump_n,
    )
    md_path = REPORT_DIR / f"{name}.md"
    md_path.write_text(md, encoding="utf-8")

    if verbose:
        _safe_print(f"\nVerdict: {verdict}")
        for r in rationale:
            _safe_print(f"  - {r}")
        _safe_print(f"\nReport   -> {md_path}")
        _safe_print(f"Offsets  -> {learned_json_path}")
        _safe_print(f"Raw eval -> {REPORT_DIR / (name + '_eval.json')}")

    return {
        "verdict": verdict,
        "rationale": rationale,
        "report_md": md_path,
        "learned_json": learned_json_path,
        "eval_report_json": REPORT_DIR / f"{name}_eval.json",
        "training_curves_png": training_png if ok_train else None,
        "mse_bars_png": mse_png if ok_mse else None,
        "synthetic_samples": sample_paths,
        "ppo_final_reward": ppo_final_reward,
        "baseline_rewards": baseline_rewards,
        "offsets_l1": best_params.total_magnitude(),
    }


def _cli(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description="Run the full RL calibration pipeline and write a Markdown decision report.",
    )
    ap.add_argument("--name", default="ambience_v1",
                    help="base name for all generated artifacts (default: ambience_v1)")
    ap.add_argument("--updates", type=int, default=30, dest="total_updates",
                    help="PPO total updates (default: 30)")
    ap.add_argument("--rollout-steps", type=int, default=512, dest="rollout_steps",
                    help="PPO rollout steps per update (default: 512)")
    ap.add_argument("--episode-length", type=int, default=16, dest="episode_length",
                    help="env episode length (default: 16)")
    ap.add_argument("--scenarios-per-episode", type=int, default=8,
                    dest="scenarios_per_episode",
                    help="scenarios batched per reward evaluation (default: 8)")
    ap.add_argument("--rollout-episodes", type=int, default=20,
                    help="greedy rollout episodes to pick best params (default: 20)")
    ap.add_argument("--eval-scenarios", type=int, default=400,
                    help="scenarios used for the eval report (default: 400)")
    ap.add_argument("--baseline-iters", type=int, default=300,
                    help="iterations per baseline method (default: 300)")
    ap.add_argument("--baseline-scenarios", type=int, default=128,
                    help="scenarios per baseline iter (default: 128)")
    ap.add_argument("--sample-dump-n", type=int, default=128, dest="sample_dump_n",
                    help="how many synthetic samples to dump for inspection "
                         "into outputs/rl_calibration/synthetic_samples/ "
                         "(default: 128; set 0 to skip)")
    ap.add_argument("--seed", type=int, default=20260423,
                    help="global seed (default: 20260423)")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress per-update stdout logs")
    args = ap.parse_args(argv)
    run(
        name=args.name,
        total_updates=args.total_updates,
        rollout_steps=args.rollout_steps,
        episode_length=args.episode_length,
        scenarios_per_episode=args.scenarios_per_episode,
        rollout_episodes=args.rollout_episodes,
        eval_scenarios=args.eval_scenarios,
        baseline_iters=args.baseline_iters,
        baseline_scenarios=args.baseline_scenarios,
        sample_dump_n=args.sample_dump_n,
        seed=args.seed,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    _cli()
