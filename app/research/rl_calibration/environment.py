"""Sequential-calibration PPO environment.

RL formulation (fixed by project spec):
    Formulation B — sequential calibration.

At each step:
    - observation = current flat offset vector
                    + summary stats of the current batch of scenarios
    - action      = per-index *delta* applied to the offset vector
                    (each delta is `action_scale * bound * tanh(raw_action)`)
    - reward      = composite reward from `reward.compute_reward()`

An episode runs for `env_cfg.episode_length` steps on a freshly sampled batch
of scenarios. At `reset()` we refresh the scenario batch (and the episode
starts from zero offsets by default — this is research, not continuation).

NOTE: we implement a minimal Gym-like surface (`reset`, `step`, `action_dim`,
`obs_dim`) rather than importing gymnasium — the PPO trainer in this package
talks to this surface directly and doesn't need full Gym compat.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from .config import (
    DAYPART_WINDOW_SHIFT_BOUND,
    EnvConfig,
    OFFSET_BOUND_BASE,
    OFFSET_BOUND_DAYPART,
    OFFSET_BOUND_DEFAULT,
    OFFSET_BOUND_TRADE,
    OFFSET_BOUND_TYPE,
    OFFSET_BOUND_WEATHER,
    RewardWeights,
)
from .offsets import (
    OFFSET_VECTOR_DIM,
    build_default_params,
    flat_bounds,
    flat_vector_to_offsets,
    offsets_to_flat_vector,
)
from .reward import RewardBreakdown, compute_reward
from .scenario_generator import generate_batch
from .synthetic_world import hidden_truth
from .text_simulator import simulate_text_evidence


# Observation = flat offsets + 3 axis-means of current-batch text + 3 axis-means of truth-summary
# + scalar confidence + scalar step-counter
_EXTRA_OBS = 3 + 3 + 1 + 1
OBS_DIM: int = OFFSET_VECTOR_DIM + _EXTRA_OBS


def _bounds() -> np.ndarray:
    return np.asarray(
        flat_bounds(
            base_bound=OFFSET_BOUND_BASE,
            trade_bound=OFFSET_BOUND_TRADE,
            type_bound=OFFSET_BOUND_TYPE,
            daypart_bound=OFFSET_BOUND_DAYPART,
            weather_bound=OFFSET_BOUND_WEATHER,
            default_bound=OFFSET_BOUND_DEFAULT,
            window_shift_bound=DAYPART_WINDOW_SHIFT_BOUND,
        ),
        dtype=np.float64,
    )


@dataclass
class EpisodeStats:
    steps: int
    last_reward: float
    last_breakdown: Optional[RewardBreakdown]


class CalibrationEnv:
    """Sequential PPO env for ambience prior calibration."""

    def __init__(
        self,
        env_cfg: Optional[EnvConfig] = None,
        reward_weights: Optional[RewardWeights] = None,
        seed: Optional[int] = None,
    ) -> None:
        self.env_cfg = env_cfg or EnvConfig()
        self.reward_weights = reward_weights or RewardWeights()
        self._rng = random.Random(seed if seed is not None else 20260423)

        self.action_dim = OFFSET_VECTOR_DIM
        self.obs_dim = OBS_DIM
        self._bounds = _bounds()

        # Episode state
        self._offsets_flat: np.ndarray = np.zeros(OFFSET_VECTOR_DIM, dtype=np.float64)
        self._prev_offsets_flat: np.ndarray = np.zeros(OFFSET_VECTOR_DIM, dtype=np.float64)
        self._scenarios = []
        self._truths = []
        self._texts = []
        self._step_i = 0
        self._last_breakdown: Optional[RewardBreakdown] = None

    # --------------------------------------------------------------- helpers
    def _resample_batch(self) -> None:
        scenarios = generate_batch(self.env_cfg.scenarios_per_episode, self._rng)
        truths = [hidden_truth(s, noisy=True) for s in scenarios]
        texts = [simulate_text_evidence(s, t, rng=self._rng) for s, t in zip(scenarios, truths)]
        self._scenarios = scenarios
        self._truths = truths
        self._texts = texts

    def _observation(self) -> np.ndarray:
        if self._scenarios:
            et = np.mean([t.E_text for t in self._texts])
            tt = np.mean([t.T_text for t in self._texts])
            mt = np.mean([t.M_text for t in self._texts])
            te = np.mean([h.energy for h in self._truths])
            tt2 = np.mean([h.tempo for h in self._truths])
            tm = np.mean([h.mood for h in self._truths])
            ctx = np.mean([t.c_text for t in self._texts])
        else:
            et = tt = mt = te = tt2 = tm = ctx = 0.5
        extras = np.asarray(
            [et, tt, mt, te, tt2, tm, ctx, float(self._step_i) / max(1, self.env_cfg.episode_length)],
            dtype=np.float64,
        )
        return np.concatenate([self._offsets_flat, extras], axis=0)

    def _current_params(self):
        return flat_vector_to_offsets(self._offsets_flat.tolist())

    # --------------------------------------------------------------- gym-ish API
    def reset(self) -> np.ndarray:
        """Start a fresh episode at zero offsets with a new scenario batch."""
        self._offsets_flat = np.zeros(OFFSET_VECTOR_DIM, dtype=np.float64)
        self._prev_offsets_flat = np.zeros(OFFSET_VECTOR_DIM, dtype=np.float64)
        self._step_i = 0
        self._resample_batch()
        self._last_breakdown = None
        return self._observation()

    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, bool, dict]:
        """Apply an action and return (obs, reward, done, info).

        `action` is a length-OFFSET_VECTOR_DIM vector in approximately [-1,1]
        (Gaussian policy before squashing). We squash via tanh to prevent
        blowups and scale by `env_cfg.action_scale * bounds` so each delta is
        a small step. Final offsets are clipped to +/- bounds so the agent
        never drifts outside the parameterization's trust region.
        """
        action = np.asarray(action, dtype=np.float64).reshape(-1)
        if action.shape[0] != self.action_dim:
            raise ValueError(f"action dim {action.shape[0]} != {self.action_dim}")
        squashed = np.tanh(action)
        delta = squashed * self._bounds * float(self.env_cfg.action_scale)

        self._prev_offsets_flat = self._offsets_flat.copy()
        self._offsets_flat = np.clip(
            self._offsets_flat + delta, -self._bounds, self._bounds,
        )

        drift = float(np.linalg.norm(self._offsets_flat - self._prev_offsets_flat))
        params = self._current_params()
        breakdown = compute_reward(
            params=params,
            scenarios=self._scenarios,
            truths=self._truths,
            texts=self._texts,
            stability_penalty=drift,
            weights=self.reward_weights,
        )
        self._last_breakdown = breakdown
        self._step_i += 1
        done = self._step_i >= self.env_cfg.episode_length

        obs = self._observation()
        info = {
            "drift": drift,
            "reward_breakdown": breakdown,
            "offsets_l1": float(np.abs(self._offsets_flat).sum()),
        }
        return obs, float(breakdown.total), done, info

    # --------------------------------------------------------------- introspection
    @property
    def current_offsets(self) -> np.ndarray:
        return self._offsets_flat.copy()

    def current_params(self):
        return self._current_params()

    def scenarios(self):
        return list(self._scenarios)

    def last_breakdown(self) -> Optional[RewardBreakdown]:
        return self._last_breakdown

    def reseed(self, seed: int) -> None:
        self._rng = random.Random(seed)
