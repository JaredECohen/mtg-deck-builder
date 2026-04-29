"""Bulk-fix card images from promo / foreign-language printings.

NOTE: this script is mostly superseded by `app.services.card_refresh`, which
lazily fixes the same rows on the fly as the API serves them. Use this
script when you want to force-refresh every suspect row up front (e.g.
seeding a fresh DB) rather than waiting for the lazy layer to fire on each
card's first surface.

Run from the api/ directory:

    python -m app.scripts.fix_card_images

Optional flags:
    --dry-run             list what would change without writing
    --include-set CODE    additionally fix all cards in this exact set
    --limit N             cap how many cards to fix (debug)
"""
from __future__ import annotations

import argparse
import json
import time

import httpx
from sqlalchemy import select, update

from app.config import SCRYFALL_USER_AGENT
from app.db import session_scope
from app.db_models import Card


# Set codes known to ship non-English / regional-art printings. This list is
# deliberately narrow — only sets where the physical card art is in another
# language (so the IMAGE looks foreign even if Scryfall stores the oracle
# entry as English). Broader catches like every "p"-prefixed promo set
# include legitimate English promos and would over-replace.
SUSPECT_SET_CODES: set[str] = {
    "ptk",    # Portal Three Kingdoms (Chinese-only printing)
    "pwcs",   # World Championship Promos (regional, foreign-text)
    "soa",    # Secret Lair Showcase (Japanese reprints)
    "ren",    # Renaissance (German / Italian)
    "rin",    # Rinascimento (Italian)
    "fbb",    # Foreign Black Border
    "fwb",    # Foreign White Border
    "4bb",    # 4th Edition Black Border (Japanese)
    "ja22",   # Jumpstart 2022 Japanese
    "wc97", "wc98", "wc99", "wc00", "wc01", "wc02", "wc03", "wc04",
}


def is_suspect_set(set_code: str | None) -> bool:
    if not set_code:
        return False
    return set_code.lower() in SUSPECT_SET_CODES


def fetch_canonical(client: httpx.Client, name: str) -> dict[str, object] | None:
    """Hit Scryfall's named endpoint to get the canonical English printing.

    Retries on 429 with exponential backoff so a long batch doesn't fail
    halfway through when Scryfall pushes back.
    """
    backoff = 0.5
    for attempt in range(5):
        response = client.get("https://api.scryfall.com/cards/named", params={"exact": name})
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            time.sleep(backoff)
            backoff *= 2
            continue
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("lang") or "en") != "en":
            return None
        return payload
    return None


def extract_image(payload: dict[str, object]) -> tuple[str | None, dict[str, str], list[dict[str, object]]]:
    image_uris = payload.get("image_uris") or {}
    faces = payload.get("card_faces") or []
    face_records: list[dict[str, object]] = []
    for face in faces:
        face_image_uris = face.get("image_uris") or {}
        face_records.append(
            {
                "name": face.get("name"),
                "mana_cost": face.get("mana_cost") or "",
                "type_line": face.get("type_line") or "",
                "oracle_text": face.get("oracle_text") or "",
                "image_uri": face_image_uris.get("large")
                or face_image_uris.get("normal")
                or face_image_uris.get("small"),
            }
        )
    if not image_uris and face_records:
        first = next((f["image_uri"] for f in face_records if f.get("image_uri")), None)
        if first:
            image_uris = {"normal": first}
    primary = image_uris.get("large") or image_uris.get("normal") or image_uris.get("small")
    return primary, {key: value for key, value in image_uris.items() if value}, face_records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-set", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    extra_sets = {code.lower() for code in args.include_set}

    headers = {"User-Agent": SCRYFALL_USER_AGENT, "Accept": "application/json"}
    fixed: list[dict[str, object]] = []
    skipped: list[str] = []
    failed: list[str] = []

    with session_scope() as session:
        rows = session.execute(select(Card.normalized_name, Card.name, Card.set_code, Card.image_uri)).all()

    candidates = [
        row for row in rows
        if is_suspect_set(row.set_code) or (row.set_code or "").lower() in extra_sets
    ]
    if args.limit:
        candidates = candidates[: args.limit]

    print(f"Scanning {len(rows)} cards; {len(candidates)} candidates from suspect sets.")

    with httpx.Client(timeout=30.0, headers=headers) as client:
        for row in candidates:
            try:
                payload = fetch_canonical(client, row.name)
            except Exception as exc:
                failed.append(f"{row.name}: {exc}")
                continue
            if payload is None:
                skipped.append(f"{row.name}: no English printing returned")
                continue
            image_uri, image_uris, faces = extract_image(payload)
            new_set = str(payload.get("set") or row.set_code or "")
            if image_uri == row.image_uri and new_set == (row.set_code or ""):
                skipped.append(f"{row.name}: already canonical")
                continue
            fixed.append(
                {
                    "normalized_name": row.normalized_name,
                    "name": row.name,
                    "old_set": row.set_code,
                    "new_set": new_set,
                    "old_image": row.image_uri,
                    "new_image": image_uri,
                    "image_uris": image_uris,
                    "faces": faces,
                }
            )
            time.sleep(0.12)  # Stay well under Scryfall's 10 req/sec ceiling.

    print(f"Will update {len(fixed)} cards; skipped {len(skipped)}; failed {len(failed)}.")
    if args.dry_run:
        for entry in fixed[:20]:
            print(json.dumps({k: v for k, v in entry.items() if k != "faces"}, indent=2))
        return

    if not fixed:
        return

    with session_scope() as session:
        for entry in fixed:
            session.execute(
                update(Card)
                .where(Card.normalized_name == entry["normalized_name"])
                .values(
                    set_code=entry["new_set"],
                    image_uri=entry["new_image"],
                    image_uris=entry["image_uris"],
                    card_faces=entry["faces"],
                )
            )

    print(json.dumps({"status": "ok", "updated": len(fixed), "failed": failed[:5]}))


if __name__ == "__main__":
    main()
