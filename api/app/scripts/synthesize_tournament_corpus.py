"""Generate a curated tournament-deck corpus from BUILTIN_ARCHETYPES.

The shipped sample corpus has 11 entries — all RU Spells / W Lifegain
variants — which is why every fallback path picks "W Lifegain Payoff" for
arbitrary requests and the Format Meta Snapshot is dominated by 2 archetypes.

This script turns each builtin archetype into ONE tournament_deck record
(source "synthesized-from-builtin"). These are templates, not observed
results: build_archetypes marks archetypes built only from them as
evidence="template" and the API labels them that way. (Until 2026-10-12 it
wrote two near-identical variants per archetype, which showed up as "2
evidence decks" for what was one curated list.)

Lists are padded to deck size with basics split across the archetype's
colors. Commander records get a 37-land mana base and are otherwise left at
the anchor list's size — padding the nonland slots with ~60 copies of one
basic (as before) produced "Mountain 100% • 70 avg" land packages.

After running this, run:
    python -m app.scripts.ingest_tournament_decks
    python -m app.scripts.build_archetypes
to reload the corpus. The Format Meta Snapshot will then reflect the
canon metagame and the corpus fallback path will produce sensible decks
even when no builtin matches.

Idempotent — re-running overwrites the curated file.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.builtin_archetypes import BUILTIN_ARCHETYPES


OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "tournament_decks.curated.json"

# Per-format target deck size for the synthesized records. Commander uses 99
# in the mainboard; everything else uses 60.
DECK_SIZE = {"commander": 99, "standard": 60, "modern": 60, "pioneer": 60, "legacy": 60}
SIDEBOARD_SIZE = {"commander": 0, "standard": 15, "modern": 15, "pioneer": 15, "legacy": 15}


def _expand_to_size(cards: list[dict], target: int, basics: list[str]) -> list[dict]:
    """Pad with basics (split evenly across ``basics``) to reach target size,
    or trim basics if over."""
    current = sum(c["quantity"] for c in cards)
    if current == target:
        return cards
    if current < target:
        deficit = target - current
        out = [dict(c) for c in cards]
        for i, basic in enumerate(basics):
            share = deficit // len(basics) + (1 if i < deficit % len(basics) else 0)
            if share <= 0:
                continue
            existing = next((c for c in out if c["name"] == basic), None)
            if existing is not None:
                existing["quantity"] += share
            else:
                out.append({"name": basic, "quantity": share})
        return out
    # Over target — trim from any basic-land entry; if none, trim trailing
    excess = current - target
    out = list(cards)
    for entry in out:
        if entry["name"] in {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}:
            take = min(entry["quantity"], excess)
            entry["quantity"] -= take
            excess -= take
            if excess <= 0:
                break
    return [c for c in out if c["quantity"] > 0]


_BASIC_FOR = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
_BASICS = set(_BASIC_FOR.values()) | {"Wastes"}
COMMANDER_LANDS = 37


def _basics_for(colors: tuple[str, ...]) -> list[str]:
    return [_BASIC_FOR[c] for c in "WUBRG" if c in colors] or ["Wastes"]


def _with_land_base(cards: list[dict], colors: tuple[str, ...], target_lands: int, is_land) -> list[dict]:
    """Anchor list plus basics up to ``target_lands``; nonland slots are not
    padded (the record is a template of the archetype's shape, not a full
    list). Padding nonland slots with basics produced 28-Plains Hatebears and
    70-Mountain Commander land packages."""
    lands = sum(c["quantity"] for c in cards if is_land(c["name"]))
    out = [dict(c) for c in cards]
    shortfall = target_lands - lands
    if shortfall > 0:
        out = _expand_to_size(out, sum(c["quantity"] for c in out) + shortfall, _basics_for(colors))
    return out


def _target_lands(archetype) -> int:
    if archetype.mana_base is not None:
        return archetype.mana_base.total_lands
    tags = set(archetype.playstyle_tags)
    if "aggro" in tags or "burn" in tags:
        return 20
    if "control" in tags or "ramp" in tags:
        return 24
    return 22


def _perturb(cards: list[tuple[str, int]], variant_index: int) -> list[dict]:
    """Mild perturbation so the clusterer sees variants of the same archetype.

    Variant 0: as-is.
    Variant 1: shift 1 copy of the longest entry to the next entry (within
               legal-copy limits). Mimics two pilots running different splits.
    """
    base = [{"name": name, "quantity": qty} for name, qty in cards if qty > 0]
    if variant_index == 0 or len(base) < 2:
        return base
    # Find the entry with the largest quantity, drop one, add to next.
    base_sorted = sorted(enumerate(base), key=lambda kv: -kv[1]["quantity"])
    src_idx = base_sorted[0][0]
    tgt_idx = (src_idx + 1) % len(base)
    if base[src_idx]["quantity"] > 1 and base[tgt_idx]["quantity"] < 4:
        base[src_idx]["quantity"] -= 1
        base[tgt_idx]["quantity"] += 1
    return base


def build_records() -> list[dict]:
    from app.rules import is_land_card
    from app.services.card_repository import CardRepository

    repository = CardRepository()

    def is_land(name: str) -> bool:
        card = repository.get_card(name)
        if card is not None:
            return is_land_card(card)
        return name in _BASICS

    records: list[dict] = []
    for archetype in BUILTIN_ARCHETYPES:
        # mechanic-* archetypes are too generic to seed as tournament decks;
        # they have ~7 anchor cards and would distort clusters. Skip them.
        if archetype.id.startswith("mechanic-"):
            continue

        primary_format = archetype.formats[0] if archetype.formats else "modern"
        commander = None
        if primary_format == "commander":
            # Pick the highest-quantity "Legendary"-looking anchor as commander
            # if present; otherwise leave null and let the builder skip it.
            for name, _ in archetype.anchor_cards:
                # Heuristic: anchors with a comma are usually legendary cards.
                if "," in name:
                    commander = name
                    break

        for variant in range(1):  # one template record per archetype
            mainboard_cards = _perturb(list(archetype.anchor_cards), variant)
            target_lands = COMMANDER_LANDS if primary_format == "commander" else _target_lands(archetype)
            mainboard = _with_land_base(mainboard_cards, archetype.colors, target_lands, is_land)
            # Sideboards are never padded with basics.
            sideboard = _perturb(list(archetype.sideboard_anchors), variant)

            record = {
                "id": f"synth-{archetype.id}-{variant}",
                "source": "synthesized-from-builtin",
                "event_name": f"Synthesized {archetype.display_name}",
                "event_date": "2026-01-15",
                "format": primary_format,
                "player_name": f"Synth-{variant}",
                "placement": 1 + variant,  # 1st, 2nd
                "wins": 7 - variant,
                "losses": 1 + variant,
                "draws": 0,
                "colors": list(archetype.colors),
                "tags": list(archetype.playstyle_tags) + list(archetype.theme_tags),
                "commander": commander,
                "mainboard": mainboard,
                "sideboard": sideboard,
                "metadata": {
                    "raw_source": "builtin-archetype-synthesis",
                    "ingested_from": archetype.id,
                    "format_season": "2026-Q1",
                    "event_tier": "challenge",
                    "event_size": 64,
                    "finish_label": f"top-{1 + variant}",
                    "confidence": 0.85,
                    # Stash the canonical builtin display name so the
                    # archetype builder can recover it later. Without this,
                    # build_archetypes auto-generates names like "B Graveyard
                    # Ramp" from the most-common tags, which then dominates
                    # the Format Meta Snapshot UI.
                    "archetype_label": archetype.display_name,
                },
            }
            records.append(record)
    return records


def main() -> None:
    records = build_records()
    OUTPUT_PATH.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    formats: dict[str, int] = {}
    for r in records:
        formats[r["format"]] = formats.get(r["format"], 0) + 1
    print(f"wrote {len(records)} tournament records to {OUTPUT_PATH}")
    for fmt, n in sorted(formats.items(), key=lambda kv: -kv[1]):
        print(f"  {fmt}: {n}")


if __name__ == "__main__":
    main()
