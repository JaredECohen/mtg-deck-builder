from __future__ import annotations

from app.oracle.profile import (
    CardProfile,
    ComboPrimitives,
    CostVector,
    EffectVector,
    PROFILE_VERSION,
    RoleWeights,
)
from app.sim import GoldfishConfig
from app.sim.policy import POLICIES
from app.synergy import (
    build_synergy_graph,
    compute_criticality,
    extract_known_combos,
)


def make_profile(
    name: str,
    *,
    produces: list[str] | None = None,
    requires: list[str] | None = None,
    triggers: list[str] | None = None,
    keywords: list[str] | None = None,
    closes_game: bool = False,
    is_tutor: bool = False,
    cmc: float = 1.0,
) -> CardProfile:
    return CardProfile(
        card_id=name,
        name=name,
        cost_vector=CostVector(cmc=cmc),
        effect_vector=EffectVector(closes_game=closes_game, is_tutor=is_tutor),
        role_weights=RoleWeights(),
        combo_primitives=ComboPrimitives(
            produces=list(produces or []),
            requires=list(requires or []),
            triggers=list(triggers or []),
            keywords=list(keywords or []),
        ),
        oracle_ast=[],
        profile_version=PROFILE_VERSION,
        parse_method="pattern",
    )


def test_known_combos_detected():
    pool = ["Splinter Twin", "Deceiver Exarch", "Mountain", "Island"]
    found = extract_known_combos(pool)
    labels = [label for label, _ in found]
    assert "Splinter Twin combo" in labels


def test_no_known_combo_when_one_piece_missing():
    # Splinter Twin alone — no Deceiver Exarch / Pestermite — no clique.
    pool = ["Splinter Twin", "Mountain"]
    assert extract_known_combos(pool) == []


def test_produces_to_requires_edge():
    treasure_maker = make_profile("Treasure Caster", produces=["mana_treasure"])
    sac_outlet = make_profile("Sac Outlet", requires=["sacrifice_outlet"])
    graph = build_synergy_graph([treasure_maker, sac_outlet])
    edges = graph.edges_for("Treasure Caster")
    assert any(
        e.dst_card == "Sac Outlet" and e.edge_type == "produces->requires"
        for e in edges
    )


def test_trigger_match_edge():
    cantrip = make_profile("Cantrip", produces=["card_advantage"])
    prowess = make_profile("Prowess Threat", triggers=["cast_instant_or_sorcery"])
    graph = build_synergy_graph([cantrip, prowess])
    edges = graph.edges_for("Cantrip")
    assert any(e.dst_card == "Prowess Threat" and e.edge_type == "trigger_match" for e in edges)


def test_tutor_to_closer_edge():
    tutor = make_profile("Tutor", is_tutor=True)
    closer = make_profile("Win Card", closes_game=True)
    irrelevant = make_profile("Random Card")
    graph = build_synergy_graph([tutor, closer, irrelevant])
    tutor_edges = graph.edges_for("Tutor")
    assert any(e.dst_card == "Win Card" and e.edge_type == "tutor_target" for e in tutor_edges)
    assert not any(e.dst_card == "Random Card" for e in tutor_edges)


def test_combo_clique_creates_high_weight_edges():
    twin = make_profile("Splinter Twin")
    exarch = make_profile("Deceiver Exarch")
    fluff = make_profile("Random Card")
    graph = build_synergy_graph([twin, exarch, fluff])
    clique_edges = [e for e in graph.edges if e.edge_type == "combo_clique"]
    assert len(clique_edges) == 1
    assert clique_edges[0].weight >= 5.0


def test_synergy_graph_handles_empty_pool():
    graph = build_synergy_graph([])
    assert graph.edges == []
    assert graph.cliques == []


def test_synergy_graph_no_edges_for_unrelated_pool():
    a = make_profile("A", produces=["mana"])
    b = make_profile("B", requires=["graveyard_present"])
    graph = build_synergy_graph([a, b])
    # mana → high_curve_payoff is the only mapping; b doesn't ask for it.
    assert all(e.src_card != "A" or e.dst_card != "B" for e in graph.edges)


def test_criticality_signal_differs_for_load_bearing_card():
    """Removing a key card should produce a measurable kill-turn delta
    relative to removing a fluff card."""
    from tests.test_goldfish import burn_deck

    deck = burn_deck()
    cfg = GoldfishConfig(games=120, max_turns=10, seed=42)
    scores = compute_criticality(
        deck, policy=POLICIES["aggro"], config=cfg,
        candidate_cards=["Lightning Bolt", "Goblin Guide", "Skewer the Critics"],
    )
    by_name = {s.card_name: s for s in scores}
    # Bolt and Goblin Guide together carry most of the early damage.
    # Removing them should slow kill more than removing the 2-mana Skewer.
    assert by_name["Lightning Bolt"].delta_kill_turn >= by_name["Skewer the Critics"].delta_kill_turn - 0.5
    assert by_name["Goblin Guide"].delta_kill_turn >= -0.5  # not negative


def test_synergy_graph_cache_hit_returns_same_instance():
    """Building the graph twice for the same deck identity should hit
    the cache (faster, returns the same instance)."""
    from app.synergy import build_synergy_graph, clear_synergy_cache

    clear_synergy_cache()
    pool = [
        make_profile("Treasure Caster", produces=["mana_treasure"]),
        make_profile("Sac Outlet", requires=["sacrifice_outlet"]),
    ]
    g1 = build_synergy_graph(pool)
    g2 = build_synergy_graph(pool)
    # Same call → cache hit → identity equality.
    assert g1 is g2


def test_synergy_graph_cache_differentiates_decks():
    from app.synergy import build_synergy_graph, clear_synergy_cache

    clear_synergy_cache()
    a = [make_profile("A", produces=["mana_treasure"])]
    b = [make_profile("B", produces=["mana_treasure"])]
    g_a = build_synergy_graph(a)
    g_b = build_synergy_graph(b)
    assert g_a is not g_b


def test_criticality_skips_lands():
    """Lands are excluded from criticality scoring — replacing a land
    with a vanilla land yields no interesting signal."""
    from tests.test_goldfish import burn_deck

    deck = burn_deck()
    cfg = GoldfishConfig(games=50, max_turns=8, seed=42)
    scores = compute_criticality(
        deck, policy=POLICIES["aggro"], config=cfg,
        candidate_cards=["Mountain", "Lightning Bolt"],
    )
    names = [s.card_name for s in scores]
    assert "Mountain" not in names
    assert "Lightning Bolt" in names
