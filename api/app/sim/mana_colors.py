"""Which colors a land adds in the goldfish.

Basic lands are colorless cards that add colored mana. Their color identity
is empty and they have no keyword letters, so an earlier guess that scanned
profile keywords counted every Mountain as colorless. Production comes from
the type line and name first, then from a ``produces:`` note the profile
builder writes after reading oracle text (pain lands, filter lands).
"""

from __future__ import annotations

import re

from app.rules import land_produced_colors
from app.sim.state import CardInPlay

_COLOR_TOKEN = re.compile(r"(?<![A-Za-z])([WUBRG])(?![A-Za-z])")
_PRODUCES_NOTE = re.compile(r"produces:([WUBRG]+)")


def produced_colors(land: CardInPlay) -> list[str]:
    """Colors this land adds, or ``["C"]`` when it only adds colorless."""
    notes = " ".join(land.profile.notes or [])
    oracle = " ".join(effect.text for effect in (land.profile.oracle_ast or []) if getattr(effect, "text", ""))
    colors = land_produced_colors(name=land.name, type_line=land.type_line, oracle_text=oracle)
    if colors:
        return colors
    noted = _PRODUCES_NOTE.search(notes)
    if noted:
        return list(noted.group(1))
    # Fixture profiles stamp the color as a keyword ("R") instead of a type line.
    blob = " ".join(land.profile.combo_primitives.keywords + (land.profile.notes or []))
    palette = [match.group(1) for match in _COLOR_TOKEN.finditer(blob)]
    deduped: list[str] = []
    for color in palette:
        if color not in deduped:
            deduped.append(color)
    return deduped or ["C"]
