"""Pre-baked Modern meta archetypes for matchup simulation.

These aren't optimal lists — they're representative skeletons used as
*opponents* in matchup simulation. Each archetype defines the kind
of pressure and interaction the player must beat. The goal is
*calibration* — given a candidate deck, how does it fare against
each of the meta's pillars?

Archetypes are versioned. Updating the meta means bumping
``META_VERSION`` and re-running the matchup matrix.

Known underdogs in the current simulator:

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

META_VERSION = "multi-format-2026.05"


def _profile(
    name: str,
    *,
    cmc: float = 1.0,
    pips: dict[str, int] | None = None,
    role: dict[str, float] | None = None,
    effect: dict | None = None,
    keywords: list[str] | None = None,
    notes: list[str] | None = None,
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
        notes=list(notes or []),
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


def yawgmoth() -> list[tuple[CardProfile, str]]:
    """Golgari Yawgmoth — grindy sacrifice/value engine combo-midrange."""
    deck: list[tuple[CardProfile, str]] = []
    yawg = _profile("Yawgmoth, Thran Physician", cmc=4.0, pips={"B": 1},
                    role={"value_engine": 0.6, "payoff": 0.4},
                    effect={"cards_drawn": 1.0, "ca_delta": 1.0, "board_impact": 3.0},
                    closes_game=True, is_combo_payoff=True)
    wolf = _profile("Young Wolf", cmc=1.0, pips={"G": 1},
                    role={"enabler": 0.6, "threat": 0.4},
                    effect={"board_impact": 1.4}, keywords=["undying"])
    geist = _profile("Strangleroot Geist", cmc=2.0, pips={"G": 1},
                     role={"enabler": 0.5, "threat": 0.5},
                     effect={"board_impact": 2.8}, keywords=["haste", "undying"])
    scavenger = _profile("Wall of Roots", cmc=2.0, pips={"G": 1},
                         role={"fixer": 0.7, "enabler": 0.3},
                         effect={"mana_produced": 1.0, "board_impact": 0.5},
                         keywords=["defender"])
    grist = _profile("Grist, the Hunger Tide", cmc=3.0, pips={"B": 1, "G": 1},
                     role={"value_engine": 0.6, "removal": 0.4},
                     effect={"creatures_made": 1.0, "board_impact": 2.0})
    chord = _profile("Chord of Calling", cmc=3.0, pips={"G": 3},
                     role={"tutor": 1.0}, effect={"interaction_window": "instant"},
                     is_tutor=True)
    ballista = _profile("Walking Ballista", cmc=0.0,
                        role={"removal": 0.6, "payoff": 0.4},
                        effect={"board_impact": 1.0, "damage_dealt": 1.0})
    forest = _profile("Forest (Yawg)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"}, keywords=["G"])
    swamp = _profile("Swamp (Yawg)", cmc=0.0, role={"land": 1.0},
                     effect={"interaction_window": "static"}, keywords=["B"])
    overgrown = _profile("Overgrown Tomb", cmc=0.0, role={"land": 1.0},
                         effect={"interaction_window": "static"}, keywords=["B", "G"])
    deck.extend([(yawg, "Creature — Phyrexian")] * 4)
    deck.extend([(wolf, "Creature — Wolf")] * 4)
    deck.extend([(geist, "Creature — Spirit")] * 4)
    deck.extend([(scavenger, "Creature — Plant Wall")] * 4)
    deck.extend([(grist, "Planeswalker — Grist")] * 3)
    deck.extend([(chord, "Instant")] * 3)
    deck.extend([(ballista, "Artifact Creature")] * 4)
    deck.extend([(forest, "Basic Land — Forest")] * 9)
    deck.extend([(swamp, "Basic Land — Swamp")] * 9)
    deck.extend([(overgrown, "Land")] * 6)
    return deck[:60]


def amulet_titan() -> list[tuple[CardProfile, str]]:
    """Amulet Titan — ramp combo that lands Primeval Titan fast."""
    deck: list[tuple[CardProfile, str]] = []
    amulet = _profile("Amulet of Vigor", cmc=1.0,
                      role={"enabler": 1.0},
                      effect={"mana_produced": 1.0, "interaction_window": "permanent"})
    titan = _profile("Primeval Titan", cmc=6.0, pips={"G": 2},
                     role={"payoff": 0.6, "threat": 0.4},
                     effect={"board_impact": 7.0}, keywords=["trample", "haste"],
                     closes_game=True, is_combo_payoff=True)
    azusa = _profile("Azusa, Lost but Seeking", cmc=3.0, pips={"G": 2},
                     role={"enabler": 1.0}, effect={"mana_produced": 2.0})
    explore = _profile("Explore", cmc=2.0, pips={"G": 1},
                       role={"enabler": 0.6, "value_engine": 0.4},
                       effect={"cards_drawn": 1.0, "mana_produced": 1.0})
    summons = _profile("Summoner's Pact", cmc=0.0, pips={"G": 2},
                       role={"tutor": 1.0}, is_tutor=True)
    chamber = _profile("Simic Growth Chamber", cmc=0.0, role={"land": 1.0},
                       effect={"interaction_window": "static"},
                       notes=["enters tapped"], keywords=["U", "G"])
    forest = _profile("Forest (Amulet)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"}, keywords=["G"])
    tower = _profile("Tolaria West", cmc=0.0, role={"land": 1.0},
                     effect={"interaction_window": "static"},
                     notes=["enters tapped"], keywords=["U"])
    deck.extend([(amulet, "Artifact")] * 4)
    deck.extend([(titan, "Creature — Giant")] * 4)
    deck.extend([(azusa, "Creature — Human Monk")] * 4)
    deck.extend([(explore, "Sorcery")] * 4)
    deck.extend([(summons, "Instant")] * 4)
    deck.extend([(chamber, "Land")] * 8)
    deck.extend([(tower, "Land")] * 4)
    deck.extend([(forest, "Basic Land — Forest")] * 18)
    return deck[:60]


# --- Standard meta ----------------------------------------------------


def mono_red_std() -> list[tuple[CardProfile, str]]:
    deck: list[tuple[CardProfile, str]] = []
    heartfire = _profile("Heartfire Hero", cmc=1.0, pips={"R": 1},
                         role={"threat": 0.9}, effect={"board_impact": 2.0})
    monstrous = _profile("Monstrous Rage", cmc=1.0, pips={"R": 1},
                         role={"closer": 0.6, "protection": 0.4},
                         effect={"board_impact": 2.0})
    boltwave = _profile("Boltwave", cmc=1.0, pips={"R": 1},
                        role={"removal": 0.6, "closer": 0.4},
                        effect={"damage_dealt": 2.0, "interaction_window": "instant"})
    burst = _profile("Burst Lightning", cmc=1.0, pips={"R": 1},
                     role={"removal": 0.5, "closer": 0.5},
                     effect={"damage_dealt": 2.0, "interaction_window": "instant"})
    screamer = _profile("Screaming Nemesis", cmc=3.0, pips={"R": 1},
                        role={"threat": 0.7, "closer": 0.3},
                        effect={"board_impact": 4.0}, keywords=["haste"])
    mountain = _profile("Mountain (Std-R)", cmc=0.0, role={"land": 1.0},
                        effect={"interaction_window": "static"}, keywords=["R"])
    deck.extend([(heartfire, "Creature — Kobold")] * 4)
    deck.extend([(monstrous, "Instant")] * 4)
    deck.extend([(boltwave, "Instant")] * 4)
    deck.extend([(burst, "Instant")] * 4)
    deck.extend([(screamer, "Creature — Spirit")] * 4)
    deck.extend([(mountain, "Basic Land — Mountain")] * 22)
    pad = _profile("Hired Claw", cmc=1.0, pips={"R": 1}, role={"threat": 0.8},
                   effect={"board_impact": 1.5})
    deck.extend([(pad, "Creature — Lizard")] * 14)
    return deck[:60]


def domain_ramp_std() -> list[tuple[CardProfile, str]]:
    deck: list[tuple[CardProfile, str]] = []
    bug = _profile("Up the Beanstalk", cmc=2.0, pips={"G": 1},
                   role={"value_engine": 1.0},
                   effect={"cards_drawn": 1.5, "ca_delta": 1.5})
    leyline = _profile("Leyline Binding", cmc=1.0, pips={"W": 1},
                       role={"removal": 1.0},
                       effect={"removal_scope": ["permanent"], "interaction_window": "instant"})
    herd = _profile("Herd Migration", cmc=6.0, pips={"G": 2},
                    role={"payoff": 0.6, "threat": 0.4},
                    effect={"creatures_made": 3.0, "board_impact": 6.0},
                    closes_game=True)
    overlord = _profile("Zur, Eternal Schemer", cmc=7.0, pips={"W": 1, "U": 1, "B": 1},
                        role={"payoff": 0.7, "removal": 0.3},
                        effect={"board_impact": 7.0}, closes_game=True)
    sunfall = _profile("Sunfall", cmc=5.0, pips={"W": 2},
                       role={"removal": 1.0},
                       effect={"removal_scope": ["creature"], "board_impact": 4.0,
                               "interaction_window": "sorcery"})
    triome = _profile("Triome (Domain)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"},
                      notes=["enters tapped"], keywords=["W", "U", "G"])
    plains = _profile("Plains (Domain)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"}, keywords=["W"])
    forest = _profile("Forest (Domain)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"}, keywords=["G"])
    deck.extend([(bug, "Enchantment")] * 4)
    deck.extend([(leyline, "Enchantment")] * 4)
    deck.extend([(herd, "Sorcery")] * 4)
    deck.extend([(overlord, "Creature — God")] * 3)
    deck.extend([(sunfall, "Sorcery")] * 4)
    deck.extend([(triome, "Land")] * 9)
    deck.extend([(plains, "Basic Land — Plains")] * 14)
    deck.extend([(forest, "Basic Land — Forest")] * 14)
    return deck[:60]


# --- Pioneer meta -----------------------------------------------------


def izzet_phoenix_pio() -> list[tuple[CardProfile, str]]:
    deck: list[tuple[CardProfile, str]] = []
    phoenix = _profile("Arclight Phoenix", cmc=4.0, pips={"R": 1},
                       role={"threat": 0.9, "closer": 0.1},
                       effect={"board_impact": 4.5}, keywords=["flying", "haste"])
    consider = _profile("Consider (Pio)", cmc=1.0, pips={"U": 1},
                        role={"value_engine": 1.0},
                        effect={"cards_drawn": 1.0, "ca_delta": 1.0,
                                "interaction_window": "instant"})
    picklock = _profile("Picklock Prankster", cmc=1.0, pips={"U": 1},
                        role={"value_engine": 0.8},
                        effect={"cards_drawn": 1.0, "ca_delta": 1.0})
    bolt = _profile("Lightning Axe", cmc=1.0, pips={"R": 1},
                    role={"removal": 1.0},
                    effect={"damage_dealt": 5.0, "interaction_window": "instant"})
    treasure = _profile("Treasure Cruise", cmc=8.0, pips={"U": 1},
                        role={"value_engine": 1.0},
                        effect={"cards_drawn": 3.0, "ca_delta": 3.0},
                        keywords=["delve"])
    island = _profile("Island (Pio-UR)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"}, keywords=["U"])
    mountain = _profile("Mountain (Pio-UR)", cmc=0.0, role={"land": 1.0},
                        effect={"interaction_window": "static"}, keywords=["R"])
    spirebluff = _profile("Spirebluff Canal", cmc=0.0, role={"land": 1.0},
                          effect={"interaction_window": "static"}, keywords=["U", "R"])
    deck.extend([(phoenix, "Creature — Phoenix")] * 4)
    deck.extend([(consider, "Instant")] * 4)
    deck.extend([(picklock, "Creature — Faerie")] * 4)
    deck.extend([(bolt, "Instant")] * 4)
    deck.extend([(treasure, "Sorcery")] * 4)
    deck.extend([(spirebluff, "Land")] * 4)
    deck.extend([(island, "Basic Land — Island")] * 9)
    deck.extend([(mountain, "Basic Land — Mountain")] * 8)
    pad = _profile("Crackling Drake", cmc=4.0, pips={"U": 1, "R": 1},
                   role={"threat": 0.7, "value_engine": 0.3},
                   effect={"board_impact": 3.5, "cards_drawn": 1.0}, keywords=["flying"])
    deck.extend([(pad, "Creature — Drake")] * 15)
    return deck[:60]


def mono_green_devotion_pio() -> list[tuple[CardProfile, str]]:
    deck: list[tuple[CardProfile, str]] = []
    elf = _profile("Llanowar Elves", cmc=1.0, pips={"G": 1},
                   role={"fixer": 0.8, "enabler": 0.2},
                   effect={"mana_produced": 1.0, "board_impact": 1.0})
    karn = _profile("Karn, the Great Creator", cmc=4.0, pips={"G": 1},
                    role={"value_engine": 0.6, "disruption": 0.4})
    nykthos = _profile("Nykthos, Shrine to Nyx", cmc=0.0, role={"land": 1.0},
                       effect={"mana_produced": 2.0, "interaction_window": "static"},
                       keywords=["G"])
    cavalier = _profile("Cavalier of Thorns", cmc=5.0, pips={"G": 3},
                        role={"threat": 0.7, "fixer": 0.3},
                        effect={"board_impact": 6.0})
    storm = _profile("Storm the Festival", cmc=6.0, pips={"G": 2},
                     role={"payoff": 0.6, "value_engine": 0.4},
                     effect={"board_impact": 6.0, "ca_delta": 2.0},
                     closes_game=True)
    kiora = _profile("Kiora, Behemoth Beckoner", cmc=3.0, pips={"G": 1},
                     role={"enabler": 0.7, "value_engine": 0.3},
                     effect={"mana_produced": 1.0, "cards_drawn": 0.5})
    forest = _profile("Forest (Pio-G)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"}, keywords=["G"])
    deck.extend([(elf, "Creature — Elf Druid")] * 4)
    deck.extend([(karn, "Planeswalker — Karn")] * 4)
    deck.extend([(cavalier, "Creature — Elemental")] * 4)
    deck.extend([(storm, "Sorcery")] * 4)
    deck.extend([(kiora, "Planeswalker — Kiora")] * 4)
    deck.extend([(nykthos, "Land")] * 4)
    deck.extend([(forest, "Basic Land — Forest")] * 16)
    pad = _profile("Old-Growth Troll", cmc=4.0, pips={"G": 3},
                   role={"threat": 0.8}, effect={"board_impact": 4.0}, keywords=["trample"])
    deck.extend([(pad, "Creature — Troll")] * 20)
    return deck[:60]


# --- Legacy meta ------------------------------------------------------


def rug_delver_leg() -> list[tuple[CardProfile, str]]:
    deck: list[tuple[CardProfile, str]] = []
    delver = _profile("Delver of Secrets", cmc=1.0, pips={"U": 1},
                      role={"threat": 0.9}, effect={"board_impact": 3.0},
                      keywords=["flying"])
    daze = _profile("Daze", cmc=1.0, pips={"U": 1},
                    role={"disruption": 1.0},
                    effect={"interaction_window": "instant"}, is_counterspell=True)
    force = _profile("Force of Will", cmc=5.0, pips={"U": 2},
                     role={"disruption": 1.0},
                     effect={"interaction_window": "instant"}, is_counterspell=True)
    bolt = _profile("Lightning Bolt (Legacy)", cmc=1.0, pips={"R": 1},
                    role={"removal": 0.6, "closer": 0.4},
                    effect={"damage_dealt": 3.0, "interaction_window": "instant"})
    ragavan = _profile("Ragavan (Legacy)", cmc=1.0, pips={"R": 1},
                       role={"threat": 0.9}, effect={"board_impact": 2.0}, keywords=["haste"])
    wasteland = _profile("Wasteland", cmc=0.0, role={"land": 0.7, "disruption": 0.3},
                         effect={"interaction_window": "static"})
    fetch = _profile("Wooded Foothills", cmc=0.0, role={"land": 1.0},
                     effect={"interaction_window": "static"}, keywords=["U", "R", "G"])
    island = _profile("Island (Legacy)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"}, keywords=["U"])
    ragout = _profile("Tarmogoyf", cmc=2.0, pips={"G": 1},
                      role={"threat": 0.9}, effect={"board_impact": 4.0})
    deck.extend([(delver, "Creature — Human Wizard")] * 4)
    deck.extend([(ragout, "Creature — Lhurgoyf")] * 4)
    deck.extend([(ragavan, "Creature — Monkey")] * 4)
    deck.extend([(daze, "Instant")] * 4)
    deck.extend([(force, "Instant")] * 4)
    deck.extend([(bolt, "Instant")] * 4)
    deck.extend([(wasteland, "Land")] * 4)
    deck.extend([(fetch, "Land")] * 8)
    deck.extend([(island, "Basic Land — Island")] * 8)
    pad = _profile("Brainstorm", cmc=1.0, pips={"U": 1}, role={"value_engine": 1.0},
                   effect={"cards_drawn": 3.0, "ca_delta": 1.0,
                           "interaction_window": "instant"})
    deck.extend([(pad, "Instant")] * 16)
    return deck[:60]


def reanimator_leg() -> list[tuple[CardProfile, str]]:
    deck: list[tuple[CardProfile, str]] = []
    entomb = _profile("Entomb", cmc=1.0, pips={"B": 1},
                      role={"tutor": 1.0, "enabler": 0.5},
                      effect={"interaction_window": "instant"}, is_tutor=True)
    reanimate = _profile("Reanimate", cmc=1.0, pips={"B": 1},
                         role={"payoff": 0.6, "enabler": 0.4},
                         effect={"board_impact": 8.0, "life_lost": 4.0},
                         is_combo_payoff=True)
    exhume = _profile("Exhume", cmc=2.0, pips={"B": 1},
                      role={"payoff": 0.6, "enabler": 0.4},
                      effect={"board_impact": 8.0})
    griselbrand = _profile("Griselbrand", cmc=8.0, pips={"B": 4},
                           role={"closer": 1.0},
                           effect={"board_impact": 12.0, "cards_drawn": 7.0},
                           keywords=["flying", "lifelink"], closes_game=True)
    atraxa = _profile("Atraxa, Grand Unifier", cmc=7.0, pips={"W": 1, "B": 1},
                      role={"closer": 0.7, "value_engine": 0.3},
                      effect={"board_impact": 10.0, "cards_drawn": 2.0},
                      keywords=["flying"], closes_game=True)
    dark = _profile("Dark Ritual", cmc=1.0, pips={"B": 1},
                    role={"enabler": 1.0}, effect={"mana_produced": 3.0})
    swamp = _profile("Swamp (Reanimator)", cmc=0.0, role={"land": 1.0},
                     effect={"interaction_window": "static"}, keywords=["B"])
    deck.extend([(entomb, "Instant")] * 4)
    deck.extend([(reanimate, "Sorcery")] * 4)
    deck.extend([(exhume, "Sorcery")] * 4)
    deck.extend([(dark, "Instant")] * 4)
    deck.extend([(griselbrand, "Creature — Demon")] * 3)
    deck.extend([(atraxa, "Creature — Angel")] * 3)
    deck.extend([(swamp, "Basic Land — Swamp")] * 16)
    pad = _profile("Faithless Looting", cmc=1.0, pips={"R": 1},
                   role={"enabler": 0.7, "value_engine": 0.3},
                   effect={"cards_drawn": 2.0, "interaction_window": "sorcery"})
    deck.extend([(pad, "Sorcery")] * 18)
    return deck[:60]


# --- Commander meta ---------------------------------------------------


def _commander_padding(label: str, count: int) -> list[tuple[CardProfile, str]]:
    """Generic midrange filler so Commander skeletons reach ~99 cards
    without inflating any single role."""
    out: list[tuple[CardProfile, str]] = []
    value = _profile(f"{label} Value Engine", cmc=3.0, pips={"C": 1},
                     role={"value_engine": 0.8},
                     effect={"cards_drawn": 1.0, "ca_delta": 1.0})
    threat = _profile(f"{label} Beater", cmc=4.0,
                      role={"threat": 0.8}, effect={"board_impact": 4.0})
    out.extend([(value, "Artifact")] * (count // 2))
    out.extend([(threat, "Creature — Construct")] * (count - count // 2))
    return out


def thoracle_combo_cmd() -> list[tuple[CardProfile, str]]:
    """Commander cEDH Thoracle combo skeleton."""
    deck: list[tuple[CardProfile, str]] = []
    thoracle = _profile("Thassa's Oracle", cmc=2.0, pips={"U": 2},
                        role={"payoff": 1.0}, effect={"board_impact": 1.0},
                        closes_game=True, is_combo_payoff=True)
    consult = _profile("Demonic Consultation", cmc=1.0, pips={"B": 1},
                       role={"enabler": 0.7, "tutor": 0.3},
                       effect={"interaction_window": "instant"}, is_tutor=True)
    ritual = _profile("Dark Ritual (Cmd)", cmc=1.0, pips={"B": 1},
                      role={"enabler": 1.0}, effect={"mana_produced": 3.0})
    sol = _profile("Sol Ring", cmc=1.0, role={"enabler": 1.0},
                   effect={"mana_produced": 2.0, "interaction_window": "permanent"})
    counter = _profile("Mana Drain", cmc=2.0, pips={"U": 2},
                       role={"disruption": 1.0},
                       effect={"interaction_window": "instant"}, is_counterspell=True)
    tutor = _profile("Demonic Tutor", cmc=2.0, pips={"B": 1},
                     role={"tutor": 1.0}, is_tutor=True)
    island = _profile("Island (Cmd-U)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"}, keywords=["U"])
    swamp = _profile("Swamp (Cmd-B)", cmc=0.0, role={"land": 1.0},
                     effect={"interaction_window": "static"}, keywords=["B"])
    deck.extend([(thoracle, "Creature — Merfolk")] * 1)
    deck.extend([(consult, "Instant")] * 1)
    deck.extend([(tutor, "Sorcery")] * 4)
    deck.extend([(ritual, "Instant")] * 4)
    deck.extend([(sol, "Artifact")] * 1)
    deck.extend([(counter, "Instant")] * 8)
    deck.extend([(island, "Basic Land — Island")] * 18)
    deck.extend([(swamp, "Basic Land — Swamp")] * 18)
    deck.extend(_commander_padding("Thoracle", 99 - len(deck)))
    return deck[:99]


def midrange_goodstuff_cmd() -> list[tuple[CardProfile, str]]:
    """Commander value midrange — slow, grindy, inevitability."""
    deck: list[tuple[CardProfile, str]] = []
    ramp = _profile("Cultivate (Cmd)", cmc=3.0, pips={"G": 1},
                    role={"fixer": 0.7, "value_engine": 0.3},
                    effect={"mana_produced": 1.0, "cards_drawn": 1.0})
    wrath = _profile("Damnation (Cmd)", cmc=4.0, pips={"B": 2},
                     role={"removal": 1.0},
                     effect={"removal_scope": ["creature"], "board_impact": 4.0})
    bomb = _profile("Avenger of Zendikar", cmc=7.0, pips={"G": 2},
                    role={"payoff": 0.6, "threat": 0.4},
                    effect={"creatures_made": 5.0, "board_impact": 8.0},
                    closes_game=True)
    draw = _profile("Sylvan Library", cmc=2.0, pips={"G": 1},
                    role={"value_engine": 1.0},
                    effect={"cards_drawn": 1.5, "ca_delta": 1.5})
    sol = _profile("Sol Ring (Cmd)", cmc=1.0, role={"enabler": 1.0},
                   effect={"mana_produced": 2.0, "interaction_window": "permanent"})
    forest = _profile("Forest (Cmd-G)", cmc=0.0, role={"land": 1.0},
                      effect={"interaction_window": "static"}, keywords=["G"])
    swamp = _profile("Swamp (Cmd-BG)", cmc=0.0, role={"land": 1.0},
                     effect={"interaction_window": "static"}, keywords=["B"])
    deck.extend([(ramp, "Sorcery")] * 6)
    deck.extend([(wrath, "Sorcery")] * 4)
    deck.extend([(bomb, "Creature — Elemental")] * 3)
    deck.extend([(draw, "Enchantment")] * 3)
    deck.extend([(sol, "Artifact")] * 1)
    deck.extend([(forest, "Basic Land — Forest")] * 20)
    deck.extend([(swamp, "Basic Land — Swamp")] * 18)
    deck.extend(_commander_padding("Goodstuff", 99 - len(deck)))
    return deck[:99]


# --- Format registry --------------------------------------------------

# Modern remains the canonical default set for backward compatibility.
META_DECKS: dict[str, list[tuple[CardProfile, str]]] = {
    "Burn": burn(),
    "Murktide (UR Tempo)": murktide(),
    "Tron": tron(),
    "Living End": living_end(),
}

# Per-format meta archetype sets. Each candidate deck is graded against
# the meta of *its own* format. The matchup pipeline was always
# format-aware — this is the data layer it needed.
META_BY_FORMAT: dict[str, dict[str, list[tuple[CardProfile, str]]]] = {
    "modern": {
        "Burn": burn(),
        "Murktide (UR Tempo)": murktide(),
        "Tron": tron(),
        "Living End": living_end(),
        "Yawgmoth": yawgmoth(),
        "Amulet Titan": amulet_titan(),
    },
    "standard": {
        "Mono-Red Aggro": mono_red_std(),
        "Domain Ramp": domain_ramp_std(),
    },
    "pioneer": {
        "Izzet Phoenix": izzet_phoenix_pio(),
        "Mono-Green Devotion": mono_green_devotion_pio(),
    },
    "legacy": {
        "RUG Delver": rug_delver_leg(),
        "Reanimator": reanimator_leg(),
    },
    "commander": {
        "Thoracle Combo": thoracle_combo_cmd(),
        "Midrange Goodstuff": midrange_goodstuff_cmd(),
    },
}

# Each meta deck's native format. Used by the matchup simulator so that
# a Commander candidate vs. these Modern decks doesn't accidentally
# apply Commander mulligan rules to the opponent.
META_DECK_FORMATS: dict[str, str] = {
    label: fmt
    for fmt, decks in META_BY_FORMAT.items()
    for label in decks
}


def format_meta(format_id: str) -> dict[str, list[tuple[CardProfile, str]]]:
    """Return the meta-archetype opponent set for ``format_id``.

    Falls back to the Modern meta for unknown formats so callers always
    get a believable opponent suite rather than an empty matrix.
    """
    return META_BY_FORMAT.get(format_id, META_BY_FORMAT["modern"])


def format_meta_formats(format_id: str) -> dict[str, str]:
    """label -> native format map for the given format's meta set."""
    return {label: format_id for label in format_meta(format_id)}
