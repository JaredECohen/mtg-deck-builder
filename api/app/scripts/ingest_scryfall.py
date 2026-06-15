from __future__ import annotations

import json

import httpx

from app.config import SCRYFALL_BULK_URL, SCRYFALL_USER_AGENT
from app.db import session_scope
from app.db_models import Card, IngestionRun
from app.services.database_bootstrap import create_schema


SKIPPED_LAYOUTS = {"token", "art_series", "double_faced_token", "emblem"}

# Set types that ship alt-art / non-canonical printings. Preferring "normal" sets
# (expansion / core / commander) keeps card images recognizable instead of
# defaulting to Secret Lair drops or promo artwork.
PROMO_LIKE_SET_TYPES = {
    "promo",
    "memorabilia",
    "alchemy",
    "treasure_chest",
    "vanguard",
    "minigame",
    "funny",
}
SECRET_LAIR_SET_TYPES = {"box", "draft_innovation"}  # "box" covers Secret Lair Drops


def normalize_name(value: str) -> str:
    return " ".join(value.lower().split())


def marketplace_links(card: dict[str, object]) -> dict[str, str]:
    purchase_uris = card.get("purchase_uris") or {}
    related_uris = card.get("related_uris") or {}
    # The TCGplayer link is affiliate-wrapped at the API read boundary
    # (app/services/affiliate.py), so the raw destination URL is stored here.
    return {
        "scryfall": str(related_uris.get("scryfall_uri") or ""),
        "tcgplayer": str(purchase_uris.get("tcgplayer") or ""),
        "cardmarket": str(purchase_uris.get("cardmarket") or ""),
    }


def extract_faces(card: dict[str, object]) -> list[dict[str, str | None]]:
    faces: list[dict[str, str | None]] = []
    for face in card.get("card_faces") or []:
        image_uris = face.get("image_uris") or {}
        faces.append(
            {
                "name": face.get("name"),
                "mana_cost": face.get("mana_cost") or "",
                "type_line": face.get("type_line") or "",
                "oracle_text": face.get("oracle_text") or "",
                "image_uri": image_uris.get("large") or image_uris.get("normal") or image_uris.get("small"),
            }
        )
    return faces


def infer_tags(card: dict[str, object]) -> list[str]:
    tags: set[str] = set()
    oracle_text = str(card.get("oracle_text") or "")
    face_text = " ".join(str(face.get("oracle_text") or "") for face in card.get("card_faces") or [])
    text = f"{oracle_text} {face_text} {card.get('type_line', '')}".lower()
    name = str(card.get("name", "")).lower()

    if "land" in text:
        tags.update({"land", "mana"})
    if "destroy target" in text or "exile target" in text or "counter target" in text:
        tags.update({"interaction", "removal"})
    if "draw" in text:
        tags.add("draw")
    if "create " in text and "token" in text:
        tags.update({"tokens", "go-wide"})
    if "add " in text and ("mana" in text or "{w}" in text or "{u}" in text or "{b}" in text or "{r}" in text or "{g}" in text):
        tags.add("ramp")
    if "flying" in text or "haste" in text or "trample" in text:
        tags.add("pressure")
    if "sliver" in text or "sliver" in name:
        tags.update({"slivers", "tribal"})
    if "lifegain" in text or "gain life" in text:
        tags.add("lifegain")
    if "prowess" in text:
        tags.update({"prowess", "spells"})
    if "instant" in text or "sorcery" in text:
        tags.add("spells")
    if "creature" in text:
        tags.add("creature")
    if "graveyard" in text or "discard" in text:
        tags.add("graveyard")
    if "search your library" in text:
        tags.add("tutor")
    if "legendary creature" in text:
        tags.add("commander")
    return sorted(tags)


def normalize_card(card: dict[str, object]) -> dict[str, object] | None:
    if card.get("layout") in SKIPPED_LAYOUTS:
        return None
    if str(card.get("set_type") or "") == "memorabilia":
        return None
    # Drop foreign-language printings outright. The default_cards bulk usually
    # prefers English already, but enforcing this here removes any ambiguity
    # so the UI never renders Japanese / Phyrexian / etc. card art.
    if str(card.get("lang") or "en") != "en":
        return None

    oracle_id = card.get("oracle_id")
    if not oracle_id:
        return None

    prices = card.get("prices") or {}
    image_uris = card.get("image_uris") or {}
    faces = extract_faces(card)
    if not image_uris and faces:
        first_face_uri = next((face["image_uri"] for face in faces if face.get("image_uri")), None)
        if first_face_uri:
            image_uris = {"normal": first_face_uri}

    return {
        "oracle_id": oracle_id,
        "scryfall_id": card.get("id"),
        "name": card["name"],
        "normalized_name": normalize_name(card["name"]),
        "mana_cost": card.get("mana_cost") or "",
        "mana_value": float(card.get("cmc") or 0),
        "colors": card.get("colors") or [],
        "color_identity": card.get("color_identity") or [],
        "type_line": card.get("type_line") or "",
        "oracle_text": card.get("oracle_text") or "",
        "keywords": card.get("keywords") or [],
        "layout": card.get("layout"),
        "rarity": card.get("rarity"),
        "legalities": card.get("legalities") or {},
        "price_usd": float(prices["usd"]) if prices.get("usd") else None,
        "price_usd_foil": float(prices["usd_foil"]) if prices.get("usd_foil") else None,
        "tags": infer_tags(card),
        "set_code": card.get("set"),
        "set_type": card.get("set_type"),
        "released_at": card.get("released_at"),
        "image_uri": image_uris.get("large") or image_uris.get("normal") or image_uris.get("small"),
        "image_uris": {key: value for key, value in image_uris.items() if value},
        "card_faces": faces,
        "purchase_links": {key: value for key, value in marketplace_links(card).items() if value},
    }


def printing_priority(normalized: dict[str, object]) -> tuple[int, int, str]:
    """Sort key for picking the canonical printing of a card.

    Returns a tuple sorted DESCENDING — higher tuples win. Tier order:
      0 — promo / alt-art / Secret Lair (avoid unless nothing else exists)
      1 — Secret Lair Drop and other "box" innovations
      2 — every normal expansion / core / commander / masters set
    Within a tier we still prefer the most recent printing.
    """
    set_type = str(normalized.get("set_type") or "")
    if set_type in PROMO_LIKE_SET_TYPES:
        tier = 0
    elif set_type in SECRET_LAIR_SET_TYPES:
        tier = 1
    else:
        tier = 2
    released_year = 0
    released = str(normalized.get("released_at") or "")
    if released[:4].isdigit():
        released_year = int(released[:4])
    return (tier, released_year, released)


def main() -> None:
    create_schema()

    headers = {"User-Agent": SCRYFALL_USER_AGENT}
    with httpx.Client(timeout=240.0, headers=headers, follow_redirects=True) as client:
        payload = client.get(SCRYFALL_BULK_URL).raise_for_status().json()
        default_cards = next(item for item in payload["data"] if item["type"] == "default_cards")
        download_uri = default_cards["download_uri"]
        cards = client.get(download_uri).raise_for_status().json()

    normalized_cards: dict[str, dict[str, object]] = {}
    skipped = 0
    for raw_card in cards:
        normalized = normalize_card(raw_card)
        if not normalized:
            skipped += 1
            continue
        key = str(normalized["normalized_name"])
        existing = normalized_cards.get(key)
        if existing is None or printing_priority(normalized) > printing_priority(existing):
            normalized_cards[key] = normalized

    processed = 0
    with session_scope() as session:
        run = IngestionRun(source="scryfall", status="running", records_processed=0)
        session.add(run)
        session.flush()

        for normalized in normalized_cards.values():
            # set_type is used only for dedupe priority; not stored on Card.
            payload = {k: v for k, v in normalized.items() if k != "set_type"}
            session.merge(Card(**payload))
            processed += 1
            if processed % 2000 == 0:
                session.flush()

        run.status = "completed"
        run.records_processed = processed
        run.notes = json.dumps({"skipped": skipped, "source_type": "default_cards", "deduped_names": len(normalized_cards)})

    print(json.dumps({"status": "ok", "records_processed": processed, "skipped": skipped}))


if __name__ == "__main__":
    main()
