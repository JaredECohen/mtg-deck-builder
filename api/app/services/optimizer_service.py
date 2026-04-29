"""Bridge between the API and the optimizer worker.

Responsibilities:
* Translate API request payloads into :class:`OptimizerConstraints`.
* Load and profile the card pool from the repository (Phase 1 profiles).
* Submit the optimizer job to the worker queue with a stable cache key.
* Return a job-id response the client can poll.
"""

from __future__ import annotations

from typing import Iterable, Literal

from pydantic import BaseModel, Field

from app.oracle import build_card_profile
from app.oracle.profile import CardProfile
from app.optimizer import AnnealConfig, OptimizerConstraints
from app.services.card_repository import CardRepository
from app.workers import optimize_deck_task
from app.workers.queue import get_job_queue, make_cache_key


class OptimizerJobRequest(BaseModel):
    format: Literal["modern"] = "modern"  # Phase 5/6 scope: Modern only.
    colors: list[str] = Field(default_factory=list)
    deck_size: int = 60
    budget_usd: float | None = None
    include_cards: list[str] = Field(default_factory=list)
    exclude_cards: list[str] = Field(default_factory=list)
    archetype_recipes: list[dict] = Field(default_factory=list)
    rounds: int = 12
    proposals_per_round: int = 4
    sim_runs_per_eval: int = 200
    seed: int = 1729


class OptimizerJobResponse(BaseModel):
    job_id: str
    status: str
    cached: bool = False
    poll_url: str


def submit_optimize_job(
    request: OptimizerJobRequest,
    *,
    repository: CardRepository,
) -> OptimizerJobResponse:
    constraints = OptimizerConstraints(
        format=request.format,
        colors=list(request.colors),
        deck_size=request.deck_size,
        budget_usd=request.budget_usd,
        include_cards=list(request.include_cards),
        exclude_cards=list(request.exclude_cards),
    )
    pool = _build_pool(repository, request.format, request.colors)
    if not pool:
        raise ValueError("optimizer pool is empty — repository has no usable cards")

    config = AnnealConfig(
        rounds=request.rounds,
        proposals_per_round=request.proposals_per_round,
        sim_runs_per_eval=request.sim_runs_per_eval,
        seed=request.seed,
    )

    cache_key = make_cache_key({
        "format": request.format,
        "colors": sorted(request.colors),
        "deck_size": request.deck_size,
        "budget": request.budget_usd,
        "includes": sorted(request.include_cards),
        "excludes": sorted(request.exclude_cards),
        "recipes": request.archetype_recipes,
        "rounds": request.rounds,
        "proposals": request.proposals_per_round,
        "sim_runs": request.sim_runs_per_eval,
        "seed": request.seed,
    })

    queue = get_job_queue()
    job = queue.submit(
        name="optimize_deck",
        fn=optimize_deck_task,
        args=(constraints, pool),
        kwargs={
            "archetype_recipes": request.archetype_recipes,
            "config": config,
        },
        cache_key=cache_key,
    )
    return OptimizerJobResponse(
        job_id=job.id,
        status=job.status,
        cached=(job.status == "cached"),
        poll_url=f"/v1/jobs/{job.id}",
    )


def _build_pool(
    repository: CardRepository,
    fmt: str,
    colors: Iterable[str],
) -> list[tuple[CardProfile, str]]:
    """Pull format-legal cards from the repository and profile them.

    Profiling is fast (~10µs/card) but for large pools we'd ideally use
    cached profiles from the ``card_profiles`` table. For now we
    profile on the fly — the cache lives in the optimizer job result.
    """
    cards = repository.list_cards_for_format(fmt) if hasattr(repository, "list_cards_for_format") else []
    pool: list[tuple[CardProfile, str]] = []
    target_colors = set(colors or [])
    for card in cards:
        type_line = card.get("type_line", "") if isinstance(card, dict) else getattr(card, "type_line", "")
        record = card if isinstance(card, dict) else _card_record_to_dict(card)
        identity = set(record.get("color_identity") or [])
        if target_colors and not identity.issubset(target_colors) and identity:
            continue
        profile = build_card_profile(record)
        pool.append((profile, type_line))
    return pool


def _card_record_to_dict(card) -> dict:
    return {
        "name": card.name,
        "mana_cost": getattr(card, "mana_cost", ""),
        "mana_value": getattr(card, "mana_value", 0),
        "type_line": getattr(card, "type_line", ""),
        "oracle_text": getattr(card, "oracle_text", ""),
        "keywords": getattr(card, "keywords", []),
        "tags": getattr(card, "tags", []),
        "color_identity": getattr(card, "color_identity", []),
        "colors": getattr(card, "colors", []),
    }
