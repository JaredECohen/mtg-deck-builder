"""Fitness vector + scalar combine for optimizer candidates.

The fitness function is the **only** thing the optimizer optimizes.
It must be calibrated so that a higher scalar score reliably
correlates with tournament win rate. To get there:

* Components come from real simulator outputs (mana solver + goldfish
  + synergy graph) — never hand-tuned heuristics.
* The scalar combine is a weighted geometric mean over normalized
  components, so a single catastrophic axis (e.g. land-screw) cannot
  be averaged away by a strong axis.
* Weights themselves are derived from the deck's role profile —
  aggro decks weigh kill-turn higher, control decks weigh value-density
  higher, combo decks weigh redundancy higher.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Callable

from app.oracle.profile import CardProfile
from app.sim import (
    GoldfishConfig,
    LandSuite,
    ManaBaseConfig,
    MatchConfig,
    MulliganProfile,
    build_land_suite,
    build_matchup_matrix,
    classify_land,
    goldfish,
    select_policy,
    solve_mana_base,
    summarize_demand,
)
from app.sim.policy import POLICIES
from app.synergy import build_synergy_graph


@dataclass
class FitnessVector:
    """Seven axes the optimizer sees. Higher = better, all on [0, 1].

    ``matchup_strength`` is the average win rate across the configured
    meta opponents; populated only when ``compute_fitness`` is called
    with ``include_matchup=True``. When omitted the axis defaults to
    0.5 (neutral) so the geometric-mean combine isn't penalized.
    """

    kill_turn_score: float = 0.0
    mulligan_keep: float = 0.0
    mana_consistency: float = 0.0
    synergy_density: float = 0.0
    redundancy: float = 0.0
    role_balance: float = 0.0
    matchup_strength: float = 0.5
    raw: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, float]:
        return {
            "kill_turn_score": self.kill_turn_score,
            "mulligan_keep": self.mulligan_keep,
            "mana_consistency": self.mana_consistency,
            "synergy_density": self.synergy_density,
            "redundancy": self.redundancy,
            "role_balance": self.role_balance,
            "matchup_strength": self.matchup_strength,
            **self.raw,
        }

    def worst_axis(self) -> str:
        # Only the structured axes are eligible — `raw` holds
        # diagnostic strings/floats that aren't directly optimizable.
        axes = {
            "kill_turn_score": self.kill_turn_score,
            "mulligan_keep": self.mulligan_keep,
            "mana_consistency": self.mana_consistency,
            "synergy_density": self.synergy_density,
            "redundancy": self.redundancy,
            "role_balance": self.role_balance,
            "matchup_strength": self.matchup_strength,
        }
        return min(axes, key=axes.get)


@dataclass
class OptimizerCandidate:
    deck: list[tuple[CardProfile, str]]
    fitness: FitnessVector | None = None
    score: float = 0.0
    notes: list[str] = field(default_factory=list)


def _archetype_weights(role_profile: dict[str, float]) -> dict[str, float]:
    """Pick weights for the scalar combine based on dominant role.

    Aggro decks weight kill-turn heavily. Control weights mana
    consistency + role_balance. Combo weights redundancy + synergy.
    """
    archetype = select_policy(role_profile)
    if archetype == "aggro":
        return {
            "kill_turn_score": 0.30,
            "mulligan_keep": 0.15,
            "mana_consistency": 0.10,
            "synergy_density": 0.05,
            "redundancy": 0.10,
            "role_balance": 0.10,
            "matchup_strength": 0.20,
        }
    if archetype == "combo":
        return {
            "kill_turn_score": 0.15,
            "mulligan_keep": 0.15,
            "mana_consistency": 0.10,
            "synergy_density": 0.20,
            "redundancy": 0.15,
            "role_balance": 0.05,
            "matchup_strength": 0.20,
        }
    if archetype == "control":
        return {
            "kill_turn_score": 0.05,
            "mulligan_keep": 0.15,
            "mana_consistency": 0.20,
            "synergy_density": 0.10,
            "redundancy": 0.10,
            "role_balance": 0.20,
            "matchup_strength": 0.20,
        }
    # midrange
    return {
        "kill_turn_score": 0.15,
        "mulligan_keep": 0.15,
        "mana_consistency": 0.15,
        "synergy_density": 0.10,
        "redundancy": 0.10,
        "role_balance": 0.15,
        "matchup_strength": 0.20,
    }


def _kill_turn_to_score(avg_kill_turn: float, max_turn: int) -> float:
    """Lower kill-turn = higher score, mapped to [0, 1] with diminishing
    returns for very fast kills (no need to incentivize T1 kills more
    than T3)."""
    if avg_kill_turn >= max_turn:
        return 0.0
    if avg_kill_turn <= 3.0:
        return 1.0
    return max(0.0, 1.0 - (avg_kill_turn - 3.0) / max(1.0, max_turn - 3.0))


def _mana_consistency_score(report) -> float:
    if not report.casting_consistency:
        return 0.5
    avg = statistics.mean(report.casting_consistency.values())
    return max(0.0, min(1.0, avg))


def _redundancy_score(profiles: list[CardProfile]) -> float:
    """A deck where a key role is held by 1 unique card is fragile.
    Score peaks when each role has ≥3 redundant pieces."""
    role_counts: dict[str, int] = {}
    for p in profiles:
        if not p.role_weights:
            continue
        top = max(p.role_weights.to_dict().items(), key=lambda kv: kv[1])
        if top[1] > 0.3:
            role_counts[top[0]] = role_counts.get(top[0], 0) + 1
    if not role_counts:
        return 0.5
    score = 0.0
    n = 0
    for role, count in role_counts.items():
        if role == "land":
            continue
        # Cap at 4 — Modern's playset rule. Beyond 4, redundancy is in
        # role coverage (multiple cards filling same role), not raw count.
        score += min(1.0, count / 8.0)
        n += 1
    return score / max(1, n)


def _role_balance_score(profiles: list[CardProfile]) -> float:
    """Reward decks that cover multiple roles, not single-axis stacks."""
    role_present: dict[str, float] = {}
    for p in profiles:
        for role, weight in p.role_weights.to_dict().items():
            if role == "land":
                continue
            role_present[role] = role_present.get(role, 0) + weight
    if not role_present:
        return 0.0
    # Reward at least 3 distinct roles having presence ≥ 2.
    strong_roles = sum(1 for v in role_present.values() if v >= 2)
    return min(1.0, strong_roles / 4.0)


def _synergy_density_score(profiles: list[CardProfile]) -> float:
    graph = build_synergy_graph(profiles)
    if not profiles:
        return 0.0
    edges_per_card = len(graph.edges) / max(1, len(profiles))
    base = min(1.0, edges_per_card / 6.0)
    if graph.cliques:
        base = min(1.0, base + 0.15 * len(graph.cliques))
    return base


def _aggregate_role_profile(profiles: list[CardProfile]) -> dict[str, float]:
    profile: dict[str, float] = {}
    for p in profiles:
        for role, weight in p.role_weights.to_dict().items():
            profile[role] = profile.get(role, 0) + weight
    return profile


def _build_demand_for_deck(profiles: list[CardProfile]) -> "ManaCostDemand":
    spells = []
    for p in profiles:
        if p.role_weights.land >= 0.9:
            continue
        spells.append({
            "name": p.name,
            "cmc": p.cost_vector.cmc,
            "pips": {k: v for k, v in p.cost_vector.pips.items() if k in {"W", "U", "B", "R", "G"}},
            "target_turn": max(1, int(p.cost_vector.cmc)),
        })
    return summarize_demand(spells)


def compute_fitness(
    deck: list[tuple[CardProfile, str]],
    *,
    sim_runs: int = 300,
    max_turns: int = 10,
    seed: int = 1729,
    include_matchup: bool = False,
    matchup_games: int = 50,
    matchup_opponents: dict | None = None,
    format_id: str = "modern",
) -> FitnessVector:
    profiles = [p for p, _ in deck]
    role_profile = _aggregate_role_profile(profiles)
    archetype = select_policy(role_profile)
    policy = POLICIES[archetype]

    # Format-aware life total — Commander uses 40 not 20.
    from app.optimizer.format_config import get_format_config
    fmt = get_format_config(format_id)

    # 1. Goldfish — kill turn + mulligan keep%.
    cfg = GoldfishConfig(games=sim_runs, max_turns=max_turns, seed=seed,
                         starting_life=fmt.starting_life)
    mp = _archetype_mulligan_profile(archetype, format_id=format_id)
    goldfish_report = goldfish(deck, policy=policy, mulligan_profile=mp, config=cfg)
    kt_score = _kill_turn_to_score(goldfish_report.avg_kill_turn, max_turns)
    mulligan_keep = 1.0 - min(1.0, goldfish_report.avg_mulligans / 2.0)

    # 2. Mana consistency — solver report.
    land_records = [{"name": p.name, "type_line": tl, "oracle_text": "",
                     "color_identity": list(p.cost_vector.color_demand.keys())} for p, tl in deck if "land" in tl.lower()]
    suite = build_land_suite(land_records)
    if suite.total_lands() == 0:
        suite = LandSuite(entries=[])
    demand = _build_demand_for_deck(profiles)
    if suite.total_lands() and demand.per_turn_demand:
        # Commander draws 7 from 100 — different deck size changes the
        # hypergeometric on-curve probabilities. Pass format size so the
        # solver's hand calculations are accurate.
        mana_cfg = ManaBaseConfig(
            deck_size=fmt.deck_size if fmt.deck_size >= 60 else 60,
            sim_runs=600,
            seed=seed,
        )
        mana_report = solve_mana_base(suite, demand, mana_cfg)
        mc_score = _mana_consistency_score(mana_report)
    else:
        mc_score = 0.5

    # 3. Synergy density.
    syn_score = _synergy_density_score(profiles)
    # 4. Redundancy.
    red_score = _redundancy_score(profiles)
    # 5. Role balance.
    rb_score = _role_balance_score(profiles)

    # 6. Matchup strength — gated since it's expensive (100ms-1s).
    matchup_score = 0.5  # neutral default when not computed
    matchup_data: dict[str, float] = {}
    if include_matchup:
        matchup_cfg = MatchConfig(games=matchup_games, max_turns=max_turns, seed=seed,
                                  starting_life=fmt.starting_life)
        matrix = build_matchup_matrix(deck, opponents=matchup_opponents, config=matchup_cfg)
        matchup_score = matrix.avg_winrate or 0.0
        matchup_data = matrix.by_opponent

    fv = FitnessVector(
        kill_turn_score=kt_score,
        mulligan_keep=mulligan_keep,
        mana_consistency=mc_score,
        synergy_density=syn_score,
        redundancy=red_score,
        role_balance=rb_score,
        matchup_strength=matchup_score,
        raw={
            "avg_kill_turn": goldfish_report.avg_kill_turn,
            "win_rate": goldfish_report.wins / max(1, goldfish_report.games_played),
            "archetype": archetype,
            "matchup_matrix": matchup_data,
        },
    )
    return fv


def fitness_score(fv: FitnessVector, role_profile: dict[str, float]) -> float:
    weights = _archetype_weights(role_profile)
    components = fv.to_dict()
    # Weighted geometric mean — guards against single catastrophic axis.
    total_weight = 0.0
    log_acc = 0.0
    for axis, w in weights.items():
        v = max(0.001, components.get(axis, 0.0))
        log_acc += w * math.log(v)
        total_weight += w
    return math.exp(log_acc / max(0.0001, total_weight))


def _archetype_mulligan_profile(
    archetype: str, format_id: str = "modern"
) -> MulliganProfile:
    """Build a mulligan profile from archetype + format defaults.

    Format influences the *floor* — Commander wants 3-5 lands no
    matter what archetype it is, while aggro Modern can keep 2.
    """
    from app.optimizer.format_config import get_format_config
    fmt = get_format_config(format_id)
    fmt_lo, fmt_hi = fmt.mulligan_ideal_lands
    fmt_action_turn = fmt.needs_action_by_turn

    if archetype == "aggro":
        lo, hi, turn = 2, 4, 2
    elif archetype == "combo":
        lo, hi, turn = 2, 5, 4
    elif archetype == "control":
        lo, hi, turn = 3, 5, 4
    else:
        lo, hi, turn = 2, 5, 3
    # Format floors override archetype defaults when stricter.
    return MulliganProfile(
        ideal_lands=(max(lo, fmt_lo), max(hi, fmt_hi)),
        needs_action_by_turn=max(turn, fmt_action_turn),
    )
