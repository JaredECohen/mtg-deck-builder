"""Ingest official product decklists from MTGJSON.

MTGJSON republishes Wizards product decks (Commander precons, Pioneer
Challenger Decks, and the rest of the official deck catalog) under the MIT
grant at https://www.mtgjson.com/license/. That is the real-deck corpus this
app is allowed to redistribute. Tournament sites are not. The allow-list and
the reasons the others were skipped live in ``docs/DATA_SOURCES.md``.

The download keeps names and quantities only. Full MTGJSON card objects are
large and carry fields (prices, EDHREC ranks) we are not using.

Usage::

    python -m app.scripts.ingest_official_decks --download
    python -m app.scripts.ingest_official_decks                # ingest snapshot
    python -m app.scripts.ingest_official_decks --download --no-ingest

``--download`` writes the snapshot. On a Fly machine the weekly refresh points
``MTG_OFFICIAL_DECKS_PATH`` at the volume (``/data/official_decks.json``) so
the image's committed copy stays untouched and the new file survives restarts.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.config import DATA_DIR


USER_AGENT = "mtg-deck-lab/1.0 (official product deck ingest; https://mtgdecklab.app)"
DECKLIST_URL = "https://mtgjson.com/api/v5/DeckList.json.gz"
DECK_URL = "https://mtgjson.com/api/v5/decks/{file_name}.json"
LICENSE_URL = "https://www.mtgjson.com/license/"
SOURCE_NAME = "mtgjson"

# Product types worth keeping, mapped to a format this app generates.
# Anything else in DeckList is real but would seed stale or non-competitive
# clusters. See docs/DATA_SOURCES.md.
INCLUDED_TYPES: dict[str, str] = {
    "Commander Deck": "commander",
    "Pioneer Challenger Deck": "pioneer",
}

COMMITTED_SNAPSHOT = DATA_DIR / "official_decks.json"
MIN_COMMANDER_DECKS = 150

# A constructed product list has to be mostly still legal before it joins the
# archetype corpus. Below this, the shell is a rotated or unknown list.
MIN_LEGAL_FRACTION = 0.80


def snapshot_path() -> Path:
    override = os.getenv("MTG_OFFICIAL_DECKS_PATH", "").strip()
    if override:
        return Path(override)
    volume = Path("/data/official_decks.json")
    if volume.exists():
        return volume
    return COMMITTED_SNAPSHOT


def _request(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = response.read()
    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    return payload


def fetch_json(url: str, timeout: float = 60.0) -> dict:
    return json.loads(_request(url, timeout=timeout))


def clean_card_name(name: str) -> str:
    """Collapse MTGJSON's doubled double-faced names ("Card // Card" → "Card")."""
    text = name.strip()
    if " // " in text:
        left, right = [part.strip() for part in text.split(" // ", 1)]
        if left == right and left:
            return left
    return text


def _counts(entries: list[dict] | None) -> list[dict]:
    totals: dict[str, int] = {}
    for entry in entries or []:
        name = clean_card_name(str(entry.get("name") or ""))
        count = int(entry.get("count") or 0)
        if not name or count <= 0:
            continue
        totals[name] = totals.get(name, 0) + count
    return [{"name": name, "quantity": quantity} for name, quantity in totals.items()]


def _identity(commanders: list[dict]) -> list[str]:
    colors: list[str] = []
    for commander in commanders:
        for color in commander.get("colorIdentity") or []:
            if color in {"W", "U", "B", "R", "G"} and color not in colors:
                colors.append(color)
    return colors


def compact_deck(summary: dict, payload: dict) -> dict | None:
    """Reduce one MTGJSON deck file to the fields we store and ingest."""
    deck_type = str(payload.get("type") or summary.get("type") or "")
    format_name = INCLUDED_TYPES.get(deck_type)
    if format_name is None:
        return None
    name = str(payload.get("name") or summary.get("name") or "").strip()
    if not name or "collector" in name.lower():
        return None
    file_name = str(summary.get("fileName") or "").strip()
    if not file_name:
        return None
    commanders = [c for c in (payload.get("commander") or []) if c.get("name")]
    commander_names = [clean_card_name(str(c["name"])) for c in commanders]
    mainboard = _counts(payload.get("mainBoard"))
    for commander_name in commander_names:
        mainboard = [card for card in mainboard if card["name"] != commander_name]
    if not mainboard:
        return None
    source_url = payload.get("source") or summary.get("source")
    return {
        "id": f"mtgjson-{file_name}",
        "file_name": file_name,
        "name": name,
        "set_code": payload.get("code") or summary.get("code"),
        "type": deck_type,
        "format": format_name,
        "release_date": payload.get("releaseDate") or summary.get("releaseDate"),
        "source_url": source_url if isinstance(source_url, str) and source_url.startswith("http") else None,
        "commanders": commander_names,
        "color_identity": _identity(commanders),
        "mainboard": mainboard,
        "sideboard": _counts(payload.get("sideBoard")),
    }


def select_summaries(deck_list: dict) -> list[dict]:
    rows = deck_list.get("data") if isinstance(deck_list, dict) else deck_list
    selected: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if row.get("type") not in INCLUDED_TYPES:
            continue
        if "collector" in str(row.get("name") or "").lower():
            continue
        if not row.get("fileName"):
            continue
        selected.append(row)
    return selected


def download_snapshot(destination: Path, *, workers: int = 6, limit: int | None = None) -> dict:
    """Download the DeckList index and the decks we keep. Writes ``destination``.

    Refuses to replace an existing snapshot when the download is short, so a
    truncated weekly run cannot wipe a good catalog.
    """
    summaries = select_summaries(fetch_json(DECKLIST_URL))
    if limit is not None:
        summaries = summaries[:limit]
    compact: list[dict] = []
    errors: list[str] = []

    def _one(summary: dict) -> dict | None:
        url = DECK_URL.format(file_name=summary["fileName"])
        last_error = "unknown error"
        for _attempt in range(2):
            try:
                return compact_deck(summary, fetch_json(url).get("data") or {})
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
        raise RuntimeError(f"{summary.get('fileName')}: {last_error}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, summary): summary for summary in summaries}
        done = 0
        for future in as_completed(futures):
            done += 1
            summary = futures[future]
            try:
                record = future.result()
            except Exception as exc:  # noqa: BLE001 — one bad deck should not abort the batch
                errors.append(str(exc) or summary.get("fileName", "deck"))
                continue
            if record is not None:
                compact.append(record)
            if done % 40 == 0:
                print(f"  downloaded {done}/{len(summaries)}")

    compact.sort(key=lambda record: record["id"])
    commander_count = sum(1 for record in compact if record["format"] == "commander")
    if limit is None and commander_count < MIN_COMMANDER_DECKS:
        raise RuntimeError(
            f"only {commander_count} commander decks downloaded ({len(errors)} errors); "
            "leaving the existing snapshot in place"
        )
    document = {
        "meta": {
            "source": "https://mtgjson.com",
            "license": LICENSE_URL,
            "notice": "Official Wizards of the Coast product decklists, via MTGJSON. Not tournament standings.",
            "decks": len(compact),
            "commander_decks": commander_count,
            "download_errors": errors[:20],
        },
        "decks": compact,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(destination)
    print(f"wrote {len(compact)} decks ({commander_count} commander) to {destination}")
    return document


def load_snapshot(path: Path | None = None) -> list[dict]:
    snapshot = path or snapshot_path()
    if not snapshot.exists():
        return []
    document = json.loads(snapshot.read_text(encoding="utf-8"))
    decks = document.get("decks") if isinstance(document, dict) else document
    return [deck for deck in decks or [] if isinstance(deck, dict)]


def to_raw_tournament(record: dict) -> dict:
    """Shape expected by ``normalize_raw_deck``."""
    commanders = [name for name in record.get("commanders") or [] if name]
    format_name = record["format"]
    tier = "challenge" if format_name != "commander" else "product"
    source_url = record.get("source_url") or None
    return {
        "id": record["id"],
        "source": SOURCE_NAME,
        "source_url": source_url,
        "event_name": record["name"],
        "event_date": record.get("release_date"),
        "format": format_name,
        "format_season": str(record.get("release_date") or "")[:4] or None,
        "event_tier": tier,
        "finish_label": "Official product",
        "confidence": 0.9,
        "player_name": "Wizards of the Coast",
        "commander": commanders[0] if commanders else None,
        "mainboard": record.get("mainboard") or [],
        "sideboard": record.get("sideboard") or [],
        "metadata": {
            "archetype_label": record["name"],
            "format_season": str(record.get("release_date") or "")[:4] or None,
            "event_tier": tier,
            "finish_label": "Official product",
            "confidence": 0.9,
        },
    }


def legal_fraction(repository, names: list[str], format_name: str) -> float:
    """Share of resolved non-basic cards that are legal in ``format_name``.

    Cards the database doesn't know don't count, so a partial card DB cannot
    accidentally look "legal" by ignoring the missing ones — a deck with too
    few resolved cards scores 0 and is skipped.
    """
    from app.rules import is_basic_land

    known = 0
    legal = 0
    for name in names:
        card = repository.get_card(name)
        if card is None or is_basic_land(card):
            continue
        known += 1
        if card.legalities.get(format_name) in {"legal", "restricted"}:
            legal += 1
    if known < 8:
        return 0.0
    return legal / known


def records_for_ingest(records: list[dict], repository) -> list[dict]:
    """Commander precons always pass. Constructed products must still be legal."""
    kept: list[dict] = []
    for record in records:
        format_name = record.get("format")
        if format_name == "commander":
            kept.append(record)
            continue
        if format_name not in {"pioneer", "modern", "legacy", "standard"}:
            continue
        names = [card["name"] for card in record.get("mainboard") or []]
        if legal_fraction(repository, names, format_name) >= MIN_LEGAL_FRACTION:
            kept.append(record)
    return kept


def ingest_snapshot(path: Path | None = None) -> dict[str, object]:
    """Load the snapshot and merge it into ``tournament_decks``.

    Identical lists are left alone so a weekly refresh that didn't change
    does not rebuild archetypes. Requires the card tables (call this after
    the Scryfall ingest). Skips itself when the card DB is still the sample.
    """
    from app.scripts.ingest_tournament_decks import ingest_raw_decks

    records = load_snapshot(path)
    if not records:
        return {"status": "skipped", "reason": "no snapshot", "inserted": 0, "replaced": 0, "skipped": 0}

    from app.services.card_repository import CardRepository

    repository = CardRepository()
    raw_decks = [to_raw_tournament(record) for record in records_for_ingest(records, repository)]
    if not raw_decks:
        return {"status": "skipped", "reason": "no lists passed the legality filter", "inserted": 0, "replaced": 0, "skipped": 0}
    result = ingest_raw_decks(raw_decks, source_name=SOURCE_NAME, ingested_from=path or snapshot_path())
    result["snapshot_decks"] = len(records)
    result["ingest_candidates"] = len(raw_decks)
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download and ingest MTGJSON official decks.")
    parser.add_argument("--download", action="store_true", help="Refresh the snapshot from MTGJSON")
    parser.add_argument("--no-ingest", action="store_true", help="Do not write the database")
    parser.add_argument("--limit", type=int, default=None, help="Download only the first N selected decks")
    parser.add_argument("--output", type=Path, default=None, help="Snapshot path (default: volume override or committed file)")
    args = parser.parse_args(argv)
    destination = args.output or snapshot_path()
    if args.download:
        download_snapshot(destination, limit=args.limit)
    if args.no_ingest:
        return
    print(json.dumps(ingest_snapshot(destination)))


if __name__ == "__main__":
    main()
