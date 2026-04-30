"""Pre-baked Modern meta archetypes for matchup simulation.

These aren't optimal lists — they're representative skeletons used as
*opponents* in matchup simulation. Each archetype defines the kind
of pressure and interaction the player must beat. The goal is
*calibration* — given a candidate deck, how does it fare against
each of the meta's pillars?

Archetypes are versioned. Updating the meta means bumping
``META_VERSION`` and re-running the matchup matrix.

Known underdogs in the current simulator:

* Tron — the simulator treats Urza lands as 1-mana basics, so the
  "2 + 1 = 7 mana" assembly is not modeled. Tron's matchup numbers
  are pessimistic by ~20-30% until the Tron-assembly rule is added.
* Living End — cascade-into-Living-End is modeled as a normal cast
  on T5 rather than a T3 cascade trigger; matchups against fast aggro
  are slightly more pessimistic than reality.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.oracle.profile import (
    CardProfile,
    ComboPrimitives,
    CostVector,
    EffectVector,
    PROFILE_VERSION,
    RoleWeights,
)

META_VERSION = "modern-2026.04"


def _profile(
    name: str,
    *,
    cmc: float = 1.0,
    pips: dict[str, int] | None = None,
    role: dict[str, float] | None = None,
    effect: dict | None = None,
    keywords: list[str] | None = None,
    closes_game: bool = False,
    is_counterspell: bool = False,
    is_tutor: bool = False,
    is_combo_payoff: bool = False,
) -> CardProfile:
    pips = pips or {}
    ev_kw = dict(effect or {})
    ev_kw.setdefault("closes_game", closes_game)
    ev_kw.setdefault("is_counterspell", is_counterspell)
    ev_kw.setdefault("is_tutor", is_tutor)
    ev_kw.setdefault("is_combo_payoff", is_combo_payoff)
    return CardProfile(
        card_id=name,
        name=name,
        cost_vector=CostVector(
            cmc=cmc, pips=dict(pips), color_demand={k: v for k, v in pips.items()}
        ),
        effect_vector=EffectVector(**ev_kw),
        role_weights=RoleWeights(**(role or {})),
        combo_primitives=ComboPrimitives(keywords=list(keywords or [])),
        oracle_ast=[],
        profile_version=PROFILE_VERSION,
        parse_method="pattern",
    )


def burn() -> list[tuple[CardProfile, str]]:
    deck: list[tuple[CardProfile, str]] = []
    bolt = _profile("Lightning Bolt (Burn)", cmc=1.0, pips={"R": 1},
                    role={"removal": 0.4, "closer": 0.6},
                    effect={"damage_dealt": 3.0, "interaction_window": "instant"})
    spike = _profile("Lava Spike (Burn)", cmc=1.0, pips={"R": 1},
                     role={"closer": 1.0}, effect={"damage_dealt": 3.0})
    goblin = _profile("Goblin Guide (Burn)", cmc=1.0, pips={"R": 1},
                      role={"threat": 0.9, "closer": 0.1},
                      effect={"board_impact": 2.5}, keywords=["haste"])
    eidolon = _profile("Eidolon (Burn)", cmc=2.0, pips={"R": 2},
                       role={"threat": 0.5, "closer": 0.5},
                       effect={"board_impact": 2.4})
    skewer = _profile("Skewer (Burn)", cmc=2.0, pips={"R": 1},
                      role={"closer": 1.0}, effect={"damage_dealt": 3.0})
    rift = _profile("Rift Bolt (Burn)", cmc=3.0, pips={"R": 1},
                    role={"closer": 1.0}, effect={"damage_dealt": 3.0})
    boros = _profile("Boros Charm (Burn)", cmc=2.0, pips={"R": 1, "W": 1},
                     role={"closer": 0.7, "protection": 0.3},
                     effect={"damage_dealt": 4.0})
    mountain = _profile("Mountain (Burn)", cmc=0.0, role={"land": 1.0},
                        effect={"interaction_window": "static"}, keywords=["R"])
    sun_canyon = _profile("Sunbaked Canyon (Burn)", cmc=0.0, role={"land": 1.0},
                          effect={"interaction_window": "static"}, keywords=["R"])
    deck.extend([(bolt, "Instant")] * 4)
    deck.extend([(spike, "Sorcery")] * 4)
    deck.extend([(goblin, "Creature — Goblin")] * 4)
    deck.extend([(eidolon, "Enchantment Creature")] * 4)
    deck.extend([(skewer, "Sorcery")] * 4)
    deck.extend([(rift, "Sorcery")] * 4)
    deck.extend([(boros, "Instant")] * 4)
    deck.extend([(mountain, "Basic Land — Mountain")] * 16)
    deck.extend([(sun_canyon, "Land")] * 4)
    return deck[:60]


def murktide() -> list[tuple[CardProfile, str]]:
    deck: list[tuple[CardProfile, str]] = []
    consider = _profile("Consider", cmc=1.0, pips={"U": 1},
                        role={"value_engine": 1.0},
                        effect={"cards_drawn": 1.0, "ca_delta": 1.0,
                                "interaction_window": "instant"})
    bolt = _profile("Lightning Bolt (UR)", cmc=1.0, pips={"R": 1},
                    role={"removal": 0.7, "closer": 0.3},
                    effect={"damage_dealt": 3.0, "interaction_window": "instant"})
    counter = _profile("Counterspell (UR)", cmc=2.0, pips={"U": 2},
                       role={"disruption": 1.0},
                       effect={"interaction_window": "instant"},
                       is_counterspell=True)
    iteration = _profile("Expressive Iteration", cmc=2.0, pips={"U": 1, "R": 1},
                         role={"value_engine": 1.0},
                         effect={"cards_drawn": 1.5, "ca_delta": 1.5})
    ragavan = _profile("Ragavan", cmc=1.0, pips={"R": 1},
                       role={"threat": 0.9},
                       effect={"board_impact": 2.0}, keywords=["haste"])
    dragon = _profile("Murktide Regent", cmc=5.0, pips={"U": 2},
                      role={"threat": 0.7, "closer": 0.3},
                      effect={"board_impact": 6.0}, keywords=["flying"],
                      closes_game=True)
    fetch = _profile("Scalding Tarn", cmc=0.0, role={"land": 1.0},
                     effect={"interaction_window": "static"}, keywords=["U", "R"])
    shock = _profile("Steam Vents", cmc=0.0, role={"land": 1.0},
                     effect={"interaction_window": "static"}, keywords=["U", "R"])
    island = _profile("Island (UR)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"}, keywords=["U"])
    mountain = _profile("Mountain (UR)", cmc=0.0, role={"land": 1.0},
                        effect={"interaction_window": "static"}, keywords=["R"])
    deck.extend([(consider, "Instant")] * 4)
    deck.extend([(bolt, "Instant")] * 4)
    deck.extend([(counter, "Instant")] * 4)
    deck.extend([(iteration, "Sorcery")] * 4)
    deck.extend([(ragavan, "Creature — Monkey")] * 4)
    deck.extend([(dragon, "Creature — Dragon")] * 4)
    deck.extend([(fetch, "Land")] * 4)
    deck.extend([(shock, "Land")] * 4)
    deck.extend([(island, "Basic Land — Island")] * 14)
    deck.extend([(mountain, "Basic Land — Mountain")] * 14)
    return deck[:60]


def tron() -> list[tuple[CardProfile, str]]:
    """Mono-G Tron skeleton — slow, bombs, heavy interaction."""
    deck: list[tuple[CardProfile, str]] = []
    expedition_map = _profile("Expedition Map", cmc=1.0,
                              role={"fixer": 1.0, "tutor": 0.5},
                              effect={"interaction_window": "permanent"},
                              is_tutor=True)
    sylvan = _profile("Sylvan Scrying", cmc=2.0, pips={"G": 1},
                      role={"tutor": 1.0},
                      effect={"interaction_window": "sorcery"},
                      is_tutor=True)
    chromatic = _profile("Chromatic Sphere", cmc=1.0,
                         role={"value_engine": 0.8, "fixer": 0.2},
                         effect={"cards_drawn": 1.0, "mana_produced": 1.0,
                                 "interaction_window": "permanent"})
    karn_lib = _profile("Karn, the Great Creator", cmc=4.0, pips={"G": 1},
                        role={"value_engine": 0.6, "disruption": 0.4})
    ulamog = _profile("Ulamog, the Ceaseless Hunger", cmc=10.0,
                      role={"closer": 1.0},
                      effect={"board_impact": 13.0,
                              "removal_scope": ["permanent"]},
                      closes_game=True)
    karn_lp = _profile("Karn Liberated", cmc=7.0,
                       role={"value_engine": 0.6, "removal": 0.4},
                       effect={"removal_scope": ["permanent"],
                               "board_impact": 5.0},
                       closes_game=True)
    wrath = _profile("Oblivion Stone", cmc=3.0,
                     role={"removal": 1.0},
                     effect={"removal_scope": ["permanent"]})
    tron1 = _profile("Urza's Tower", cmc=0.0, role={"land": 1.0},
                     effect={"interaction_window": "static"})
    tron2 = _profile("Urza's Power Plant", cmc=0.0, role={"land": 1.0},
                     effect={"interaction_window": "static"})
    tron3 = _profile("Urza's Mine", cmc=0.0, role={"land": 1.0},
                     effect={"interaction_window": "static"})
    forest = _profile("Forest (Tron)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"}, keywords=["G"])
    deck.extend([(expedition_map, "Artifact")] * 4)
    deck.extend([(sylvan, "Sorcery")] * 4)
    deck.extend([(chromatic, "Artifact")] * 4)
    deck.extend([(karn_lib, "Planeswalker")] * 4)
    deck.extend([(karn_lp, "Planeswalker")] * 3)
    deck.extend([(ulamog, "Creature — Eldrazi")] * 2)
    deck.extend([(wrath, "Artifact")] * 3)
    deck.extend([(tron1, "Land — Urza's Tower")] * 4)
    deck.extend([(tron2, "Land — Urza's Power Plant")] * 4)
    deck.extend([(tron3, "Land — Urza's Mine")] * 4)
    deck.extend([(forest, "Basic Land — Forest")] * 24)
    return deck[:60]


def living_end() -> list[tuple[CardProfile, str]]:
    """Cascade-Living End skeleton — fast combo via T3 cascade."""
    deck: list[tuple[CardProfile, str]] = []
    cascade1 = _profile("Violent Outburst", cmc=3.0, pips={"R": 1, "G": 1},
                        role={"enabler": 1.0},
                        effect={"interaction_window": "instant"})
    cascade2 = _profile("Shardless Agent", cmc=3.0, pips={"U": 1, "G": 1},
                        role={"enabler": 0.7, "threat": 0.3},
                        effect={"board_impact": 2.0,
                                "interaction_window": "permanent"})
    end = _profile("Living End", cmc=5.0, pips={"B": 2},
                   role={"closer": 1.0, "payoff": 1.0},
                   effect={"creatures_made": 4.0, "board_impact": 8.0,
                           "interaction_window": "sorcery"},
                   closes_game=True, is_combo_payoff=True)
    striped = _profile("Striped Riverwinder", cmc=6.0, pips={"U": 1},
                       role={"threat": 1.0},
                       effect={"board_impact": 5.0,
                               "interaction_window": "permanent"})
    monstrous = _profile("Monstrous Carabid", cmc=4.0, pips={"R": 1},
                         role={"threat": 1.0},
                         effect={"board_impact": 4.5,
                                 "interaction_window": "permanent"})
    architects = _profile("Architects of Will", cmc=4.0, pips={"U": 1},
                          role={"threat": 0.8, "value_engine": 0.2},
                          effect={"board_impact": 3.0,
                                  "interaction_window": "permanent"})
    forest = _profile("Forest (LE)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"}, keywords=["G"])
    swamp = _profile("Swamp (LE)", cmc=0.0, role={"land": 1.0},
                     effect={"interaction_window": "static"}, keywords=["B"])
    mountain = _profile("Mountain (LE)", cmc=0.0, role={"land": 1.0},
                        effect={"interaction_window": "static"}, keywords=["R"])
    deck.extend([(cascade1, "Instant")] * 4)
    deck.extend([(cascade2, "Creature — Human Wizard")] * 4)
    deck.extend([(end, "Sorcery")] * 4)
    deck.extend([(striped, "Creature — Serpent")] * 4)
    deck.extend([(monstrous, "Creature — Insect")] * 4)
    deck.extend([(architects, "Creature — Human Wizard")] * 4)
    deck.extend([(forest, "Basic Land — Forest")] * 8)
    deck.extend([(swamp, "Basic Land — Swamp")] * 8)
    deck.extend([(mountain, "Basic Land — Mountain")] * 8)
    return deck[:60]


META_DECKS: dict[str, list[tuple[CardProfile, str]]] = {
    "Burn": burn(),
    "Murktide (UR Tempo)": murktide(),
    "Tron": tron(),
    "Living End": living_end(),
}

# Each meta deck's native format. Used by the matchup simulator so that
# a Commander candidate vs. these Modern decks doesn't accidentally
# apply Commander mulligan rules to the opponent. Add new entries when
# expanding the meta to other formats.
META_DECK_FORMATS: dict[str, str] = {
    "Burn": "modern",
    "Murktide (UR Tempo)": "modern",
    "Tron": "modern",
    "Living End": "modern",
}
