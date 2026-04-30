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
    format: Literal["modern", "standard", "pioneer", "legacy", "commander"] = "modern"
    colors: list[str] = Field(default_factory=list)
    deck_size: int | None = None  # None = pull from format config
    budget_usd: float | None = None
    include_cards: list[str] = Field(default_factory=list)
    exclude_cards: list[str] = Field(default_factory=list)
    commander_name: str | None = None
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
        deck_size=request.deck_size,  # None → format config default
        budget_usd=request.budget_usd,
        include_cards=list(request.include_cards),
        exclude_cards=list(request.exclude_cards),
        commander_name=request.commander_name,
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

    Reads pre-built profiles from the ``card_profiles`` table when
    they exist (Phase 1 + #6 cache pipeline). Falls back to on-the-fly
    profiling for cards without a cached entry — keeps the system
    workable when the cache hasn't been built yet.
    """
    from app.oracle.profile import (
        ComboPrimitives,
        CostVector,
        EffectVector,
        PROFILE_VERSION,
        RoleWeights,
    )

    cards = repository.list_cards_for_format(fmt) if hasattr(repository, "list_cards_for_format") else []
    cached_profiles = _load_cached_profiles()  # name -> dict (may be empty)

    pool: list[tuple[CardProfile, str]] = []
    target_colors = set(colors or [])
    for card in cards:
        type_line = card.get("type_line", "") if isinstance(card, dict) else getattr(card, "type_line", "")
        record = card if isinstance(card, dict) else _card_record_to_dict(card)
        identity = set(record.get("color_identity") or [])
        if target_colors and not identity.issubset(target_colors) and identity:
            continue
        cached = cached_profiles.get(record.get("name"))
        if cached and cached.get("profile_version") == PROFILE_VERSION:
            profile = _hydrate_profile(cached)
        else:
            profile = build_card_profile(record)
        pool.append((profile, type_line))
    return pool


def _load_cached_profiles() -> dict[str, dict]:
    """Load all card profiles from the DB into an in-memory map. Returns
    an empty dict if the DB read fails — callers fall back to on-the-fly
    profiling."""
    try:
        from app.db import session_scope
        from app.db_models import CardProfile as CardProfileRow
    except Exception:
        return {}
    try:
        out: dict[str, dict] = {}
        with session_scope() as session:
            for row in session.query(CardProfileRow).all():
                out[row.name] = {
                    "card_id": row.card_id,
                    "name": row.name,
                    "profile_version": row.profile_version,
                    "parse_method": row.parse_method,
                    "parse_coverage": row.parse_coverage,
                    "cost_vector": row.cost_vector or {},
                    "effect_vector": row.effect_vector or {},
                    "role_weights": row.role_weights or {},
                    "combo_primitives": row.combo_primitives or {},
                    "oracle_ast": row.oracle_ast or [],
                    "notes": row.notes or [],
                }
        return out
    except Exception:
        return {}


def _hydrate_profile(cached: dict) -> CardProfile:
    """Reconstruct a CardProfile from a serialized DB row."""
    from app.oracle.profile import (
        Action,
        ComboPrimitives,
        CostVector,
        Effect,
        EffectVector,
        PROFILE_VERSION,
        RoleWeights,
    )

    cv_data = cached.get("cost_vector") or {}
    ev_data = cached.get("effect_vector") or {}
    rw_data = cached.get("role_weights") or {}
    cb_data = cached.get("combo_primitives") or {}
    ast_data = cached.get("oracle_ast") or []

    cost_vector = CostVector(
        generic=int(cv_data.get("generic", 0)),
        pips=dict(cv_data.get("pips") or {}),
        alt_costs=list(cv_data.get("alt_costs") or []),
        additional_costs=list(cv_data.get("additional_costs") or []),
        cmc=float(cv_data.get("cmc", 0.0)),
        pip_intensity=float(cv_data.get("pip_intensity", 0.0)),
        color_demand=dict(cv_data.get("color_demand") or {}),
    )
    effect_vector = EffectVector(**{k: v for k, v in ev_data.items() if k in EffectVector.__dataclass_fields__})
    role_weights = RoleWeights(**{k: v for k, v in rw_data.items() if k in RoleWeights.__dataclass_fields__})
    combo = ComboPrimitives(
        triggers=list(cb_data.get("triggers") or []),
        produces=list(cb_data.get("produces") or []),
        requires=list(cb_data.get("requires") or []),
        keywords=list(cb_data.get("keywords") or []),
    )
    oracle_ast: list[Effect] = []
    for eff in ast_data:
        try:
            actions = [Action(**a) for a in (eff.get("actions") or [])]
            oracle_ast.append(Effect(
                trigger=eff.get("trigger", "none"),
                cost=eff.get("cost"),
                actions=actions,
                text=eff.get("text", ""),
                conditional=bool(eff.get("conditional", False)),
            ))
        except (TypeError, KeyError):
            continue
    return CardProfile(
        card_id=cached["card_id"],
        name=cached["name"],
        cost_vector=cost_vector,
        effect_vector=effect_vector,
        role_weights=role_weights,
        combo_primitives=combo,
        oracle_ast=oracle_ast,
        profile_version=int(cached.get("profile_version", PROFILE_VERSION)),
        parse_method=cached.get("parse_method", "pattern"),
        parse_coverage=float(cached.get("parse_coverage", 1.0)),
        notes=list(cached.get("notes") or []),
    )


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
