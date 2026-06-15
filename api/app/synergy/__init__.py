"""Synergy graph + criticality scoring.

A *synergy edge* between cards A and B records that A produces a
resource or trigger B needs. Edges are derived deterministically from
:class:`CardProfile.combo_primitives` (Phase 1 output). *Criticality*
is the simulator-derived measure of how much the deck breaks if a
specific card is removed: ``criticality = ∆kill_turn`` after deletion.

This module is consumed by the optimizer (Phase 5) — swap proposals
must avoid breaking high-criticality edges, and decks that lack any
synergy clique are flagged as filler-fests.
"""

from app.synergy.builder import (
    COMBO_REGISTRY_VERSION,
    KNOWN_COMBOS,
    SynergyEdge,
    SynergyGraph,
    build_synergy_graph,
    clear_synergy_cache,
    extract_known_combos,
    reload_combo_registry,
    suggest_clique_candidates,
)
from app.synergy.criticality import compute_criticality, score_card_criticality

__all__ = [
    "COMBO_REGISTRY_VERSION",
    "KNOWN_COMBOS",
    "SynergyEdge",
    "SynergyGraph",
    "build_synergy_graph",
    "clear_synergy_cache",
    "compute_criticality",
    "extract_known_combos",
    "reload_combo_registry",
    "score_card_criticality",
    "suggest_clique_candidates",
]
