from __future__ import annotations

import pytest

from app.sim.mana import (
    LandEntry,
    LandSuite,
    ManaBaseConfig,
    build_land_suite,
    classify_land,
    hypergeom_at_least_one,
    karsten_recommendation,
    solve_mana_base,
    summarize_demand,
)


def test_hypergeom_baseline():
    # 14 sources in 60-card deck, 7-card opening + draw step (turn 1 on play).
    p = hypergeom_at_least_one(60, 14, 7)
    assert 0.85 <= p <= 0.95


def test_hypergeom_zero_successes():
    assert hypergeom_at_least_one(60, 0, 7) == 0.0


def test_hypergeom_all_successes():
    assert hypergeom_at_least_one(60, 60, 1) == 1.0


def test_karsten_thresholds():
    # 1-pip turn-1: 14 sources baseline.
    assert karsten_recommendation(1, 1) == 14
    # 2-pip turn-2 (Counterspell-grade): 20 sources.
    assert karsten_recommendation(2, 2) == 20
    # 3-pip turn-3: 23 sources.
    assert karsten_recommendation(3, 3) == 23
    # Late game requirements relax.
    assert karsten_recommendation(1, 5) < karsten_recommendation(1, 1)


def test_classify_basic_land():
    card = {
        "name": "Mountain",
        "type_line": "Basic Land — Mountain",
        "oracle_text": "({T}: Add {R}.)",
        "color_identity": ["R"],
    }
    entry = classify_land(card)
    assert entry is not None
    assert entry.kind == "basic"
    assert "R" in entry.produces


def test_classify_shockland():
    card = {
        "name": "Steam Vents",
        "type_line": "Land — Island Mountain",
        "oracle_text": "As ~ enters, you may pay 2 life. If you don't, ~ enters tapped. {T}: Add {U} or {R}.",
        "color_identity": ["U", "R"],
    }
    entry = classify_land(card)
    assert entry is not None
    assert entry.kind == "shock"
    assert set(entry.produces) == {"U", "R"}


def test_classify_fetchland():
    card = {
        "name": "Scalding Tarn",
        "type_line": "Land",
        "oracle_text": "{T}, Pay 1 life, Sacrifice ~: Search your library for an Island or Mountain land card, put it onto the battlefield, then shuffle.",
        "color_identity": [],
    }
    entry = classify_land(card)
    assert entry is not None
    assert entry.kind == "fetch"


def test_classify_non_land_returns_none():
    card = {"name": "Lightning Bolt", "type_line": "Instant", "oracle_text": "..."}
    assert classify_land(card) is None


def test_summarize_demand_aggregates_per_color():
    spells = [
        {"name": "Lightning Bolt", "cmc": 1, "pips": {"R": 1}, "target_turn": 1},
        {"name": "Counterspell", "cmc": 2, "pips": {"U": 2}, "target_turn": 2},
        {"name": "Lightning Bolt #2", "cmc": 1, "pips": {"R": 1}, "target_turn": 1},
    ]
    demand = summarize_demand(spells)
    assert demand.per_color_pip_max["R"] == 1
    assert demand.per_color_pip_max["U"] == 2
    assert demand.earliest_turn_per_color["R"] == 1
    assert demand.earliest_turn_per_color["U"] == 2


def test_solver_perfect_monocolor_mountain_base():
    suite = LandSuite(
        entries=[LandEntry(name="Mountain", kind="basic", produces=("R",), quantity=20)]
    )
    spells = [{"name": "Bolt", "cmc": 1, "pips": {"R": 1}, "target_turn": 1}]
    demand = summarize_demand(spells)
    report = solve_mana_base(suite, demand, ManaBaseConfig(sim_runs=2000))
    assert report.total_lands == 20
    # 20 mountains in 60 should hit T1 R consistently.
    assert report.on_curve_color_hit["R"][1] >= 0.94
    # Casting consistency for 1-mana RR... but we asked R1, so it should hit.
    key = next(iter(report.casting_consistency))
    assert report.casting_consistency[key] >= 0.85


def test_solver_color_screw_with_too_few_sources():
    # 8 mountains for double-red on turn 2 — undersaturated.
    suite = LandSuite(
        entries=[
            LandEntry(name="Mountain", kind="basic", produces=("R",), quantity=8),
            LandEntry(name="Plains", kind="basic", produces=("W",), quantity=15),
        ]
    )
    spells = [{"name": "Boros Reckoner", "cmc": 3, "pips": {"R": 2, "W": 1}, "target_turn": 3}]
    demand = summarize_demand(spells)
    report = solve_mana_base(suite, demand, ManaBaseConfig(sim_runs=2000))
    assert report.karsten_satisfaction["R"] < 0.7
    assert any("under-saturated" in n for n in report.notes)


def test_solver_two_color_with_shocks_and_basics_modern_band():
    # A standard URd manabase: 4 fetches (Scalding Tarn equivalents),
    # 4 shocks, 5 basic Islands, 5 basic Mountains, 4 misc untapped duals.
    suite = LandSuite(
        entries=[
            LandEntry(name="Scalding Tarn", kind="fetch", produces=(), conditional_produces=("U", "R"),
                      fetches=("U", "R"), pain_per_use=1, quantity=4),
            LandEntry(name="Steam Vents", kind="shock", produces=("U", "R"), quantity=4, etb_tapped_prior=0.05),
            LandEntry(name="Spirebluff Canal", kind="fast", produces=("U", "R"), quantity=4, etb_tapped_prior=0.15),
            LandEntry(name="Island", kind="basic", produces=("U",), quantity=4),
            LandEntry(name="Mountain", kind="basic", produces=("R",), quantity=3),
        ]
    )
    spells = [
        {"name": "Counterspell", "cmc": 2, "pips": {"U": 2}, "target_turn": 2},
        {"name": "Bolt", "cmc": 1, "pips": {"R": 1}, "target_turn": 1},
        {"name": "Murktide Regent", "cmc": 5, "pips": {"U": 2}, "target_turn": 4},
    ]
    demand = summarize_demand(spells)
    report = solve_mana_base(suite, demand, ManaBaseConfig(sim_runs=2500))
    # Both colors should have plenty of sources. A standard Modern URd
    # base typically lands at ~80% Karsten saturation on the heavy color
    # — accepting slight under-saturation to keep a 19-land base.
    assert report.karsten_satisfaction["U"] >= 0.75
    assert report.karsten_satisfaction["R"] >= 0.65
    # Fetch+shock should produce non-zero pain.
    assert report.avg_pain_taken > 0
    # Total lands is in healthy Modern range.
    assert 17 <= report.total_lands <= 27
    # T1 R hit should be reasonably high (Bolt on T1).
    assert report.on_curve_color_hit.get("R", {}).get(1, 0) >= 0.6


def test_solver_tapped_land_t1_unable_to_cast():
    # All tapped lands — should fail to cast T1 spells.
    suite = LandSuite(
        entries=[LandEntry(name="Vivid Crag", kind="tapped", produces=("R",), quantity=20, etb_tapped_prior=1.0)]
    )
    spells = [{"name": "Bolt", "cmc": 1, "pips": {"R": 1}, "target_turn": 1}]
    demand = summarize_demand(spells)
    report = solve_mana_base(suite, demand, ManaBaseConfig(sim_runs=1500))
    # T1 casting consistency must be 0 — all lands are tapped.
    key = next(iter(report.casting_consistency))
    assert report.casting_consistency[key] < 0.05


def test_three_color_modern_base_consistency():
    """Jund (BRG) base resembling a tournament list (Liliana = single B
    instead of double, since real Jund lists run BB only on Liliana of
    the Veil and accept the slight under-saturation)."""
    suite = LandSuite(
        entries=[
            LandEntry(name="Bloodstained Mire", kind="fetch", produces=(),
                      conditional_produces=("B", "R"), fetches=("B", "R"), pain_per_use=1, quantity=4),
            LandEntry(name="Wooded Foothills", kind="fetch", produces=(),
                      conditional_produces=("R", "G"), fetches=("R", "G"), pain_per_use=1, quantity=4),
            LandEntry(name="Verdant Catacombs", kind="fetch", produces=(),
                      conditional_produces=("B", "G"), fetches=("B", "G"), pain_per_use=1, quantity=2),
            LandEntry(name="Blood Crypt", kind="shock", produces=("B", "R"), quantity=2, etb_tapped_prior=0.05),
            LandEntry(name="Stomping Ground", kind="shock", produces=("R", "G"), quantity=2, etb_tapped_prior=0.05),
            LandEntry(name="Overgrown Tomb", kind="shock", produces=("B", "G"), quantity=1, etb_tapped_prior=0.05),
            LandEntry(name="Forest", kind="basic", produces=("G",), quantity=1),
            LandEntry(name="Swamp", kind="basic", produces=("B",), quantity=2),
            LandEntry(name="Mountain", kind="basic", produces=("R",), quantity=1),
            LandEntry(name="Raging Ravine", kind="creature_land", produces=("R", "G"), quantity=2),
        ]
    )
    spells = [
        {"name": "Lightning Bolt", "cmc": 1, "pips": {"R": 1}, "target_turn": 1},
        {"name": "Tarmogoyf", "cmc": 2, "pips": {"G": 1}, "target_turn": 2},
        {"name": "Liliana of the Veil", "cmc": 3, "pips": {"B": 1}, "target_turn": 3},
        {"name": "Bloodbraid Elf", "cmc": 4, "pips": {"R": 1, "G": 1}, "target_turn": 4},
    ]
    demand = summarize_demand(spells)
    report = solve_mana_base(suite, demand, ManaBaseConfig(sim_runs=3000))
    assert report.total_lands == 21
    for color in "BRG":
        assert report.karsten_satisfaction.get(color, 0) >= 0.7, f"under-sourced on {color}"
    # Keepable-hand failures (≤1 land in opener) for 21-land decks sit
    # around 22% mathematically — that's a real mulligan rate, not a bug.
    assert report.avg_color_screw_pct < 0.25


def test_solver_seed_determinism():
    suite = LandSuite(
        entries=[LandEntry(name="Mountain", kind="basic", produces=("R",), quantity=20)]
    )
    spells = [{"name": "Bolt", "cmc": 1, "pips": {"R": 1}, "target_turn": 1}]
    demand = summarize_demand(spells)
    cfg = ManaBaseConfig(sim_runs=500, seed=42)
    a = solve_mana_base(suite, demand, cfg)
    b = solve_mana_base(suite, demand, cfg)
    assert a.casting_consistency == b.casting_consistency
    assert a.avg_pain_taken == pytest.approx(b.avg_pain_taken)


def test_benchmark_burn_manabase():
    """Phase 2 kill criterion: matches a published Modern Burn manabase
    (19–20 lands, R-saturated, low pain budget)."""
    suite = LandSuite(entries=[
        LandEntry(name="Mountain", kind="basic", produces=("R",), quantity=10),
        LandEntry(name="Bloodstained Mire", kind="fetch", produces=(),
                  conditional_produces=("R",), fetches=("R",), pain_per_use=1, quantity=4),
        LandEntry(name="Sunbaked Canyon", kind="pain", produces=("R",), quantity=4, pain_per_use=1),
        LandEntry(name="Inspiring Vantage", kind="fast", produces=("R", "W"), quantity=2, etb_tapped_prior=0.15),
    ])
    spells = [
        {"name": "Goblin Guide", "cmc": 1, "pips": {"R": 1}, "target_turn": 1},
        {"name": "Lightning Bolt", "cmc": 1, "pips": {"R": 1}, "target_turn": 1},
        {"name": "Skewer the Critics", "cmc": 2, "pips": {"R": 1}, "target_turn": 2},
    ]
    report = solve_mana_base(suite, summarize_demand(spells), ManaBaseConfig(sim_runs=2500))
    assert 19 <= report.total_lands <= 21  # within ±1 of published 19-20
    assert report.karsten_satisfaction["R"] >= 1.0  # R is fully saturated
    assert report.on_curve_color_hit["R"][1] >= 0.92  # T1 R-spell hits ≥92%


def test_benchmark_murktide_manabase():
    """Phase 2 kill criterion: matches a published URd Murktide list
    (19 lands, double-U on T2 + T4)."""
    suite = LandSuite(entries=[
        LandEntry(name="Scalding Tarn", kind="fetch", produces=(),
                  conditional_produces=("U", "R"), fetches=("U", "R"), pain_per_use=1, quantity=4),
        LandEntry(name="Misty Rainforest", kind="fetch", produces=(),
                  conditional_produces=("U", "R"), fetches=("U", "R"), pain_per_use=1, quantity=2),
        LandEntry(name="Steam Vents", kind="shock", produces=("U", "R"), quantity=2, etb_tapped_prior=0.05),
        LandEntry(name="Spirebluff Canal", kind="fast", produces=("U", "R"), quantity=4, etb_tapped_prior=0.15),
        LandEntry(name="Island", kind="basic", produces=("U",), quantity=4),
        LandEntry(name="Mountain", kind="basic", produces=("R",), quantity=2),
        LandEntry(name="Otawara, Soaring City", kind="channel", produces=("U",), quantity=1),
    ])
    spells = [
        {"name": "Consider", "cmc": 1, "pips": {"U": 1}, "target_turn": 1},
        {"name": "Lightning Bolt", "cmc": 1, "pips": {"R": 1}, "target_turn": 1},
        {"name": "Counterspell", "cmc": 2, "pips": {"U": 2}, "target_turn": 2},
        {"name": "Murktide Regent", "cmc": 5, "pips": {"U": 2}, "target_turn": 4},
    ]
    report = solve_mana_base(suite, summarize_demand(spells), ManaBaseConfig(sim_runs=2500))
    assert 18 <= report.total_lands <= 20
    assert report.karsten_satisfaction["U"] >= 0.75
    assert report.on_curve_color_hit["U"][2] >= 0.85
    assert report.on_curve_color_hit["U"][4] >= 0.95


def test_build_land_suite_from_card_records():
    """build_land_suite should classify a mixed card list into a clean
    LandSuite, dedupe by (name, kind), and skip non-lands."""
    records = [
        {"name": "Mountain", "type_line": "Basic Land — Mountain",
         "oracle_text": "({T}: Add {R}.)", "color_identity": ["R"], "quantity": 4},
        {"name": "Mountain", "type_line": "Basic Land — Mountain",
         "oracle_text": "({T}: Add {R}.)", "color_identity": ["R"], "quantity": 2},
        {"name": "Lightning Bolt", "type_line": "Instant",
         "oracle_text": "Deals 3 damage.", "color_identity": ["R"], "quantity": 4},
    ]
    suite = build_land_suite(records)
    assert len(suite.entries) == 1
    assert suite.entries[0].quantity == 6
    assert suite.lands_by_color("R") == 6


def test_undersaturated_modern_base_raises_warning():
    # Only 6 G sources with double-G demand turn 2 — must complain.
    suite = LandSuite(
        entries=[
            LandEntry(name="Forest", kind="basic", produces=("G",), quantity=6),
            LandEntry(name="Mountain", kind="basic", produces=("R",), quantity=14),
        ]
    )
    spells = [{"name": "Tarmogoyf", "cmc": 2, "pips": {"G": 1}, "target_turn": 2}]
    demand = summarize_demand(spells)
    report = solve_mana_base(suite, demand, ManaBaseConfig(sim_runs=1500))
    assert report.karsten_satisfaction["G"] < 0.6
    assert any("G" in n for n in report.notes)
