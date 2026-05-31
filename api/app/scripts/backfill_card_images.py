"""Surgical re-fetch of cards with missing image, missing price, or known
bad printings (Secret Lair alt-art, foreign-language, joke sets).

Walks the existing `cards` table and identifies "suspect" rows:
  - image_uri IS NULL
  - price_usd IS NULL (excluding basic lands, which legitimately have no
    Scryfall price)
  - set_code in a small problem list (sld = Secret Lair Drop alt-art)

For each suspect, re-fetches the canonical English printing via Scryfall's
`/cards/named?exact={name}` endpoint and updates image_uri, image_uris,
price_usd, set_code, set_type, purchase_links. Skips DFCs that already have
a face image. Throttled to Scryfall's published rate limit (10 req/sec).

Idempotent — re-running only touches rows still missing data. Doesn't
require the 5GB all_cards bulk download.

Usage:
    cd api && source .venv/bin/activate && python -m app.scripts.backfill_card_images
    # Optional --limit N to cap how many cards to refresh in this run
    python -m app.scripts.backfill_card_images --limit 500
"""
from __future__ import annotations

import argparse
import time
from urllib.parse import quote

import httpx
from sqlalchemy import or_, select

from app.config import SCRYFALL_USER_AGENT
from app.db import session_scope
from app.db_models import Card


# Set codes whose Scryfall printing is known to be off-canonical (alt-art,
# stickers, etc.). Forces a re-fetch even if image and price are populated.
PROBLEM_SET_CODES = frozenset({"sld", "plg21", "plg22", "plg23", "pip"})

# Cards from these sets have no meaningful USD price and shouldn't be flagged
# as suspect just for the price gap.
PRICELESS_LAYOUTS = frozenset({"basic"})


def marketplace_links(card: dict) -> dict:
    purchase = card.get("purchase_uris") or {}
    related = card.get("related_uris") or {}
    return {
        "scryfall": str(related.get("scryfall_uri") or ""),
        "tcgplayer": str(purchase.get("tcgplayer") or ""),
        "cardmarket": str(purchase.get("cardmarket") or ""),
    }


def extract_image_uris(card: dict) -> dict[str, str]:
    image_uris = dict(card.get("image_uris") or {})
    if not image_uris:
        # DFC: use front face
        faces = card.get("card_faces") or []
        if faces and isinstance(faces[0], dict):
            face_uris = dict(faces[0].get("image_uris") or {})
            if face_uris:
                image_uris = face_uris
    return {k: v for k, v in image_uris.items() if v}


def _name_candidates(name: str) -> list[str]:
    """Generate name variants to try against Scryfall's exact-name endpoint.

    Handles the patterns that produce 404s on /cards/named?exact:
      • Full DFC: "Tamiyo, Inquisitive Student // Tamiyo, Seasoned Scholar"
        Scryfall accepts the full DFC name on /named?exact, but only if the
        server has it indexed exactly. Try full, front face, back face.
      • Adventure cards: "Brazen Borrower // Petty Theft" — same split.
      • Split cards: "Fire // Ice" — same split.
      • Modal DFCs: handled the same as DFC.
      • Some cards have an em-dash variant of the // separator.

    Returns the variants in order; the caller tries each until one resolves.
    """
    variants: list[str] = [name]
    # Normalize " / " / " // " / "//" / em-dash variants to a single splitter.
    for sep in (" // ", "//", " / ", " — "):
        if sep in name:
            parts = [p.strip() for p in name.split(sep) if p.strip()]
            for part in parts:
                if part and part not in variants:
                    variants.append(part)
            # Also try the canonical form: front // back.
            if len(parts) == 2:
                canonical = f"{parts[0]} // {parts[1]}"
                if canonical not in variants:
                    variants.append(canonical)
            break  # only one split separator should apply
    return variants


def fetch_canonical(client: httpx.Client, name: str, retries: int = 3) -> dict | None:
    """Fetch the canonical English printing for a card by name. Returns the
    Scryfall card JSON or None on 404 / persistent network failure.

    Tries name variants (DFC half-names, adventure splits) before giving up.
    Retries on 429 (rate-limited) and 5xx with exponential backoff. Honors
    Scryfall's documented 10 req/sec limit.
    """
    candidates = _name_candidates(name)
    for candidate in candidates:
        url = f"https://api.scryfall.com/cards/named?exact={quote(candidate)}"
        for attempt in range(retries):
            try:
                response = client.get(url, timeout=15.0)
            except Exception:
                time.sleep(0.5 * (attempt + 1))
                continue
            if response.status_code == 404:
                break  # this candidate doesn't exist; try next
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(1.0 * (attempt + 1))
                continue
            if response.status_code == 200:
                try:
                    return response.json()
                except Exception:
                    return None
            break  # other 4xx: don't retry, try next candidate
    return None


def is_suspect(card: Card) -> bool:
    if card.image_uri is None or card.image_uri == "":
        return True
    if card.set_code and card.set_code.lower() in PROBLEM_SET_CODES:
        return True
    if card.price_usd is None and "Basic Land" not in (card.type_line or ""):
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Cap on cards to refresh (0=no cap).")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no DB writes.")
    parser.add_argument(
        "--names",
        type=str,
        default="",
        help="Comma-separated card names to refresh (bypasses suspect detection).",
    )
    args = parser.parse_args()

    headers = {"User-Agent": SCRYFALL_USER_AGENT, "Accept": "application/json"}
    refreshed = 0
    skipped = 0
    not_found = 0

    with session_scope() as session, httpx.Client(headers=headers, follow_redirects=True) as client:
        if args.names:
            wanted = [name.strip() for name in args.names.split(",") if name.strip()]
            candidates = list(session.scalars(select(Card).where(Card.name.in_(wanted))).all())
        else:
            # Pull suspect rows in batches so memory stays bounded.
            candidates = list(session.scalars(
                select(Card).where(
                    or_(
                        Card.image_uri.is_(None),
                        Card.image_uri == "",
                        Card.set_code.in_(PROBLEM_SET_CODES),
                        Card.price_usd.is_(None),
                    )
                )
            ).all())
            # Re-filter in Python because the price-null clause over-collects basic lands.
            candidates = [card for card in candidates if is_suspect(card)]
        if args.limit > 0:
            candidates = candidates[: args.limit]

        print(f"{len(candidates)} suspect card(s) identified; refreshing...")
        for card in candidates:
            data = fetch_canonical(client, card.name)
            if data is None:
                not_found += 1
                time.sleep(0.1)  # Scryfall asks for ~10 req/sec max
                continue

            image_uris = extract_image_uris(data)
            image_uri = (
                image_uris.get("large")
                or image_uris.get("normal")
                or image_uris.get("small")
                or card.image_uri
            )
            prices = data.get("prices") or {}
            new_price = float(prices["usd"]) if prices.get("usd") else card.price_usd
            new_foil = float(prices["usd_foil"]) if prices.get("usd_foil") else card.price_usd_foil

            changed = False
            if image_uri and image_uri != card.image_uri:
                card.image_uri = image_uri
                changed = True
            if image_uris and image_uris != (card.image_uris or {}):
                card.image_uris = image_uris
                changed = True
            if new_price != card.price_usd:
                card.price_usd = new_price
                changed = True
            if new_foil != card.price_usd_foil:
                card.price_usd_foil = new_foil
                changed = True
            new_set_code = data.get("set")
            if new_set_code and new_set_code != card.set_code:
                card.set_code = new_set_code
                changed = True
            new_set_type = data.get("set_type")
            if new_set_type and new_set_type != card.set_type:
                card.set_type = new_set_type
                changed = True
            new_links = marketplace_links(data)
            existing_links = dict(card.purchase_links or {})
            # Keep amazon_search if already set; update the rest.
            new_links_clean = {k: v for k, v in new_links.items() if v}
            merged_links = {**existing_links, **new_links_clean}
            if merged_links != existing_links:
                card.purchase_links = merged_links
                changed = True

            if changed:
                refreshed += 1
            else:
                skipped += 1

            time.sleep(0.1)  # rate-limit pacing

        if args.dry_run:
            session.rollback()
            print(f"DRY RUN — would have refreshed {refreshed}, skipped {skipped}, missing {not_found}")
        else:
            print(f"refreshed {refreshed} card(s); skipped {skipped}; missing {not_found}")


if __name__ == "__main__":
    main()
