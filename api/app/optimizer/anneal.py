"""Simulated-annealing optimizer loop.

Outer-loop: iterate over seeds, keep best. Inner-loop: at each
temperature step, propose targeted swaps, evaluate fitness, accept or
reject by Metropolis criterion. Temperature decays geometrically.

The annealer never violates constraints — they're filtered before
fitness is computed.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

from app.oracle.profile import CardProfile
from app.optimizer.constraints import OptimizerConstraints, is_legal, validate_constraints
from app.optimizer.fitness import (
    FitnessVector,
    OptimizerCandidate,
    compute_fitness,
    fitness_score,
    _aggregate_role_profile,
)
from app.optimizer.seeder import Seed, seed_candidates
from app.optimizer.swap_proposals import (
    Swap,
    apply_swap,
    propose_constraint_repair_swaps,
    propose_swaps,
)


@dataclass
class AnnealConfig:
    rounds: int = 30
    proposals_per_round: int = 5
    initial_temperature: float = 0.05
    cooling: float = 0.92
    sim_runs_per_eval: int = 200
    max_turns: int = 10
    seed: int = 1729
    include_matchup: bool = False
    matchup_games: int = 40
    matchup_opponents: dict | None = None


@dataclass
class OptimizerResult:
    best: OptimizerCandidate
    seed_results: list[OptimizerCandidate] = field(default_factory=list)
    rounds_log: list[dict] = field(default_factory=list)
    rejected_swaps: int = 0
    accepted_swaps: int = 0


def optimize_deck(
    constraints: OptimizerConstraints,
    pool: list[tuple[CardProfile, str]],
    *,
    archetype_recipes: list[dict] | None = None,
    config: AnnealConfig | None = None,
    card_prices: dict[str, float] | None = None,
) -> OptimizerResult:
    cfg = config or AnnealConfig()
    rng = random.Random(cfg.seed)

    seeds = seed_candidates(constraints, pool, archetype_recipes=archetype_recipes)

    candidates: list[OptimizerCandidate] = []
    rounds_log: list[dict] = []
    accepted = 0
    rejected = 0

    for seed in seeds:
        # Soft-illegal seeds (e.g. 1 land over max_lands due to pool
        # padding) are acceptable starting points; the annealer fixes
        # them via targeted swaps. Hard violations (size mismatch,
        # off-color, missing-include) still skip the seed.
        seed_violations = validate_constraints(seed.deck, constraints, card_prices=card_prices)
        hard_codes = {"size", "missing_include", "excluded_present", "off_color"}
        if any(v.code in hard_codes for v in seed_violations):
            continue
        fv = compute_fitness(
            seed.deck,
            sim_runs=cfg.sim_runs_per_eval,
            max_turns=cfg.max_turns,
            seed=cfg.seed,
            include_matchup=cfg.include_matchup,
            matchup_games=cfg.matchup_games,
            matchup_opponents=cfg.matchup_opponents,
            format_id=constraints.format,
        )
        role_profile = _aggregate_role_profile([p for p, _ in seed.deck])
        score = fitness_score(fv, role_profile)
        current = OptimizerCandidate(deck=seed.deck, fitness=fv, score=score, notes=[seed.label])

        temperature = cfg.initial_temperature
        for round_idx in range(cfg.rounds):
            improved = False
            # Constraint-repair has priority — only useful when the
            # current deck is not yet legal. Once legal, propose
            # fitness-targeted swaps as normal.
            current_violations = validate_constraints(
                current.deck, constraints, card_prices=card_prices
            )
            if current_violations:
                swaps = propose_constraint_repair_swaps(
                    current.deck, pool, constraints,
                    locked_card_names=set(constraints.include_cards),
                    n_proposals=cfg.proposals_per_round,
                    rng=rng,
                )
                if not swaps:
                    swaps = propose_swaps(
                        current.deck, pool, current.fitness,
                        locked_card_names=set(constraints.include_cards),
                        n_proposals=cfg.proposals_per_round,
                        rng=rng,
                    )
            else:
                swaps = propose_swaps(
                    current.deck, pool, current.fitness,
                    locked_card_names=set(constraints.include_cards),
                    n_proposals=cfg.proposals_per_round,
                    rng=rng,
                )
            current_violation_count = len(current_violations)
            for swap in swaps:
                candidate_deck = apply_swap(current.deck, swap)
                cand_violations = validate_constraints(
                    candidate_deck, constraints, card_prices=card_prices
                )
                cand_violation_count = len(cand_violations)
                hard_codes = {
                    "size",
                    "missing_include",
                    "excluded_present",
                    "off_color",
                    "over_playset",
                }
                if any(v.code in hard_codes for v in cand_violations):
                    rejected += 1
                    continue
                # Strict monotonicity: never accept a candidate with
                # more violations than the current deck. Annealing can
                # still escape locally, but only via legitimate
                # constraint-respecting swaps.
                if cand_violation_count > current_violation_count:
                    rejected += 1
                    continue
                # If the candidate is fully legal AND the current deck
                # was not, accept unconditionally to escape the violation.
                # Otherwise apply the standard Metropolis criterion.
                cand_fv = compute_fitness(
                    candidate_deck,
                    sim_runs=cfg.sim_runs_per_eval,
                    max_turns=cfg.max_turns,
                    seed=cfg.seed + round_idx,
                    include_matchup=cfg.include_matchup,
                    matchup_games=cfg.matchup_games,
                    matchup_opponents=cfg.matchup_opponents,
                    format_id=constraints.format,
                )
                cand_role_profile = _aggregate_role_profile([p for p, _ in candidate_deck])
                cand_score = fitness_score(cand_fv, cand_role_profile)
                delta = cand_score - current.score
                escape_violation = (
                    cand_violation_count < current_violation_count
                    and current_violation_count > 0
                )
                if (
                    escape_violation
                    or delta > 0
                    or rng.random() < math.exp(delta / max(0.001, temperature))
                ):
                    current = OptimizerCandidate(
                        deck=candidate_deck,
                        fitness=cand_fv,
                        score=cand_score,
                        notes=current.notes + [f"swap @ r{round_idx}: {swap.rationale}"],
                    )
                    accepted += 1
                    improved = improved or delta > 0
                    break
                else:
                    rejected += 1
            rounds_log.append({
                "seed": seed.label,
                "round": round_idx,
                "score": current.score,
                "fitness": current.fitness.to_dict(),
                "temp": temperature,
            })
            temperature *= cfg.cooling
            if not improved and round_idx > 5:
                # Plateau check: if 5 consecutive rounds without
                # improvement, break and let outer loop pick best seed.
                tail = rounds_log[-5:]
                if all(abs(r["score"] - current.score) < 1e-4 for r in tail):
                    break
        candidates.append(current)

    if not candidates:
        # No legal seed survived — synthesize a best-effort single candidate.
        if seeds:
            fallback = seeds[0]
            fv = compute_fitness(
                fallback.deck,
                sim_runs=cfg.sim_runs_per_eval,
                max_turns=cfg.max_turns,
                seed=cfg.seed,
                include_matchup=cfg.include_matchup,
                matchup_games=cfg.matchup_games,
                matchup_opponents=cfg.matchup_opponents,
                format_id=constraints.format,
            )
            role = _aggregate_role_profile([p for p, _ in fallback.deck])
            candidates.append(OptimizerCandidate(deck=fallback.deck, fitness=fv,
                                                score=fitness_score(fv, role),
                                                notes=["fallback (constraint-violating seed)"]))

    best = max(candidates, key=lambda c: c.score)
    return OptimizerResult(
        best=best,
        seed_results=candidates,
        rounds_log=rounds_log,
        accepted_swaps=accepted,
        rejected_swaps=rejected,
    )
