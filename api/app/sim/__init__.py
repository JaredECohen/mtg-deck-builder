"""MTG simulation kernel.

This package owns the deterministic, headless simulators used for
mana-consistency analysis (Phase 2), goldfish kill-turn distributions
(Phase 3), and matchup matrices (later phases). Nothing here imports
FastAPI or the database — it operates on plain dataclasses so it can
run in the optimizer worker pool.
"""
from app.sim.goldfish import GoldfishConfig, GoldfishReport, goldfish
from app.sim.mulligan import MulliganProfile, hand_quality, london_mulligan_loop
from app.sim.policy import POLICIES, select_policy
from app.sim.state import GameState, build_initial_state, card_to_in_play
from app.sim.mana import (
    LandEntry,
    LandKind,
    LandSuite,
    ManaBaseConfig,
    ManaBaseReport,
    ManaCostDemand,
    build_land_suite,
    classify_land,
    karsten_recommendation,
    solve_mana_base,
    summarize_demand,
)

__all__ = [
    "GameState",
    "GoldfishConfig",
    "GoldfishReport",
    "LandEntry",
    "LandKind",
    "LandSuite",
    "ManaBaseConfig",
    "ManaBaseReport",
    "ManaCostDemand",
    "MulliganProfile",
    "POLICIES",
    "build_initial_state",
    "build_land_suite",
    "card_to_in_play",
    "classify_land",
    "goldfish",
    "hand_quality",
    "karsten_recommendation",
    "london_mulligan_loop",
    "select_policy",
    "solve_mana_base",
    "summarize_demand",
]
