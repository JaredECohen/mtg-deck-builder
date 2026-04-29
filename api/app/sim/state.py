"""Game-state model for the goldfish simulator.

Solitaire by design — there is no opponent priority, no targeting
windows, no interaction. The goal is to produce a deterministic
turn-by-turn record of what *this deck* does on average, given a seed
and a policy. The simulator returns kill-turn distributions and
engine-online turns; matchup simulation comes later in :mod:`match`.

Frozen-ish: state is mutated in place by the simulator, but every
mutation is logged in :class:`GameState.history` for reproducibility
and explanation. The simulator is single-threaded; concurrency happens
at the *batch* level (many games → many cores).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.oracle.profile import CardProfile, RoleWeights


@dataclass
class CardInPlay:
    """A card currently in some zone with mutable state."""

    profile: CardProfile
    summoning_sick: bool = True
    tapped: bool = False
    counters: dict[str, int] = field(default_factory=dict)
    is_land: bool = False
    is_creature: bool = False
    is_planeswalker: bool = False
    fetched_target: str | None = None
    suspended_counters: int = 0  # for Suspend cards waiting in exile
    delay_until_turn: int = 0  # earliest turn this card becomes castable

    @property
    def name(self) -> str:
        return self.profile.name


@dataclass
class ManaPool:
    pool: dict[str, int] = field(default_factory=dict)

    def add(self, color: str, n: int = 1) -> None:
        self.pool[color] = self.pool.get(color, 0) + n

    def total(self) -> int:
        return sum(self.pool.values())

    def can_pay(self, generic: int, pips: dict[str, int]) -> bool:
        avail = dict(self.pool)
        for color, count in pips.items():
            if avail.get(color, 0) < count:
                return False
            avail[color] -= count
        if sum(avail.values()) < generic:
            return False
        return True

    def pay(self, generic: int, pips: dict[str, int]) -> bool:
        if not self.can_pay(generic, pips):
            return False
        for color, count in pips.items():
            self.pool[color] -= count
        # Spend any remaining colored sources for generic.
        remaining = generic
        for color in list(self.pool):
            if remaining <= 0:
                break
            avail = self.pool.get(color, 0)
            spend = min(avail, remaining)
            self.pool[color] -= spend
            remaining -= spend
        return True

    def empty(self) -> None:
        self.pool.clear()


@dataclass
class GameState:
    seed: int
    library: list[CardInPlay]
    hand: list[CardInPlay]
    battlefield: list[CardInPlay] = field(default_factory=list)
    graveyard: list[CardInPlay] = field(default_factory=list)
    exile: list[CardInPlay] = field(default_factory=list)
    suspended: list[CardInPlay] = field(default_factory=list)
    life: int = 20
    opp_life: int = 20
    mana: ManaPool = field(default_factory=ManaPool)
    storm_count: int = 0
    spells_cast_this_turn: int = 0
    cards_drawn_this_turn: int = 0
    turn: int = 0
    on_play: bool = True
    history: list[dict[str, Any]] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    engine_online_turn: int | None = None
    win_turn: int | None = None
    loss_turn: int | None = None
    mulligans_taken: int = 0

    def log(self, **fields: Any) -> None:
        entry = {"turn": self.turn, **fields}
        self.history.append(entry)

    def lands_in_play(self) -> list[CardInPlay]:
        return [c for c in self.battlefield if c.is_land]

    def untapped_lands(self) -> list[CardInPlay]:
        return [c for c in self.lands_in_play() if not c.tapped]

    def creatures(self) -> list[CardInPlay]:
        return [c for c in self.battlefield if c.is_creature]

    def is_game_over(self) -> bool:
        if self.opp_life <= 0:
            self.win_turn = self.win_turn or self.turn
            return True
        if self.life <= 0:
            self.loss_turn = self.loss_turn or self.turn
            return True
        if not self.library and self.cards_drawn_this_turn > 0:
            # Drawing from an empty library = loss.
            self.loss_turn = self.loss_turn or self.turn
            return True
        return False


def card_to_in_play(profile: CardProfile, *, type_line: str) -> CardInPlay:
    type_l = type_line.lower()
    return CardInPlay(
        profile=profile,
        is_land="land" in type_l,
        is_creature="creature" in type_l,
        is_planeswalker="planeswalker" in type_l,
    )


def build_initial_state(
    deck_records: Iterable[tuple[CardProfile, str]],
    *,
    seed: int = 1729,
    on_play: bool = True,
    starting_life: int = 20,
) -> GameState:
    """``deck_records`` is an iterable of (CardProfile, type_line) pairs."""
    rng = random.Random(seed)
    library = [card_to_in_play(p, type_line=tl) for p, tl in deck_records]
    rng.shuffle(library)
    state = GameState(
        seed=seed,
        library=library,
        hand=[],
        life=starting_life,
        opp_life=starting_life,
        on_play=on_play,
        rng=rng,
    )
    return state
