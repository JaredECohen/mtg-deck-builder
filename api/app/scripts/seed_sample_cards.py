from __future__ import annotations

import json

from app.config import CARD_CACHE_PATH
from app.db import session_scope
from app.db_models import Card
from app.services.database_bootstrap import create_schema


def main() -> None:
    create_schema()
    with CARD_CACHE_PATH.open() as handle:
        cards = json.load(handle)

    with session_scope() as session:
        for card in cards:
            name = card["name"]
            payload = {
                "oracle_id": card.get("oracle_id") or f"sample::{name.lower()}",
                "name": name,
                "normalized_name": " ".join(name.lower().split()),
                "mana_cost": card.get("mana_cost", ""),
                "mana_value": float(card.get("mana_value", 0)),
                "colors": card.get("colors", []),
                "color_identity": card.get("color_identity", []),
                "type_line": card["type_line"],
                "oracle_text": card.get("oracle_text", ""),
                "keywords": card.get("keywords", []),
                "layout": card.get("layout"),
                "rarity": card.get("rarity"),
                "legalities": card.get("legalities", {}),
                "price_usd": card.get("price_usd"),
                "price_usd_foil": card.get("price_usd_foil"),
                "tags": card.get("tags", []),
                "set_code": card.get("set_code"),
                "released_at": card.get("released_at"),
                "image_uri": card.get("image_uri"),
                "image_uris": card.get("image_uris", {}),
                "card_faces": card.get("faces", []),
                # Preserve source purchase links (scryfall/tcgplayer/cardmarket).
                # The TCGplayer link is affiliate-wrapped at the read boundary.
                "purchase_links": card.get("purchase_links", {}),
            }
            session.merge(Card(**payload))


if __name__ == "__main__":
    main()
