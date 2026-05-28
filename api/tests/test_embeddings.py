"""Tests for the card embedding pipeline + the retriever's vector mode."""

from __future__ import annotations

import math

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db_models import Base, CardEmbedding
from app.services.card_repository import CardRepository
from app.services.embeddings import (
    EMBEDDING_DIM,
    cosine_dense,
    embed_card,
    embed_text,
    load_card_embeddings,
)
from app.services.vector_retrieval import CardVectorRetriever

BOLT = {"name": "Lightning Bolt", "type_line": "Instant", "color_identity": ["R"],
        "oracle_text": "Lightning Bolt deals 3 damage to any target.", "mana_value": 1}
DART = {"name": "Lava Dart", "type_line": "Instant", "color_identity": ["R"],
        "oracle_text": "Lava Dart deals 1 damage to any target. Flashback.", "mana_value": 1}
TREE = {"name": "Llanowar Elves", "type_line": "Creature — Elf Druid",
        "color_identity": ["G"], "oracle_text": "Tap: Add G.", "mana_value": 1}


def test_embedding_is_deterministic_and_normalized():
    a = embed_card(BOLT)
    b = embed_card(BOLT)
    assert a == b  # blake2b hashing → stable across calls
    assert len(a) == EMBEDDING_DIM
    assert abs(math.sqrt(sum(x * x for x in a)) - 1.0) < 1e-9


def test_similar_cards_embed_closer_than_dissimilar():
    bolt = embed_card(BOLT)
    dart = embed_card(DART)
    elf = embed_card(TREE)
    assert cosine_dense(bolt, dart) > cosine_dense(bolt, elf)


def test_embed_text_matches_card_themes():
    q = embed_text("deal damage to any target instant")
    assert cosine_dense(q, embed_card(BOLT)) > cosine_dense(q, embed_card(TREE))


def _embedding_db():
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[CardEmbedding.__table__])
    sf = sessionmaker(bind=engine, future=True)
    session = sf()
    for rec in (BOLT, DART, TREE):
        session.add(CardEmbedding(name=rec["name"], model="test", dim=EMBEDDING_DIM,
                                  vector=embed_card(rec)))
    session.commit()
    session.close()
    return sf


def test_load_card_embeddings_roundtrip():
    sf = _embedding_db()
    loaded = load_card_embeddings(sf)
    assert set(loaded) == {"Lightning Bolt", "Lava Dart", "Llanowar Elves"}
    assert len(loaded["Lightning Bolt"]) == EMBEDDING_DIM


def test_retriever_vector_mode_uses_stored_embeddings():
    sf = _embedding_db()
    r = CardVectorRetriever(CardRepository(), use_pgvector=False, session_factory=sf)
    assert r.mode == "vector"
    hits = r.similar_to("Lightning Bolt", k=2)
    names = [h.name for h in hits]
    assert "Lightning Bolt" not in names
    # Lava Dart (red damage instant) ranks above the green elf.
    assert names[0] == "Lava Dart"


def test_retriever_lexical_mode_when_no_embeddings():
    r = CardVectorRetriever(CardRepository(), use_pgvector=False, embeddings={})
    assert r.mode == "lexical"
