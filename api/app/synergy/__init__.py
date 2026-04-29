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
    SynergyEdge,
    SynergyGraph,
    build_synergy_graph,
    extract_known_combos,
)
from app.synergy.criticality import compute_criticality, score_card_criticality

__all__ = [
    "SynergyEdge",
    "SynergyGraph",
    "build_synergy_graph",
    "compute_criticality",
    "extract_known_combos",
    "score_card_criticality",
]
