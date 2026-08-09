"""Configuration constants for the RL calibration subsystem.

Kept as plain module-level constants (not env-driven) because this is a research
pipeline — reproducibility matters more than runtime flexibility. Override by
importing and mutating, or by passing overrides into `ppo_train.train()`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from ...config import PROJECT_ROOT


OUTPUT_ROOT: Path = PROJECT_ROOT / "outputs" / "rl_calibration"
CHECKPOINT_DIR: Path = OUTPUT_ROOT / "checkpoints"
REPORT_DIR: Path = OUTPUT_ROOT / "reports"
LEARNED_PARAMS_DIR: Path = OUTPUT_ROOT / "learned_params"


# --- Offset bounds ---------------------------------------------------------
# Keep offsets small enough that learned parameters stay interpretable. The
# agent emits raw actions in [-1,1]; we rescale to these bounds.
OFFSET_BOUND_BASE: float = 0.10        # allowed shift on the global base
OFFSET_BOUND_TRADE: float = 0.20       # per-trade-area offsets
OFFSET_BOUND_TYPE: float = 0.20        # per-business-type offsets
OFFSET_BOUND_DAYPART: float = 0.15     # per-daypart offsets
OFFSET_BOUND_WEATHER: float = 0.10     # per-weather offsets
OFFSET_BOUND_DEFAULT: float = 0.15     # default-trade / default-type offsets
DAYPART_WINDOW_SHIFT_BOUND: float = 2.0  # hours of allowed boundary shift


# --- Reward weights --------------------------------------------------------
@dataclass
class RewardWeights:
    fit: float = 1.0               # negative MSE vs hidden truth (per axis)
    constraint: float = 0.6        # satisfaction of semantic constraints
    stability: float = 0.3         # penalty on step-to-step oscillation
    regularization: float = 0.25   # anti-extremeness on offset magnitude
    bounds_penalty: float = 1.0    # hard penalty when effective priors clip


# --- PPO hyper-parameters --------------------------------------------------
@dataclass
class PPOConfig:
    seed: int = 20260423
    rollout_steps: int = 512       # env steps per rollout
    epochs_per_update: int = 4
    minibatch_size: int = 64
    total_updates: int = 30
    gamma: float = 0.95
    gae_lambda: float = 0.95
    clip_eps: float = 0.2
    policy_lr: float = 3e-4
    value_lr: float = 1e-3
    entropy_coef: float = 0.01
    value_coef: float = 0.5
    max_grad_norm: float = 0.5
    hidden_size: int = 64
    log_std_init: float = -0.5     # exp(-0.5) ≈ 0.607 starting action std
    reward: RewardWeights = field(default_factory=RewardWeights)


# --- Environment / episode --------------------------------------------------
@dataclass
class EnvConfig:
    episode_length: int = 16       # sequential offset edits per episode
    scenarios_per_episode: int = 8  # batched scenarios per reward evaluation
    action_scale: float = 0.05     # per-step offset delta fraction (of bound)
    include_window_shifts_in_action: bool = False  # optional extended action


def ensure_output_dirs() -> None:
    for p in (CHECKPOINT_DIR, REPORT_DIR, LEARNED_PARAMS_DIR):
        p.mkdir(parents=True, exist_ok=True)
