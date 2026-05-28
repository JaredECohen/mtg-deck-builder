"""Build dense embeddings for every card and store them in the
``card_embeddings`` table.

Usage::

    python -m app.scripts.build_card_embeddings              # all cards in DB
    python -m app.scripts.build_card_embeddings --limit 500  # smoke test

Powers the retriever's ``vector`` mode (works on SQLite) and the
pgvector ``<=>`` path on Postgres. Idempotent: re-running upserts rows
for the current ``EMBEDDING_MODEL``. The default embedder is the
deterministic feature-hash projection in :mod:`app.services.embeddings`;
swap that for a learned model without changing this script or the schema.
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy.orm import Session

from app.db import get_engine, session_scope
from app.db_models import Base, Card, CardEmbedding
from app.services.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, embed_card


def _card_to_record(row: Card) -> dict:
    return {
        "name": row.name,
        "type_line": row.type_line,
        "oracle_text": row.oracle_text,
        "keywords": row.keywords or [],
        "tags": row.tags or [],
        "color_identity": row.color_identity or [],
        "mana_value": row.mana_value,
    }


def build_embeddings(*, limit: int | None = None) -> dict:
    # Lazily ensure the table exists (dev convenience; prod uses migrations).
    Base.metadata.create_all(get_engine(), tables=[CardEmbedding.__table__])

    processed = 0
    inserted = 0
    updated = 0
    with session_scope() as session:  # type: Session
        query = session.query(Card)
        if limit:
            query = query.limit(limit)
        for row in query:
            vector = embed_card(_card_to_record(row), dim=EMBEDDING_DIM)
            existing = session.get(CardEmbedding, row.name)
            if existing is None:
                session.add(CardEmbedding(
                    name=row.name, model=EMBEDDING_MODEL, dim=EMBEDDING_DIM, vector=vector,
                ))
                inserted += 1
            else:
                existing.model = EMBEDDING_MODEL
                existing.dim = EMBEDDING_DIM
                existing.vector = vector
                updated += 1
            processed += 1
    return {
        "status": "ok",
        "model": EMBEDDING_MODEL,
        "dim": EMBEDDING_DIM,
        "processed": processed,
        "inserted": inserted,
        "updated": updated,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build card embeddings")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    result = build_embeddings(limit=args.limit)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
