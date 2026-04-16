from __future__ import annotations

import json

from sqlalchemy.dialects.postgresql import insert

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
            payload = {
                "oracle_id": card.get("oracle_id") or f"sample::{card['name'].lower()}",
                "name": card["name"],
                "normalized_name": card["name"].lower(),
                "mana_cost": card.get("mana_cost", ""),
                "mana_value": float(card.get("mana_value", 0)),
                "colors": card.get("colors", []),
                "color_identity": card.get("color_identity", []),
                "type_line": card["type_line"],
                "oracle_text": card.get("oracle_text", ""),
                "legalities": card.get("legalities", {}),
                "price_usd": card.get("price_usd"),
                "tags": card.get("tags", []),
                "set_code": card.get("set_code"),
                "released_at": card.get("released_at"),
                "image_uri": card.get("image_uri"),
            }
            stmt = insert(Card).values(**payload)
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


if __name__ == "__main__":
    main()
