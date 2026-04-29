"""Build the synergy graph from a pool of CardProfiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.oracle.profile import CardProfile


# Mapping from a card's ``produces`` token to the trigger/requirement
# tokens that pair with it. This is the canonical edge-type taxonomy.
PRODUCES_TO_REQUIRES: dict[str, set[str]] = {
    "mana_treasure": {"sacrifice_outlet", "artifact_payoff", "noncreature_payoff"},
    "mana": {"high_curve_payoff"},
    "creature_token": {"sacrifice_outlet", "creature_payoff", "go_wide_payoff"},
    "card_advantage": {"deck_thinning", "graveyard_filler"},
    "damage": {"damage_payoff"},
    "tutored_card": {},
    "graveyard_fill": {"graveyard_payoff", "delve", "escape", "flashback"},
    "untap": {"untap_payoff"},
    "extra_turn": {},
    "game_win": {},
    "free_spell": {"cast_trigger_payoff"},
}

PRODUCES_TO_TRIGGERS: dict[str, set[str]] = {
    "card_advantage": {"cast_trigger", "cast_instant_or_sorcery"},
    "damage": {"deals_damage"},
    "creature_token": {"cast_noncreature"},
    "graveyard_fill": {"dies"},
    "mana_treasure": {"cast_noncreature"},
}

# Hand-maintained registry of well-known Modern combo cliques. Each
# clique is a set of card names; if all members are present, the synergy
# graph adds high-criticality edges among them. Curated from MTG Wiki
# and tournament reports.
KNOWN_COMBOS: list[tuple[str, list[str]]] = [
    ("Splinter Twin combo", ["Splinter Twin", "Deceiver Exarch"]),
    ("Splinter Twin combo (Pestermite)", ["Splinter Twin", "Pestermite"]),
    ("Storm combo", ["Grapeshot", "Manamorphose", "Past in Flames"]),
    ("Ad Nauseam loop", ["Ad Nauseam", "Angel's Grace", "Lightning Storm"]),
    ("Devoted Druid combo", ["Devoted Druid", "Vizier of Remedies", "Walking Ballista"]),
    ("Hardened Scales combo", ["Hardened Scales", "Walking Ballista", "Arcbound Ravager"]),
    ("Goryo's Vengeance reanimator", ["Goryo's Vengeance", "Griselbrand"]),
    ("Living End cascade", ["Living End", "Violent Outburst", "Shardless Agent",
                             "Striped Riverwinder", "Curator of Mysteries"]),
    ("Thoracle line", ["Thassa's Oracle", "Demonic Consultation"]),
    ("Yawgmoth combo",
     ["Yawgmoth, Thran Physician", "Strangleroot Geist", "Young Wolf"]),
    ("Scapeshift combo", ["Scapeshift", "Valakut, the Molten Pinnacle", "Mountain"]),
    ("Amulet Titan", ["Amulet of Vigor", "Primeval Titan", "Simic Growth Chamber"]),
]


@dataclass(frozen=True)
class SynergyEdge:
    src_card: str
    dst_card: str
    edge_type: str  # "produces->requires", "trigger_match", "tutor_target", "combo_clique"
    weight: float
    evidence: str = ""


@dataclass
class SynergyGraph:
    edges: list[SynergyEdge] = field(default_factory=list)
    by_card: dict[str, list[SynergyEdge]] = field(default_factory=dict)
    cliques: list[tuple[str, list[str]]] = field(default_factory=list)

    def add(self, edge: SynergyEdge) -> None:
        self.edges.append(edge)
        self.by_card.setdefault(edge.src_card, []).append(edge)
        self.by_card.setdefault(edge.dst_card, []).append(edge)

    def edges_for(self, card: str) -> list[SynergyEdge]:
        return self.by_card.get(card, [])

    def has_complete_clique(self, names: Iterable[str]) -> bool:
        nameset = set(names)
        for label, members in self.cliques:
            if set(members).issubset(nameset):
                return True
        return False

    def total_weight(self) -> float:
        return sum(e.weight for e in self.edges)


def extract_known_combos(card_names: Iterable[str]) -> list[tuple[str, list[str]]]:
    """Return any well-known combos fully contained in the given pool."""
    pool = set(card_names)
    found: list[tuple[str, list[str]]] = []
    for label, members in KNOWN_COMBOS:
        if all(m in pool for m in members):
            found.append((label, members))
    return found


def build_synergy_graph(profiles: list[CardProfile]) -> SynergyGraph:
    graph = SynergyGraph()
    by_name: dict[str, CardProfile] = {p.name: p for p in profiles}

    # 1. produces → requires (e.g. treasure → sacrifice_outlet)
    for src in profiles:
        produced = set(src.combo_primitives.produces)
        if not produced:
            continue
        for token in produced:
            wanted_requires = PRODUCES_TO_REQUIRES.get(token, set())
            wanted_triggers = PRODUCES_TO_TRIGGERS.get(token, set())
            for dst in profiles:
                if dst.name == src.name:
                    continue
                requires = set(dst.combo_primitives.requires)
                triggers = set(dst.combo_primitives.triggers)
                req_match = requires & wanted_requires
                trig_match = triggers & wanted_triggers
                if req_match:
                    graph.add(SynergyEdge(
                        src_card=src.name,
                        dst_card=dst.name,
                        edge_type="produces->requires",
                        weight=1.0 + 0.5 * len(req_match),
                        evidence=f"{token} -> {sorted(req_match)}",
                    ))
                if trig_match:
                    graph.add(SynergyEdge(
                        src_card=src.name,
                        dst_card=dst.name,
                        edge_type="trigger_match",
                        weight=0.8 + 0.3 * len(trig_match),
                        evidence=f"{token} satisfies {sorted(trig_match)}",
                    ))

    # 2. tutors → high-impact closers (cards with closes_game = True)
    closers = [p for p in profiles if p.effect_vector.closes_game]
    for src in profiles:
        if not src.effect_vector.is_tutor:
            continue
        for closer in closers:
            graph.add(SynergyEdge(
                src_card=src.name,
                dst_card=closer.name,
                edge_type="tutor_target",
                weight=2.0,
                evidence=f"tutor → game-winning piece {closer.name}",
            ))

    # 3. known combo cliques — top weight, marks all member pairs.
    cliques = extract_known_combos(p.name for p in profiles)
    graph.cliques.extend(cliques)
    for label, members in cliques:
        for a in members:
            for b in members:
                if a >= b:
                    continue
                graph.add(SynergyEdge(
                    src_card=a,
                    dst_card=b,
                    edge_type="combo_clique",
                    weight=5.0,
                    evidence=label,
                ))

    return graph
