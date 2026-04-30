"""Per-format configuration for the optimizer.

Each format encodes the rule deltas the optimizer / simulator pipeline
needs to know about beyond what the card legality field already
provides:

* deck size + sideboard size
* singleton rule (Commander only)
* starting life
* recommended land range
* mulligan ideal-land range
* meta-archetype set used for the matchup matrix
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

FormatId = Literal["modern", "standard", "pioneer", "legacy", "commander"]


@dataclass(frozen=True)
class FormatConfig:
    name: FormatId
    deck_size: int
    sideboard_size: int
    singleton: bool
    starting_life: int
    min_lands: int
    max_lands: int
    mulligan_ideal_lands: tuple[int, int]
    needs_action_by_turn: int
    has_commander: bool = False
    extra_rules: tuple[str, ...] = field(default_factory=tuple)


FORMATS: dict[FormatId, FormatConfig] = {
    "modern": FormatConfig(
        name="modern",
        deck_size=60,
        sideboard_size=15,
        singleton=False,
        starting_life=20,
        min_lands=18,
        max_lands=27,
        mulligan_ideal_lands=(2, 5),
        needs_action_by_turn=3,
    ),
    "standard": FormatConfig(
        name="standard",
        deck_size=60,
        sideboard_size=15,
        singleton=False,
        starting_life=20,
        min_lands=22,
        max_lands=27,
        mulligan_ideal_lands=(3, 5),
        needs_action_by_turn=3,
    ),
    "pioneer": FormatConfig(
        name="pioneer",
        deck_size=60,
        sideboard_size=15,
        singleton=False,
        starting_life=20,
        min_lands=20,
        max_lands=27,
        mulligan_ideal_lands=(2, 5),
        needs_action_by_turn=3,
    ),
    "legacy": FormatConfig(
        name="legacy",
        deck_size=60,
        sideboard_size=15,
        singleton=False,
        starting_life=20,
        min_lands=16,
        max_lands=24,
        mulligan_ideal_lands=(2, 5),
        needs_action_by_turn=2,
    ),
    "commander": FormatConfig(
        name="commander",
        deck_size=99,  # 99 in mainboard + 1 commander
        sideboard_size=0,
        singleton=True,
        starting_life=40,
        min_lands=35,
        max_lands=42,
        mulligan_ideal_lands=(3, 5),
        needs_action_by_turn=4,
        has_commander=True,
        extra_rules=("color_identity_from_commander",),
    ),
}


def get_format_config(name: str) -> FormatConfig:
    if name not in FORMATS:
        raise ValueError(f"unsupported format: {name!r} (known: {sorted(FORMATS)})")
    return FORMATS[name]
