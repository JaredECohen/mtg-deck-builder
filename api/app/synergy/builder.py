"""Build the synergy graph from a pool of CardProfiles."""

from __future__ import annotations

import json
import logging
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Iterable

from app.oracle.profile import CardProfile

logger = logging.getLogger(__name__)


# Mapping from a card's ``produces`` token to the trigger/requirement
# tokens that pair with it. This is the canonical edge-type taxonomy.
PRODUCES_TO_REQUIRES: dict[str, set[str]] = {
    "mana_treasure": {"sacrifice_outlet", "artifact_payoff", "noncreature_payoff"},
    "mana": {"high_curve_payoff"},
    "creature_token": {"sacrifice_outlet", "creature_payoff", "go_wide_payoff"},
    "card_advantage": {"deck_thinning", "graveyard_filler"},
    "damage": {"damage_payoff"},
    # NOTE: `{}` is a dict in Python — must use `set()` for empty sets, or
    # `requires & wanted_requires` crashes with a TypeError when the token
    # is one of these. Caused every optimizer job that touched a card with
    # these primitives to fail.
    "tutored_card": set(),
    "graveyard_fill": {"graveyard_payoff", "delve", "escape", "flashback"},
    "untap": {"untap_payoff"},
    "extra_turn": set(),
    "game_win": set(),
    "free_spell": {"cast_trigger_payoff"},
}

PRODUCES_TO_TRIGGERS: dict[str, set[str]] = {
    "card_advantage": {"cast_trigger", "cast_instant_or_sorcery"},
    "damage": {"deals_damage"},
    "creature_token": {"cast_noncreature"},
    "graveyard_fill": {"dies"},
    "mana_treasure": {"cast_noncreature"},
}

# The combo registry lives in a versioned data file (combos.json) so it
# can be expanded without code changes and audited in git. These embedded
# defaults are the fallback if the file is missing or unreadable.
_FALLBACK_COMBOS: list[tuple[str, list[str]]] = [
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

_COMBOS_PATH = Path(__file__).with_name("combos.json")
COMBO_REGISTRY_VERSION = "fallback"


def _load_combo_registry() -> list[tuple[str, list[str]]]:
    """Load the combo registry from combos.json, falling back to the
    embedded defaults if the file is missing or malformed."""
    global COMBO_REGISTRY_VERSION
    try:
        raw = json.loads(_COMBOS_PATH.read_text(encoding="utf-8"))
        combos = [
            (entry["label"], list(entry["cards"]))
            for entry in raw.get("combos", [])
            if entry.get("label") and entry.get("cards")
        ]
        if combos:
            COMBO_REGISTRY_VERSION = str(raw.get("version", "unknown"))
            return combos
        logger.warning("combos.json contained no usable combos; using fallback")
    except (OSError, ValueError, KeyError, TypeError) as exc:  # noqa: BLE001
        logger.warning("failed to load combos.json (%s); using fallback registry", exc)
    return list(_FALLBACK_COMBOS)


# Loaded once at import. Each clique is a set of card names; if all
# members are present in a pool, the synergy graph adds high-criticality
# edges among them.
KNOWN_COMBOS: list[tuple[str, list[str]]] = _load_combo_registry()


def suggest_clique_candidates(
    decklists: Iterable[Iterable[str]],
    *,
    min_co_occurrence: int = 3,
    min_support: float = 0.15,
    max_candidates: int = 25,
) -> list[tuple[tuple[str, str], int, float]]:
    """Mine tournament decklists for card pairs that co-occur often but
    aren't yet in :data:`KNOWN_COMBOS` — surfacing candidate cliques to
    add to the registry.

    Returns ``[((card_a, card_b), co_occurrence_count, support), ...]``
    sorted by support (fraction of decks containing the pair) then raw
    count, descending. ``support`` filters out merely-popular staples by
    requiring the pair appear together in a meaningful share of decks.

    Lands and basic staples that appear in nearly every deck are noisy,
    so callers should pre-filter or rely on the ``min_support`` cap to
    avoid trivially-frequent pairs. This is automation to *flag* new
    cliques for human curation — it does not auto-register them.
    """
    known_pairs: set[frozenset[str]] = set()
    for _label, members in KNOWN_COMBOS:
        members = list(members)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                known_pairs.add(frozenset((members[i], members[j])))

    pair_counts: Counter[frozenset[str]] = Counter()
    deck_count = 0
    for deck in decklists:
        unique = sorted(set(deck))
        deck_count += 1
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                pair_counts[frozenset((unique[i], unique[j]))] += 1

    if deck_count == 0:
        return []

    candidates: list[tuple[tuple[str, str], int, float]] = []
    for pair, count in pair_counts.items():
        if pair in known_pairs or count < min_co_occurrence:
            continue
        support = count / deck_count
        if support < min_support:
            continue
        a, b = sorted(pair)
        candidates.append(((a, b), count, support))

    candidates.sort(key=lambda item: (item[2], item[1]), reverse=True)
    return candidates[:max_candidates]


def reload_combo_registry() -> list[tuple[str, list[str]]]:
    """Re-read combos.json at runtime (e.g. after editing). Returns the
    freshly-loaded registry and updates the module-level cache."""
    global KNOWN_COMBOS
    KNOWN_COMBOS = _load_combo_registry()
    return KNOWN_COMBOS


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


_GRAPH_CACHE: "OrderedDict[tuple, SynergyGraph]" = OrderedDict()
_GRAPH_CACHE_LOCK = RLock()
_GRAPH_CACHE_MAX = 256


def _graph_cache_key(profiles: list[CardProfile]) -> tuple:
    """Deck identity for caching = (frozenset of (name, count), max
    profile_version).

    The profile_version is included so that bumping the parser version
    invalidates cached graphs — otherwise stale graphs survive a code
    upgrade. Cards with mismatched versions in the same deck use the
    *max* version; a graph computed from heterogeneous versions is
    still consistent because the inputs are deterministic.
    """
    counts: dict[str, int] = {}
    max_version = 0
    for p in profiles:
        counts[p.name] = counts.get(p.name, 0) + 1
        if p.profile_version > max_version:
            max_version = p.profile_version
    return (frozenset(counts.items()), max_version)


def build_synergy_graph(profiles: list[CardProfile]) -> SynergyGraph:
    """Build (or retrieve from cache) the synergy graph for ``profiles``.

    The cache is global, thread-safe, and bounded. Inside the optimizer
    annealing loop the same near-identical deck gets re-evaluated
    dozens of times; without the cache, that's O(n²) graph rebuilds
    per round.
    """
    cache_key = _graph_cache_key(profiles)
    with _GRAPH_CACHE_LOCK:
        cached = _GRAPH_CACHE.get(cache_key)
        if cached is not None:
            _GRAPH_CACHE.move_to_end(cache_key)
            return cached

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

    with _GRAPH_CACHE_LOCK:
        _GRAPH_CACHE[cache_key] = graph
        if len(_GRAPH_CACHE) > _GRAPH_CACHE_MAX:
            _GRAPH_CACHE.popitem(last=False)
    return graph


def clear_synergy_cache() -> None:
    """For tests — reset the global synergy graph cache."""
    with _GRAPH_CACHE_LOCK:
        _GRAPH_CACHE.clear()
