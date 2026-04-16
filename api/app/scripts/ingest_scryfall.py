from __future__ import annotations

import json

import httpx
from sqlalchemy.dialects.postgresql import insert

from app.config import SCRYFALL_BULK_URL, SCRYFALL_USER_AGENT
from app.db import session_scope
from app.db_models import Card, IngestionRun
from app.services.database_bootstrap import create_schema


def infer_tags(card: dict) -> list[str]:
    tags: set[str] = set()
    text = f"{card.get('oracle_text', '')} {card.get('type_line', '')}".lower()
    name = card.get("name", "").lower()

    if "land" in text:
        tags.add("land")
        tags.add("mana")
    if "destroy target" in text or "exile target" in text:
        tags.add("interaction")
        tags.add("removal")
    if "draw" in text:
        tags.add("draw")
    if "add " in text and "mana" in text:
        tags.add("ramp")
    if "sliver" in text or "sliver" in name:
        tags.add("slivers")
        tags.add("tribal")
    if "lifegain" in text or "gain life" in text:
        tags.add("lifegain")
    if "prowess" in text:
        tags.add("prowess")
        tags.add("spells")
    if "instant" in text or "sorcery" in text:
        tags.add("spells")
    if "creature" in text:
        tags.add("creature")
    return sorted(tags)


def normalize_card(card: dict) -> dict[str, object] | None:
    if card.get("layout") == "token":
        return None
    oracle_id = card.get("oracle_id")
    if not oracle_id:
        return None

    prices = card.get("prices") or {}
    image_uris = card.get("image_uris") or {}
    if not image_uris and card.get("card_faces"):
        first_face = next((face for face in card["card_faces"] if face.get("image_uris")), {})
        image_uris = first_face.get("image_uris") or {}

    return {
        "oracle_id": oracle_id,
        "name": card["name"],
        "normalized_name": card["name"].lower(),
        "mana_cost": card.get("mana_cost") or "",
        "mana_value": float(card.get("cmc") or 0),
        "colors": card.get("colors") or [],
        "color_identity": card.get("color_identity") or [],
        "type_line": card.get("type_line") or "",
        "oracle_text": card.get("oracle_text") or "",
        "legalities": card.get("legalities") or {},
        "price_usd": float(prices["usd"]) if prices.get("usd") else None,
        "tags": infer_tags(card),
        "set_code": card.get("set"),
        "released_at": card.get("released_at"),
        "image_uri": image_uris.get("normal"),
    }


def main() -> None:
    create_schema()

    headers = {"User-Agent": SCRYFALL_USER_AGENT}
    with httpx.Client(timeout=120.0, headers=headers) as client:
        payload = client.get(SCRYFALL_BULK_URL).raise_for_status().json()
        default_cards = next(item for item in payload["data"] if item["type"] == "default_cards")
        download_uri = default_cards["download_uri"]
        response = client.get(download_uri)
        response.raise_for_status()
        cards = response.json()

    processed = 0
    with session_scope() as session:
        run = IngestionRun(source="scryfall", status="running", records_processed=0)
        session.add(run)
        session.flush()

        for raw_card in cards:
            normalized = normalize_card(raw_card)
            if not normalized:
                continue
            stmt = insert(Card).values(**normalized)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Card.oracle_id],
                set_={
                    "name": stmt.excluded.name,
                    "normalized_name": stmt.excluded.normalized_name,
                    "mana_cost": stmt.excluded.mana_cost,
                    "mana_value": stmt.excluded.mana_value,
                    "colors": stmt.excluded.colors,
                    "color_identity": stmt.excluded.color_identity,
                    "type_line": stmt.excluded.type_line,
                    "oracle_text": stmt.excluded.oracle_text,
                    "legalities": stmt.excluded.legalities,
                    "price_usd": stmt.excluded.price_usd,
                    "tags": stmt.excluded.tags,
                    "set_code": stmt.excluded.set_code,
                    "released_at": stmt.excluded.released_at,
                    "image_uri": stmt.excluded.image_uri,
                },
            )
            session.execute(stmt)
            processed += 1

        run.status = "completed"
        run.records_processed = processed

    print(json.dumps({"status": "ok", "records_processed": processed}))


if __name__ == "__main__":
    main()
