"""PyTorch-based PPO trainer for the calibration env.

Drop-in replacement for the previous numpy-only implementation. The public
surface (``MLPPolicy``, ``MLPValue``, ``PPOTrainer``, module-level
``train()``) is preserved so that callers in ``evaluate.py`` and
``run_calibration.py`` keep working unchanged. Internally the policy and
value networks are now ``torch.nn.Module`` subclasses, gradients flow via
``torch.autograd``, and ``torch.optim.Adam`` handles updates.

What changed vs the numpy version
---------------------------------
- Networks are ``nn.Module`` (orthogonal-initialised tanh MLPs) and the
  Gaussian policy uses ``torch.distributions.Normal`` for log-probs and
  entropy, instead of hand-rolled formulas.
- Policy / value gradients are obtained by ``loss.backward()``; the manual
  chain-rule blocks (``_policy_forward_grad`` / ``_value_forward_grad``) are
  gone.
- Gradient clipping uses ``torch.nn.utils.clip_grad_norm_``.
- Checkpoints are saved with ``torch.save`` (state_dict + optimizer state)
  to ``{name}.pt`` instead of ``{name}.npz``.
- The trainer still talks numpy at the env boundary (``env.reset()`` /
  ``env.step()`` are unchanged) — only the inner learning loop is on torch.

Behavioral parity with the numpy version
----------------------------------------
- Same orthogonal init scales (sqrt(2) for hidden layers, 0.01 for the
  Gaussian mean head, 1.0 for the value head).
- Same observation/action normalisation: there isn't any — observation
  normalisation was deliberately omitted to keep the trainer
  hyperparameter-light.
- Same GAE(λ) advantage computation and advantage normalisation.
- Same minimum/maximum clamp on ``log_std`` ([-4, 1]) so action variance
  stays sane.
- Same global gradient-norm clip from ``cfg.max_grad_norm``.

To swap in a GPU run, set the ``device`` kwarg of ``PPOTrainer`` (or the
``CUDA_VISIBLE_DEVICES`` env var) — but for this small problem CPU is
fastest because rollouts dominate runtime.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.distributions import Normal

from .config import CHECKPOINT_DIR, EnvConfig, PPOConfig, RewardWeights, ensure_output_dirs
from .environment import CalibrationEnv, OBS_DIM
from .offsets import OFFSET_VECTOR_DIM, flat_vector_to_offsets


ArrayLike = Union[np.ndarray, torch.Tensor]


# --------------------------------------------------------------- helpers
def _set_global_seed(seed: int) -> None:
    """Seed torch + numpy RNGs together so rollouts and updates are reproducible."""
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _orthogonal_(layer: nn.Linear, gain: float) -> None:
    nn.init.orthogonal_(layer.weight, gain=gain)
    nn.init.zeros_(layer.bias)


def _to_tensor(x: ArrayLike, *, device: torch.device, dtype: torch.dtype = torch.float32) -> torch.Tensor:
    if isinstance(x, torch.Tensor):
        return x.to(device=device, dtype=dtype)
    return torch.as_tensor(np.asarray(x), dtype=dtype, device=device)


# --------------------------------------------------------------- networks
class MLPPolicy(nn.Module):
    """Gaussian policy: π(a|s) = N(μ(s), diag(exp(log_std)²))."""

    def __init__(
        self,
        obs_dim: int,
        act_dim: int,
        hidden: int,
        log_std_init: float,
        device: Optional[torch.device] = None,
    ) -> None:
        super().__init__()
        self.obs_dim = obs_dim
        self.act_dim = act_dim
        self.fc1 = nn.Linear(obs_dim, hidden)
        self.fc2 = nn.Linear(hidden, hidden)
        # Mean head — small init so early actions are near-zero and the agent
        # does not blow past the trust-region bounds in step #1.
        self.mu_head = nn.Linear(hidden, act_dim)
        self.log_std = nn.Parameter(torch.full((act_dim,), float(log_std_init)))

        _orthogonal_(self.fc1, gain=math.sqrt(2.0))
        _orthogonal_(self.fc2, gain=math.sqrt(2.0))
        _orthogonal_(self.mu_head, gain=0.01)

        self._device = device or torch.device("cpu")
        self.to(self._device)

    # --------------------------- internal trunk
    def _trunk(self, x: torch.Tensor) -> torch.Tensor:
        h = torch.tanh(self.fc1(x))
        h = torch.tanh(self.fc2(h))
        return h

    # --------------------------- numpy-friendly inference API
    def forward(self, obs: ArrayLike) -> Tuple[ArrayLike, ArrayLike]:
        """Return ``(mean, std)`` with the same shape conventions as the old API.

        - 1D numpy obs -> 1D numpy ``mean``/``std``.
        - 2D numpy batch -> 2D numpy ``mean``/``std``.
        - torch tensor obs -> torch tensors (used by the inner training loop).
        """
        if isinstance(obs, torch.Tensor):
            mu = self.mu_head(self._trunk(obs))
            std = self.log_std.exp().expand_as(mu)
            return mu, std

        x = np.asarray(obs)
        single = x.ndim == 1
        x_t = torch.as_tensor(x if not single else x.reshape(1, -1), dtype=torch.float32,
                              device=self._device)
        with torch.no_grad():
            mu_t = self.mu_head(self._trunk(x_t))
            std_t = self.log_std.exp().expand_as(mu_t)
        mu = mu_t.cpu().numpy().astype(np.float64)
        std = std_t.cpu().numpy().astype(np.float64)
        return (mu[0], std[0]) if single else (mu, std)

    def sample(
        self, obs: np.ndarray, rng: Optional[np.random.Generator] = None,
    ) -> Tuple[np.ndarray, float]:
        """Sample one action from N(μ(s), σ²) and return ``(action, log_prob)``.

        ``rng`` is accepted for API compatibility with the old numpy trainer but
        the actual sampling is delegated to torch's RNG (which the trainer
        seeds globally).
        """
        x = np.asarray(obs)
        single = x.ndim == 1
        x_t = torch.as_tensor(x if not single else x.reshape(1, -1), dtype=torch.float32,
                              device=self._device)
        with torch.no_grad():
            mu = self.mu_head(self._trunk(x_t))
            std = self.log_std.exp().expand_as(mu)
            dist = Normal(mu, std)
            act = dist.sample()
            logp = dist.log_prob(act).sum(dim=-1)
        act_np = act.cpu().numpy().astype(np.float64)
        logp_np = logp.cpu().numpy().astype(np.float64)
        if single:
            return act_np[0], float(logp_np[0])
        return act_np, logp_np

    # --------------------------- training-loop API
    def log_prob_batch(self, obs_t: torch.Tensor, act_t: torch.Tensor) -> torch.Tensor:
        mu = self.mu_head(self._trunk(obs_t))
        std = self.log_std.exp().expand_as(mu)
        return Normal(mu, std).log_prob(act_t).sum(dim=-1)

    def entropy(self) -> float:
        """Policy entropy (in nats), summed over action dims.

        For an isotropic Gaussian this is action-independent, so we expose it
        as a scalar instead of a per-batch tensor.
        """
        # Per-dim entropy of N(0, σ²) is 0.5*(1 + log(2πσ²)) = 0.5*(1+log 2π) + log σ.
        return float(
            (0.5 * (1.0 + math.log(2.0 * math.pi)) * self.act_dim
             + self.log_std.sum()).detach().cpu().item()
        )


class MLPValue(nn.Module):
    """Tanh-MLP critic with a single scalar output."""

    def __init__(self, obs_dim: int, hidden: int, device: Optional[torch.device] = None) -> None:
        super().__init__()
        self.fc1 = nn.Linear(obs_dim, hidden)
        self.fc2 = nn.Linear(hidden, hidden)
        self.head = nn.Linear(hidden, 1)
        _orthogonal_(self.fc1, gain=math.sqrt(2.0))
        _orthogonal_(self.fc2, gain=math.sqrt(2.0))
        _orthogonal_(self.head, gain=1.0)

        self._device = device or torch.device("cpu")
        self.to(self._device)

    def _trunk(self, x: torch.Tensor) -> torch.Tensor:
        h = torch.tanh(self.fc1(x))
        h = torch.tanh(self.fc2(h))
        return h

    def forward(self, obs: ArrayLike) -> ArrayLike:
        """Numpy-friendly forward.

        - 1D numpy obs -> python ``float`` (matches old API used by rollouts).
        - 2D numpy batch -> 1D numpy array.
        - torch tensor input -> torch tensor (used in training loop).
        """
        if isinstance(obs, torch.Tensor):
            return self.head(self._trunk(obs)).squeeze(-1)

        x = np.asarray(obs)
        single = x.ndim == 1
        x_t = torch.as_tensor(x if not single else x.reshape(1, -1), dtype=torch.float32,
                              device=self._device)
        with torch.no_grad():
            v = self.head(self._trunk(x_t)).squeeze(-1)
        v_np = v.cpu().numpy().astype(np.float64)
        return float(v_np[0]) if single else v_np


# --------------------------------------------------------------- trainer
class PPOTrainer:
    """PPO trainer wrapping the calibration env.

    The trainer is intentionally minimal — clipped surrogate, entropy bonus,
    GAE(λ), Gaussian policy, MSE critic — and aims for parity with the
    previous numpy version's hyperparameters.
    """

    def __init__(
        self,
        env: CalibrationEnv,
        cfg: Optional[PPOConfig] = None,
        device: Optional[Union[str, torch.device]] = None,
    ) -> None:
        self.env = env
        self.cfg = cfg or PPOConfig()
        self.device = torch.device(device) if device is not None else torch.device("cpu")

        _set_global_seed(self.cfg.seed)
        # Numpy RNG is kept for minibatch shuffling and is seeded from the same
        # PPOConfig.seed so the order of minibatches is reproducible.
        self.rng = np.random.default_rng(self.cfg.seed)

        self.policy = MLPPolicy(
            obs_dim=env.obs_dim,
            act_dim=env.action_dim,
            hidden=self.cfg.hidden_size,
            log_std_init=self.cfg.log_std_init,
            device=self.device,
        )
        self.value = MLPValue(
            obs_dim=env.obs_dim,
            hidden=self.cfg.hidden_size,
            device=self.device,
        )

        self.policy_optim = optim.Adam(self.policy.parameters(), lr=self.cfg.policy_lr)
        self.value_optim = optim.Adam(self.value.parameters(), lr=self.cfg.value_lr)

        self.history: List[Dict[str, float]] = []

    # --------------------------------------------------------------- rollouts
    def _collect_rollout(self) -> Dict[str, np.ndarray]:
        """Roll the policy in the env for ``cfg.rollout_steps`` and return GAE buffers."""
        T = self.cfg.rollout_steps
        obs_buf = np.zeros((T, self.env.obs_dim), dtype=np.float64)
        act_buf = np.zeros((T, self.env.action_dim), dtype=np.float64)
        logp_buf = np.zeros(T, dtype=np.float64)
        rew_buf = np.zeros(T, dtype=np.float64)
        done_buf = np.zeros(T, dtype=np.float64)
        val_buf = np.zeros(T, dtype=np.float64)

        obs = self.env.reset()
        for i in range(T):
            act, logp = self.policy.sample(obs, self.rng)
            val = float(self.value.forward(obs))
            new_obs, reward, done, _info = self.env.step(act)

            obs_buf[i] = obs
            act_buf[i] = act
            logp_buf[i] = logp
            rew_buf[i] = reward
            done_buf[i] = float(done)
            val_buf[i] = val

            obs = new_obs if not done else self.env.reset()

        last_val = float(self.value.forward(obs))

        # GAE(λ)
        adv = np.zeros_like(rew_buf)
        last_gae = 0.0
        for t in reversed(range(T)):
            next_val = last_val if t == T - 1 else val_buf[t + 1]
            next_nonterm = 1.0 - done_buf[t]
            delta = rew_buf[t] + self.cfg.gamma * next_val * next_nonterm - val_buf[t]
            last_gae = delta + self.cfg.gamma * self.cfg.gae_lambda * next_nonterm * last_gae
            adv[t] = last_gae

        returns = adv + val_buf
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)

        return {
            "obs": obs_buf, "act": act_buf, "logp": logp_buf,
            "rew": rew_buf, "adv": adv, "ret": returns, "val": val_buf,
        }

    # --------------------------------------------------------------- update
    def _ppo_update(self, data: Dict[str, np.ndarray]) -> Dict[str, float]:
        """Run ``epochs_per_update`` passes of clipped PPO + value MSE on the rollout."""
        obs_t = _to_tensor(data["obs"], device=self.device)
        act_t = _to_tensor(data["act"], device=self.device)
        old_logp_t = _to_tensor(data["logp"], device=self.device)
        adv_t = _to_tensor(data["adv"], device=self.device)
        ret_t = _to_tensor(data["ret"], device=self.device)

        N = obs_t.shape[0]
        idx = np.arange(N)
        clip = float(self.cfg.clip_eps)

        ep_pi = ep_v = ep_kl = ep_H = 0.0
        ep_mb = 0

        for _ in range(self.cfg.epochs_per_update):
            self.rng.shuffle(idx)
            for start in range(0, N, self.cfg.minibatch_size):
                mb = idx[start:start + self.cfg.minibatch_size]
                if mb.size == 0:
                    continue
                mb_t = torch.as_tensor(mb, dtype=torch.long, device=self.device)
                obs_mb = obs_t.index_select(0, mb_t)
                act_mb = act_t.index_select(0, mb_t)
                old_logp_mb = old_logp_t.index_select(0, mb_t)
                adv_mb = adv_t.index_select(0, mb_t)
                ret_mb = ret_t.index_select(0, mb_t)

                # ---- policy loss (clipped surrogate + entropy bonus)
                new_logp = self.policy.log_prob_batch(obs_mb, act_mb)
                ratio = torch.exp(new_logp - old_logp_mb)
                surr1 = ratio * adv_mb
                surr2 = torch.clamp(ratio, 1.0 - clip, 1.0 + clip) * adv_mb
                policy_loss = -torch.min(surr1, surr2).mean()
                # Closed-form Gaussian entropy (action-independent, scalar).
                entropy = (
                    0.5 * (1.0 + math.log(2.0 * math.pi)) * self.policy.act_dim
                    + self.policy.log_std.sum()
                )
                total_policy_loss = policy_loss - self.cfg.entropy_coef * entropy

                self.policy_optim.zero_grad(set_to_none=True)
                total_policy_loss.backward()
                nn.utils.clip_grad_norm_(self.policy.parameters(), self.cfg.max_grad_norm)
                self.policy_optim.step()
                # Keep log_std in a sane range so std neither vanishes nor explodes.
                with torch.no_grad():
                    self.policy.log_std.clamp_(min=-4.0, max=1.0)

                # ---- value loss (MSE)
                v_pred = self.value(obs_mb)
                value_loss = F.mse_loss(v_pred, ret_mb)

                self.value_optim.zero_grad(set_to_none=True)
                value_loss.backward()
                nn.utils.clip_grad_norm_(self.value.parameters(), self.cfg.max_grad_norm)
                self.value_optim.step()

                with torch.no_grad():
                    ep_pi += float(policy_loss.detach().cpu().item())
                    ep_v += float(value_loss.detach().cpu().item())
                    ep_kl += float((old_logp_mb - new_logp).detach().mean().cpu().item())
                    ep_H += float(entropy.detach().cpu().item())
                ep_mb += 1

        nb = max(ep_mb, 1)
        return {
            "policy_loss": ep_pi / nb,
            "value_loss": ep_v / nb,
            "kl": ep_kl / nb,
            "entropy": ep_H / nb,
        }

    # --------------------------------------------------------------- outer loop
    def train(
        self,
        *,
        progress_cb: Optional[Callable[[int, Dict[str, float]], None]] = None,
    ) -> List[Dict[str, float]]:
        for update in range(self.cfg.total_updates):
            t0 = time.time()
            data = self._collect_rollout()
            update_stats = self._ppo_update(data)

            stats = {
                "update": update,
                "avg_reward": float(data["rew"].mean()),
                "policy_loss": update_stats["policy_loss"],
                "value_loss": update_stats["value_loss"],
                "kl": update_stats["kl"],
                "entropy": update_stats["entropy"],
                "adv_mean": float(data["adv"].mean()),
                "duration_s": time.time() - t0,
            }
            self.history.append(stats)
            if progress_cb is not None:
                progress_cb(update, stats)
        return self.history

    # --------------------------------------------------------------- checkpoint
    def save_checkpoint(self, path: Path) -> None:
        """Save model + optimizer state via ``torch.save``."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "schema": "torch-ppo-1",
                "policy_state": self.policy.state_dict(),
                "value_state": self.value.state_dict(),
                "policy_optim_state": self.policy_optim.state_dict(),
                "value_optim_state": self.value_optim.state_dict(),
                "cfg": asdict(self.cfg),
                "obs_dim": self.env.obs_dim,
                "act_dim": self.env.action_dim,
            },
            path,
        )

    def load_checkpoint(self, path: Path) -> None:
        """Load a checkpoint produced by ``save_checkpoint``."""
        ckpt = torch.load(Path(path), map_location=self.device, weights_only=False)
        self.policy.load_state_dict(ckpt["policy_state"])
        self.value.load_state_dict(ckpt["value_state"])
        if "policy_optim_state" in ckpt:
            self.policy_optim.load_state_dict(ckpt["policy_optim_state"])
        if "value_optim_state" in ckpt:
            self.value_optim.load_state_dict(ckpt["value_optim_state"])


# --------------------------------------------------------------- CLI wrapper
def train(
    *,
    ppo_cfg: Optional[PPOConfig] = None,
    env_cfg: Optional[EnvConfig] = None,
    reward_weights: Optional[RewardWeights] = None,
    save_name: str = "ppo_ambience",
    verbose: bool = True,
    device: Optional[Union[str, torch.device]] = None,
) -> Tuple[PPOTrainer, CalibrationEnv, List[Dict[str, float]]]:
    """End-to-end run: build env + trainer, train, save checkpoint & log."""
    ensure_output_dirs()
    ppo_cfg = ppo_cfg or PPOConfig()
    env_cfg = env_cfg or EnvConfig()
    reward_weights = reward_weights or ppo_cfg.reward

    env = CalibrationEnv(env_cfg=env_cfg, reward_weights=reward_weights, seed=ppo_cfg.seed)
    trainer = PPOTrainer(env, cfg=ppo_cfg, device=device)

    def _cb(i: int, stats: Dict[str, float]) -> None:
        if verbose:
            print(
                f"[update {i:03d}] reward={stats['avg_reward']:+.4f} "
                f"pi_loss={stats['policy_loss']:+.4f} "
                f"v_loss={stats['value_loss']:.4f} "
                f"kl={stats['kl']:+.4f} H={stats['entropy']:.2f} "
                f"dt={stats['duration_s']:.2f}s"
            )

    history = trainer.train(progress_cb=_cb)

    ckpt_path = CHECKPOINT_DIR / f"{save_name}.pt"
    trainer.save_checkpoint(ckpt_path)
    log_path = CHECKPOINT_DIR / f"{save_name}.log.json"
    log_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    if verbose:
        print(f"Saved checkpoint -> {ckpt_path}")
        print(f"Saved log        -> {log_path}")
    return trainer, env, history
