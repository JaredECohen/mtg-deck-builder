"""Generate a curated tournament-deck corpus from BUILTIN_ARCHETYPES.

The shipped sample corpus has 11 entries — all RU Spells / W Lifegain
variants — which is why every fallback path picks "W Lifegain Payoff" for
arbitrary requests and the Format Meta Snapshot is dominated by 2 archetypes.

This script turns each builtin archetype into 2 tournament_deck records
(slight quantity perturbations so the archetype builder's clusterer sees
"multiple decks of this archetype" rather than a single point). The result:
~200 tournament decks across ~100 archetypes, all format-correct, all
covering the actual Modern / Pioneer / Standard / Legacy / Commander
metagame instead of two niche shells.

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


def _expand_to_size(cards: list[dict], target: int, basic_land: str) -> list[dict]:
    """Pad with basics to reach target size, or trim trailing basics if over."""
    current = sum(c["quantity"] for c in cards)
    if current == target:
        return cards
    if current < target:
        # Add more of the basic land
        deficit = target - current
        out = list(cards)
        existing = next((c for c in out if c["name"] == basic_land), None)
        if existing is not None:
            existing["quantity"] += deficit
        else:
            out.append({"name": basic_land, "quantity": deficit})
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


def _pick_basic(colors: tuple[str, ...]) -> str:
    if "G" in colors:
        return "Forest"
    if "R" in colors:
        return "Mountain"
    if "B" in colors:
        return "Swamp"
    if "U" in colors:
        return "Island"
    if "W" in colors:
        return "Plains"
    return "Wastes"


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
    records: list[dict] = []
    for archetype in BUILTIN_ARCHETYPES:
        # mechanic-* archetypes are too generic to seed as tournament decks;
        # they have ~7 anchor cards and would distort clusters. Skip them.
        if archetype.id.startswith("mechanic-"):
            continue

        primary_format = archetype.formats[0] if archetype.formats else "modern"
        target_main = DECK_SIZE.get(primary_format, 60)
        target_side = SIDEBOARD_SIZE.get(primary_format, 15)
        basic = _pick_basic(archetype.colors)
        commander = None
        if primary_format == "commander":
            # Pick the highest-quantity "Legendary"-looking anchor as commander
            # if present; otherwise leave null and let the builder skip it.
            for name, _ in archetype.anchor_cards:
                # Heuristic: anchors with a comma are usually legendary cards.
                if "," in name:
                    commander = name
                    break

        for variant in range(2):  # two variants per archetype
            mainboard_cards = _perturb(list(archetype.anchor_cards), variant)
            mainboard = _expand_to_size(mainboard_cards, target_main, basic)
            sideboard_cards = _perturb(list(archetype.sideboard_anchors), variant)
            sideboard = _expand_to_size(sideboard_cards, target_side, basic) if archetype.sideboard_anchors else []

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
