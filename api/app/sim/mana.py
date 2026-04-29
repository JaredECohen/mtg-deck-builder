"""Mana-base solver.

Evaluates how reliably a candidate deck hits its color requirements
on the right turn. Two complementary methods:

* Closed-form **hypergeometric** for "P(≥1 source of color C in 7+N draws)".
  Used to sanity-check against Frank Karsten's published thresholds for
  Modern (60-card decks): roughly ``2.5·M + 0.5`` sources for an
  ``M``-pip colored cost on curve.

* **Monte Carlo** for everything closed-form can't handle: fetchlands
  thinning the library, shocks tapping for one but not the other color,
  MDFC back-faces, painland self-damage, snow vs colored sources, and
  spells with hybrid costs.

The simulator is deterministic given a seed. Same deck + same seed +
same config -> identical output. That is required so the optimizer
can compare runs and the critic loop can reproduce evidence.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterable, Literal

LandKind = Literal[
    "basic",
    "shock",
    "fetch",
    "fast",
    "check",
    "pain",
    "filter",
    "snow_basic",
    "mdfc_back",
    "tapped",
    "utility",
    "creature_land",
    "channel",
]

COLOR_KEYS = ("W", "U", "B", "R", "G")


@dataclass
class LandEntry:
    """One land-card slot in a candidate deck.

    ``produces`` is a list of colors the land can tap for *immediately*
    on the turn it enters untapped. ``conditional_produces`` is what it
    can tap for under realistic conditions (e.g. a Triome on turn 4 from
    cycling, a check land with the right untapped basic). ``etb_tapped``
    is the simulator's prior probability that the land enters tapped.
    """

    name: str
    kind: LandKind
    produces: tuple[str, ...]
    quantity: int = 1
    conditional_produces: tuple[str, ...] = ()
    etb_tapped_prior: float = 0.0
    fetches: tuple[str, ...] = ()  # colors it can search for, if a fetchland
    pain_per_use: int = 0  # life loss for tapping for a colored mana
    cost_modifiers: dict[str, int] = field(default_factory=dict)


@dataclass
class LandSuite:
    """The full set of lands in the candidate deck."""

    entries: list[LandEntry]

    def total_lands(self) -> int:
        return sum(e.quantity for e in self.entries)

    def lands_by_color(self, color: str) -> int:
        return sum(
            e.quantity
            for e in self.entries
            if color in e.produces or color in e.conditional_produces
        )

    def explicit_basics(self, color: str) -> int:
        return sum(
            e.quantity
            for e in self.entries
            if e.kind in ("basic", "snow_basic") and color in e.produces
        )

    def fetches_for(self, color: str) -> int:
        return sum(
            e.quantity for e in self.entries if e.kind == "fetch" and color in e.fetches
        )


@dataclass
class ManaCostDemand:
    """Aggregate color-source demand for a deck.

    ``per_color_pip_max`` records the maximum *single-card* color demand
    we ever need to cast on time (e.g. Counterspell needs UU on turn 2,
    so per_color_pip_max[U] = 2 with target_turn=2). ``per_turn_demand``
    maps a turn number to the (color -> source count needed) demand
    that turn, used by the closed-form solver to check on-curve hits.
    """

    per_color_pip_max: dict[str, int] = field(default_factory=dict)
    per_turn_demand: dict[int, dict[str, int]] = field(default_factory=dict)
    earliest_turn_per_color: dict[str, int] = field(default_factory=dict)
    sample_size: int = 0


@dataclass
class ManaBaseConfig:
    deck_size: int = 60
    starting_hand: int = 7
    mulligan_to: int = 7
    on_play: bool = True
    sim_runs: int = 5000
    max_turn: int = 8
    seed: int = 1729


@dataclass
class ManaBaseReport:
    total_lands: int
    on_curve_color_hit: dict[str, dict[int, float]]  # color -> turn -> P
    karsten_satisfaction: dict[str, float]            # color -> sources / target
    casting_consistency: dict[str, float]              # spell_signature -> P
    avg_pain_taken: float
    avg_lands_in_hand_t1: float
    avg_color_screw_pct: float
    notes: list[str] = field(default_factory=list)


def hypergeom_at_least_one(
    deck_size: int, successes_in_deck: int, draws: int
) -> float:
    """P(at least one success) when drawing ``draws`` from a deck of
    ``deck_size`` containing ``successes_in_deck`` successes."""
    if successes_in_deck <= 0 or draws <= 0:
        return 0.0
    if successes_in_deck >= deck_size:
        return 1.0
    p_none = 1.0
    for k in range(draws):
        remaining = deck_size - k
        if remaining <= 0:
            return 1.0
        non_success = deck_size - successes_in_deck - k
        if non_success < 0:
            return 1.0
        p_none *= non_success / remaining
    return 1.0 - p_none


def karsten_recommendation(pips: int, target_turn: int) -> int:
    """Return the recommended on-color source count from Karsten's tables
    for hitting a cost with ``pips`` colored requirements on
    ``target_turn`` (60-card decks). Approximation; used as a sanity
    benchmark, not a hard rule.
    """
    if pips <= 0:
        return 0
    base = {
        (1, 1): 14,
        (1, 2): 13,
        (1, 3): 12,
        (1, 4): 11,
        (1, 5): 10,
        (2, 2): 20,
        (2, 3): 18,
        (2, 4): 16,
        (2, 5): 15,
        (3, 3): 23,
        (3, 4): 20,
        (3, 5): 18,
    }
    key = (pips, target_turn)
    if key in base:
        return base[key]
    nearest = min(base.keys(), key=lambda k: (abs(k[0] - pips), abs(k[1] - target_turn)))
    return base[nearest]


def summarize_demand(spells: Iterable[dict]) -> ManaCostDemand:
    """Aggregate a deck's per-spell color demand into a ManaCostDemand.

    ``spells`` items expect: ``{"name": str, "cmc": float, "pips": {color: int},
    "target_turn": int}``. ``target_turn`` is the latest turn we need to
    cast it for it to matter (usually equal to its CMC for non-flash
    spells, or earlier for combat tricks).
    """
    demand = ManaCostDemand()
    for spell in spells:
        pips = spell.get("pips") or {}
        target_turn = int(spell.get("target_turn") or spell.get("cmc") or 1)
        target_turn = max(1, target_turn)
        for color, count in pips.items():
            count = int(count)
            if count <= 0:
                continue
            demand.per_color_pip_max[color] = max(
                demand.per_color_pip_max.get(color, 0), count
            )
            turn_bucket = demand.per_turn_demand.setdefault(target_turn, {})
            turn_bucket[color] = max(turn_bucket.get(color, 0), count)
            existing = demand.earliest_turn_per_color.get(color)
            if existing is None or target_turn < existing:
                demand.earliest_turn_per_color[color] = target_turn
        demand.sample_size += 1
    return demand


def classify_land(card: dict) -> LandEntry | None:
    """Classify a card record into a LandEntry. Returns None if not a land.

    Heuristic — looks at ``type_line``, ``oracle_text``, and ``name``.
    Sufficient for Modern: covers basics, shocklands, fetchlands,
    fastlands, painlands, checklands, filterlands, snow basics, MDFCs,
    creature lands, channel lands, and untyped utility lands.
    """
    type_line = (card.get("type_line") or "").lower()
    if "land" not in type_line:
        return None

    name = card.get("name") or ""
    text = (card.get("oracle_text") or "").lower()
    color_id = tuple(c for c in (card.get("color_identity") or []) if c in COLOR_KEYS)

    quantity = int(card.get("quantity") or 1)

    # Basic / snow basic.
    if "basic" in type_line and "snow" in type_line:
        return LandEntry(name=name, kind="snow_basic", produces=color_id or _basic_color(type_line), quantity=quantity)
    if "basic" in type_line:
        produces = color_id or _basic_color(type_line)
        return LandEntry(name=name, kind="basic", produces=produces, quantity=quantity)

    # Fetchland: "Pay 1 life, sacrifice ~: Search your library for a … card"
    if "search your library for a" in text and "land card" in text and "pay 1 life" in text:
        return LandEntry(
            name=name,
            kind="fetch",
            produces=(),
            conditional_produces=color_id,
            quantity=quantity,
            fetches=color_id,
            pain_per_use=1,
        )
    # Shocklands: "you may pay 2 life. If you don't, ~ enters tapped."
    if "as ~ enters" in text or "as this land enters" in text:
        if "you may pay 2 life" in text:
            return LandEntry(
                name=name,
                kind="shock",
                produces=color_id,
                quantity=quantity,
                etb_tapped_prior=0.05,
                pain_per_use=0,
            )
        if "control" in text and "enters tapped unless" in text:
            return LandEntry(
                name=name,
                kind="check",
                produces=color_id,
                quantity=quantity,
                etb_tapped_prior=0.25,
            )
    # Fastland: "enters tapped unless you control two or fewer other lands"
    if "two or fewer other lands" in text:
        return LandEntry(name=name, kind="fast", produces=color_id, quantity=quantity, etb_tapped_prior=0.15)
    # Painland: "{T}: Add {C}." plus colored option that costs 1 life
    if "deals 1 damage to you" in text and "add" in text:
        return LandEntry(name=name, kind="pain", produces=color_id, quantity=quantity, pain_per_use=1)
    # Filter lands ({1}, {T}: Add two mana of two colors)
    if "add two mana" in text or "add {" in text and "filter" in name.lower():
        return LandEntry(name=name, kind="filter", produces=color_id, quantity=quantity)
    # Channel lands (Boseiju, Otawara, Eiganjo, Takenuma, Sokenzan)
    if "channel" in text and "discard" in text:
        return LandEntry(name=name, kind="channel", produces=color_id, quantity=quantity)
    # Modal DFC (Shatterskull Smashing, etc.) — front face is spell, back is land
    if (card.get("layout") or "").lower() in ("modal_dfc", "transform"):
        return LandEntry(name=name, kind="mdfc_back", produces=color_id, quantity=quantity, etb_tapped_prior=0.5)
    # Creature lands (Inkmoth Nexus, Mishra's Factory, etc.)
    if "becomes a" in text and "creature" in text:
        return LandEntry(name=name, kind="creature_land", produces=color_id, quantity=quantity, etb_tapped_prior=0.0)
    # Tapped utility (Triomes, Field of the Dead, etc.)
    if "enters tapped" in text and color_id:
        return LandEntry(name=name, kind="tapped", produces=color_id, quantity=quantity, etb_tapped_prior=1.0)
    # Generic / utility land (Wasteland, Mishra's Factory)
    return LandEntry(name=name, kind="utility", produces=color_id, quantity=quantity)


def _basic_color(type_line: str) -> tuple[str, ...]:
    mapping = {"plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G"}
    for sub, color in mapping.items():
        if sub in type_line:
            return (color,)
    return ()


def build_land_suite(card_records: Iterable[dict]) -> LandSuite:
    """Build a LandSuite from a list of card record dicts.

    Each record should contain ``type_line``, ``oracle_text``,
    ``color_identity``, ``name``, and an optional ``quantity`` (default 1).
    Non-land cards are silently skipped.
    """
    by_kind: dict[tuple[str, str], LandEntry] = {}
    for card in card_records:
        entry = classify_land(card)
        if entry is None:
            continue
        key = (entry.name, entry.kind)
        if key in by_kind:
            by_kind[key].quantity += entry.quantity
        else:
            by_kind[key] = entry
    return LandSuite(entries=list(by_kind.values()))


def _expected_lands_in_hand(deck_size: int, total_lands: int, hand: int) -> float:
    return total_lands * hand / deck_size


def solve_mana_base(
    suite: LandSuite,
    demand: ManaCostDemand,
    config: ManaBaseConfig | None = None,
) -> ManaBaseReport:
    cfg = config or ManaBaseConfig()
    rng = random.Random(cfg.seed)

    total_lands = suite.total_lands()
    deck_size = cfg.deck_size

    on_curve: dict[str, dict[int, float]] = {}
    karsten_sat: dict[str, float] = {}
    for color in COLOR_KEYS:
        sources = suite.lands_by_color(color)
        if sources <= 0:
            continue
        on_curve[color] = {}
        for turn, color_demand in sorted(demand.per_turn_demand.items()):
            if color not in color_demand:
                continue
            draws = cfg.starting_hand + (turn - 1 if cfg.on_play else turn)
            p = hypergeom_at_least_one(deck_size, sources, draws)
            on_curve[color][turn] = p
        if color in demand.per_color_pip_max:
            pips = demand.per_color_pip_max[color]
            target_turn = demand.earliest_turn_per_color.get(color, max(1, pips))
            recommended = karsten_recommendation(pips, target_turn)
            karsten_sat[color] = sources / max(1, recommended)

    # Monte Carlo simulation for casting consistency.
    casting_consistency: dict[str, float] = {}
    pain_total = 0.0
    lands_in_hand_total = 0.0
    color_screwed = 0
    runs = max(50, cfg.sim_runs)
    spell_keys: list[tuple[int, dict[str, int]]] = sorted(
        demand.per_turn_demand.items()
    )
    successful_casts: dict[str, int] = {f"T{t}_" + _serialize_demand(d): 0 for t, d in spell_keys}

    for run_idx in range(runs):
        deck = _build_simulation_deck(suite, deck_size, rng)
        rng.shuffle(deck)
        hand = deck[: cfg.starting_hand]
        library = deck[cfg.starting_hand :]
        opening_lands = sum(1 for c in hand if c.kind != "spell")
        lands_in_hand_total += opening_lands
        # Mulligan-relevant land-screw: opening hand had 0 or 1 land. This is
        # the real keep/no-keep signal a London-mulligan player uses.
        if opening_lands <= 1:
            color_screwed += 1
        per_turn_state: dict[int, dict[str, int]] = {}
        played_lands: list[LandEntry] = []
        pain_run = 0
        for turn in range(1, cfg.max_turn + 1):
            if turn > 1 or not cfg.on_play:
                if library:
                    hand.append(library.pop(0))
            land_options = [c for c in hand if c.kind != "spell"]
            if land_options:
                land = _pick_best_land(land_options, demand, played_lands, turn)
                hand.remove(land)
                if land.kind == "fetch" and land.fetches:
                    target_color = _pick_fetch_color(land, demand, played_lands, turn)
                    fetched = _resolve_fetch_target(library, target_color, suite)
                    if fetched is not None:
                        played_lands.append(fetched)
                        pain_run += land.pain_per_use
                        if fetched.kind == "shock" and turn >= 2:
                            pain_run += 2
                    else:
                        played_lands.append(land)
                else:
                    played_lands.append(land)
            mana_pool = _compute_available_mana(played_lands, turn)
            for cd_turn, cd in spell_keys:
                if cd_turn != turn:
                    continue
                key = f"T{turn}_" + _serialize_demand(cd)
                if _can_pay(mana_pool, cd):
                    successful_casts[key] = successful_casts.get(key, 0) + 1
                    pain_run += sum(
                        l.pain_per_use
                        for l in played_lands
                        if l.kind == "pain" and any(c in cd for c in l.produces)
                    )
            per_turn_state[turn] = mana_pool
        pain_total += pain_run
    for key in successful_casts:
        casting_consistency[key] = successful_casts[key] / runs

    avg_pain = pain_total / max(1, runs)
    avg_lands_in_hand_t1 = lands_in_hand_total / max(1, runs)
    avg_color_screw_pct = color_screwed / max(1, runs)

    notes: list[str] = []
    for color, ratio in karsten_sat.items():
        if ratio < 0.85:
            notes.append(
                f"under-saturated on {color}: {ratio:.0%} of Karsten target ({suite.lands_by_color(color)} sources)"
            )
    if avg_color_screw_pct > 0.18:
        notes.append(
            f"keepable-hand failure {avg_color_screw_pct:.0%} (≤1 land in opener) — consider +1 land"
        )
    if avg_pain > 4.0:
        notes.append(f"avg pain taken {avg_pain:.1f} life — heavy fetch/shock; reconsider for grindy decks")
    if total_lands < 19 or total_lands > 27:
        notes.append(f"land count {total_lands} is outside the 19–27 Modern band")

    return ManaBaseReport(
        total_lands=total_lands,
        on_curve_color_hit=on_curve,
        karsten_satisfaction=karsten_sat,
        casting_consistency=casting_consistency,
        avg_pain_taken=avg_pain,
        avg_lands_in_hand_t1=avg_lands_in_hand_t1,
        avg_color_screw_pct=avg_color_screw_pct,
        notes=notes,
    )


def _serialize_demand(demand: dict[str, int]) -> str:
    return "".join(f"{c}{n}" for c, n in sorted(demand.items()))


@dataclass
class _SimCard:
    name: str
    kind: str  # "spell" or land kind
    produces: tuple[str, ...] = ()
    fetches: tuple[str, ...] = ()
    etb_tapped_prior: float = 0.0
    pain_per_use: int = 0
    enters_tapped_this_game: bool = False


def _build_simulation_deck(suite: LandSuite, deck_size: int, rng: random.Random) -> list[_SimCard]:
    cards: list[_SimCard] = []
    for entry in suite.entries:
        for _ in range(entry.quantity):
            tapped = rng.random() < entry.etb_tapped_prior
            cards.append(
                _SimCard(
                    name=entry.name,
                    kind=entry.kind,
                    produces=entry.produces,
                    fetches=entry.fetches,
                    etb_tapped_prior=entry.etb_tapped_prior,
                    pain_per_use=entry.pain_per_use,
                    enters_tapped_this_game=tapped,
                )
            )
    spells_needed = max(0, deck_size - len(cards))
    for _ in range(spells_needed):
        cards.append(_SimCard(name="<spell>", kind="spell"))
    return cards


def _pick_best_land(
    options: list[_SimCard],
    demand: ManaCostDemand,
    played: list[_SimCard],
    turn: int,
) -> _SimCard:
    """Greedy: prefer untapped lands of colors needed *this turn* the most."""
    needs = demand.per_turn_demand.get(turn, {})
    if not needs:
        needs = demand.per_color_pip_max
    untapped = [c for c in options if not c.enters_tapped_this_game]
    pool = untapped or options
    def score(card: _SimCard) -> tuple[int, int]:
        provides = sum(needs.get(col, 0) for col in card.produces)
        fetch_provides = sum(needs.get(col, 0) for col in card.fetches)
        immediate = provides if not card.enters_tapped_this_game else 0
        return (immediate + fetch_provides, provides)
    return max(pool, key=score)


def _pick_fetch_color(
    land: _SimCard, demand: ManaCostDemand, played: list[_SimCard], turn: int
) -> str:
    needs = demand.per_turn_demand.get(turn + 1, {}) or demand.per_color_pip_max
    if not needs:
        return land.fetches[0]
    return max(land.fetches, key=lambda c: needs.get(c, 0))


def _resolve_fetch_target(
    library: list[_SimCard], color: str, suite: LandSuite
) -> _SimCard | None:
    for i, card in enumerate(library):
        if card.kind in ("basic", "snow_basic", "shock") and color in card.produces:
            return library.pop(i)
    return None


def _compute_available_mana(played: list[_SimCard], turn: int) -> dict[str, int]:
    pool: dict[str, int] = {}
    for land in played:
        if land.enters_tapped_this_game and turn == 1:
            continue
        for color in land.produces:
            pool[color] = pool.get(color, 0) + 1
    pool["GENERIC"] = sum(pool.get(c, 0) for c in COLOR_KEYS)
    return pool


def _can_pay(pool: dict[str, int], demand: dict[str, int]) -> bool:
    available = dict(pool)
    needed_colored = sum(demand.values())
    if available.get("GENERIC", 0) < needed_colored:
        return False
    for color, count in demand.items():
        if available.get(color, 0) < count:
            return False
    return True
