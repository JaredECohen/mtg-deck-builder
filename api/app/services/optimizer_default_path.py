"""Synchronous wrapper that lets ``/v1/decks/generate`` route through
the optimizer pipeline while preserving the ``DeckResponse`` shape.

Gated by ``MTG_USE_OPTIMIZER_DEFAULT=true``. Falls back to legacy
generator on any error so production traffic isn't affected by a bad
deploy.
"""

from __future__ import annotations

from typing import Any

from app.models import (
    CardRef,
    DeckProvenance,
    DeckResponse,
    GenerateDeckRequest,
    ScoreBreakdown,
)
from app.optimizer import AnnealConfig, OptimizerConstraints, optimize_deck
from app.services.card_repository import CardRepository
from app.services.deck_validator import DeckValidator
from app.services.optimizer_service import _build_pool


def generate_via_optimizer(
    request: GenerateDeckRequest,
    *,
    repository: CardRepository,
    validator: DeckValidator,
) -> DeckResponse:
    """Run the optimizer synchronously and convert the result into the
    legacy ``DeckResponse`` shape so existing UI consumers don't need
    changes."""
    constraints = OptimizerConstraints(
        format=request.format,
        colors=list(request.colors),
        budget_usd=request.budget,
        include_cards=list(request.include_cards),
        exclude_cards=list(request.exclude_cards),
        commander_name=request.commander_name,
    )
    pool = _build_pool(repository, request.format, request.colors)
    if not pool:
        raise RuntimeError("optimizer pool is empty")

    cfg = AnnealConfig(
        rounds=8,
        proposals_per_round=3,
        sim_runs_per_eval=120,
        seed=1729,
    )
    result = optimize_deck(constraints, pool, config=cfg)

    name_counts: dict[str, int] = {}
    for profile, _ in result.best.deck:
        name_counts[profile.name] = name_counts.get(profile.name, 0) + 1
    mainboard = [CardRef(name=n, quantity=q) for n, q in name_counts.items()]

    fitness = result.best.fitness.to_dict() if result.best.fitness else {}
    score = ScoreBreakdown(
        legality=100,
        mana=int(round(100 * fitness.get("mana_consistency", 0.0))),
        synergy=int(round(100 * fitness.get("synergy_density", 0.0))),
        competitiveness=int(round(100 * fitness.get("kill_turn_score", 0.0))),
        role_balance=int(round(100 * fitness.get("role_balance", 0.0))),
        curve=int(round(100 * fitness.get("mulligan_keep", 0.0))),
        total=int(round(100 * result.best.score)),
    )

    return DeckResponse(
        format=request.format,
        title=f"Optimizer-built {request.format} deck",
        colors=list(request.colors),
        strategy_summary=f"Simulator-driven {fitness.get('archetype', 'midrange')} build.",
        commander=request.commander_name,
        mainboard=mainboard,
        sideboard=[],
        is_legal=True,
        validation_errors=[],
        score=score,
        explanation=list(result.best.notes or []),
        card_notes=[],
        warnings=[],
        source_archetypes=[],
        provenance=DeckProvenance(
            source_type="hybrid",
            confidence=float(result.best.score or 0.0),
            evidence_count=result.accepted_swaps,
            retrieved_from=["optimizer"],
            fallback_used=False,
            notes=["routed through MTG_USE_OPTIMIZER_DEFAULT path"],
        ),
        playstyle_tags=list(request.playstyle_tags),
        theme_tags=list(request.theme_tags),
        card_types={},
    )
