"""Worker tasks. Each task is a thin wrapper around a domain operation
that's slow enough to push out of the request lifecycle.
"""

from __future__ import annotations

from typing import Any

from app.optimizer import (
    AnnealConfig,
    OptimizerConstraints,
    optimize_deck,
)
from app.optimizer.fitness import _aggregate_role_profile
from app.services.deck_rationale import build_deck_rationale


def optimize_deck_task(
    constraints: OptimizerConstraints,
    pool: list,
    *,
    archetype_recipes: list[dict] | None = None,
    config: AnnealConfig | None = None,
    card_prices: dict[str, float] | None = None,
    _job_progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the optimizer and return a serializable result.

    ``_job_progress`` is the in-process job's mutable progress dict.
    The optimizer doesn't currently emit progress updates, but the
    wrapper logs phase boundaries so a polling client can show them.
    """
    if _job_progress is not None:
        _job_progress["phase"] = "seeding"

    result = optimize_deck(
        constraints,
        pool,
        archetype_recipes=archetype_recipes,
        config=config,
        card_prices=card_prices,
    )

    if _job_progress is not None:
        _job_progress["phase"] = "complete"
        _job_progress["accepted_swaps"] = result.accepted_swaps
        _job_progress["rejected_swaps"] = result.rejected_swaps

    deck_payload = [
        {
            "name": p.name,
            "type_line": tl,
            "cmc": p.cost_vector.cmc,
            "color_demand": dict(p.cost_vector.color_demand),
            "role_weights": p.role_weights.to_dict(),
        }
        for p, tl in result.best.deck
    ]

    rationale = build_deck_rationale(result.best)

    return {
        "deck": deck_payload,
        "fitness": result.best.fitness.to_dict() if result.best.fitness else {},
        "score": result.best.score,
        "accepted_swaps": result.accepted_swaps,
        "rejected_swaps": result.rejected_swaps,
        "rounds": len(result.rounds_log),
        "notes": result.best.notes,
        "role_profile": _aggregate_role_profile([p for p, _ in result.best.deck]),
        "rationale": rationale.to_dict(),
    }
