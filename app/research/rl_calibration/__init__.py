"""Synthetic-data PPO calibration for ambience priors.

This package builds around the production `app.services.ambience_service` fusion
logic. It never edits the shipped prior tables directly; instead, a PPO agent
learns *offsets* on top of the current (neutral-base) priors using a synthetic
ground-truth simulator.

Public entry points:
    - `build_default_params()` -> OffsetParams aligned to current priors
    - `scenario_generator.generate_scenario()` -> a single synthetic shop
    - `synthetic_world.hidden_truth()` -> hidden E/T/M for a scenario
    - `environment.CalibrationEnv` -> sequential offset-editing env
    - `ppo_train.train()` -> run PPO and checkpoint learned offsets
    - `evaluate.evaluate_params()` -> report fit / constraint / stability
    - `export_params.export()` -> write learned param JSON under outputs/
"""
from .offsets import (
    OffsetParams,
    build_default_params,
    apply_offsets,
    effective_priors_from_params,
    offsets_to_flat_vector,
    flat_vector_to_offsets,
    OFFSET_VECTOR_DIM,
)
from .types import Scenario, HiddenTruth, SimulatedText, StepResult
