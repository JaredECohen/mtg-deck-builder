"""Optimizer-improved generation behind ``MTG_USE_OPTIMIZER_DEFAULT=true``.

The legacy generator builds the deck first (legal, on budget, sideboard,
provenance, game plan). The simulator-driven annealer then starts from that
list as its seed recipe and tries to improve it. The improved list is kept
only when it validates, stays within budget and scores higher than the seed;
otherwise the legacy deck is returned with a note saying so.

Before 2026-10-12 this path seeded the annealer with no recipe at all, so it
filled decks from an alphabetically sorted pool ("Abandoned Sarcophagus,
Abrade, Abstergo Entertainment ...") and hard-coded ``is_legal=True``.
"""

from __future__ import annotations

import logging

from app.models import CardRef, DeckResponse, GenerateDeckRequest, ValidateDeckRequest
from app.optimizer import AnnealConfig, OptimizerConstraints, optimize_deck
from app.services.card_repository import CardRepository
from app.services.deck_generator import DeckGenerator
from app.services.deck_validator import DeckValidator
from app.services.optimizer_service import _build_pool

logger = logging.getLogger(__name__)

# Minimum fitness gain over the seed before an optimized list replaces it.
MIN_IMPROVEMENT = 0.01


def generate_via_optimizer(
    request: GenerateDeckRequest,
    *,
    repository: CardRepository,
    validator: DeckValidator,
    generator: DeckGenerator,
) -> DeckResponse:
    legacy = generator.generate(request)
    if legacy.format == "commander":
        return legacy  # the annealer's constraints are 60-card constructed

    recipe = {
        "id": "legacy-seed",
        "label": legacy.title,
        "card_quotas": {ref.name: ref.quantity for ref in legacy.mainboard},
    }
    constraints = OptimizerConstraints(
        format=legacy.format,
        colors=list(legacy.colors),
        budget_usd=request.budget,
        include_cards=list(request.include_cards),
        exclude_cards=list(request.exclude_cards),
    )
    pool = _build_pool(repository, legacy.format, legacy.colors)
    prices = {
        card.name: card.price_usd
        for name in {p.name for p, _ in pool}
        if (card := repository.get_card(name)) is not None and card.price_usd is not None
    }
    result = optimize_deck(
        constraints,
        pool,
        archetype_recipes=[recipe],
        config=AnnealConfig(rounds=8, proposals_per_round=3, sim_runs_per_eval=120, seed=1729),
        card_prices=prices,
    )
    seed_score = max((c.score for c in result.seed_results), default=0.0)

    counts: dict[str, int] = {}
    for profile, _ in result.best.deck:
        counts[profile.name] = counts.get(profile.name, 0) + 1
    optimized = [CardRef(name=name, quantity=qty) for name, qty in sorted(counts.items())]

    reason = None
    check = validator.validate(ValidateDeckRequest(
        format=legacy.format, mainboard=optimized, sideboard=legacy.sideboard,
    ))
    price = sum((prices.get(ref.name) or 0.0) * ref.quantity for ref in optimized)
    if result.best.score < seed_score + MIN_IMPROVEMENT:
        reason = "the simulator found no improvement over the generated list"
    elif not check.is_legal:
        reason = "the optimized list failed validation (" + "; ".join(check.errors[:2]) + ")"
    elif request.budget is not None and price > request.budget:
        reason = f"the optimized list costs ${price:.2f}, over the ${request.budget:.2f} budget"
    if reason:
        legacy.provenance.notes.append(f"Simulator optimization kept the generated list: {reason}.")
        return legacy

    # Rebuild through the generator with the optimized list as preserved
    # seeds, so every derived field (notes, curve, game plan, ...) matches it.
    improved = generator.generate(request.model_copy(update={
        "seed_cards": optimized,
        "preserve_mana_base": True,
    }))
    improved.provenance.notes.append(
        f"Simulator-optimized: {result.accepted_swaps} accepted swap(s), "
        f"fitness {seed_score:.2f} → {result.best.score:.2f}."
    )
    return improved
