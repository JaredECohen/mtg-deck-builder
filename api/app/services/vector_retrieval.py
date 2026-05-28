"""Semantic card retrieval with a pgvector fast-path and a dependency-free
fallback.

Two retrieval modes share one interface:

* **pgvector** (when ``MTG_USE_PGVECTOR=true`` *and* the ``card_embeddings``
  table exists): nearest-neighbour search via the ``<=>`` cosine operator.
* **lexical fallback** (default): a deterministic bag-of-features cosine
  over each card's type line, oracle-text tokens, keywords, and tags.
  No external embedding model, no DB — so it runs anywhere, including
  tests and offline dev.

The fallback is intentionally simple but useful: it surfaces cards that
share mechanics ("draw a card", "deal damage", token-makers) and type,
which is exactly what archetype-shell adaptation needs before a real
embedding pipeline is provisioned.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from dataclasses import dataclass

from app.services.card_features import cosine as _cosine
from app.services.card_features import featurize as _featurize
from app.services.card_features import featurize_text
from app.services.embeddings import cosine_dense, embed_card, embed_text, load_card_embeddings

logger = logging.getLogger(__name__)


@dataclass
class RetrievalHit:
    name: str
    score: float

    def to_dict(self) -> dict:
        return {"name": self.name, "score": round(self.score, 4)}


class CardVectorRetriever:
    """Find cards similar to a seed card or free-text query.

    Mode resolution (best first):
      1. ``pgvector`` — Postgres ``<=>`` cosine over a ``card_embeddings``
         table (when ``MTG_USE_PGVECTOR`` and the table exist).
      2. ``vector`` — stored dense embeddings (works on SQLite too): the
         build_card_embeddings script populates the table, and cosine is
         computed in Python.
      3. ``lexical`` — deterministic bag-of-features cosine, no DB needed.
    """

    def __init__(
        self,
        repository,
        *,
        use_pgvector: bool | None = None,
        embeddings: dict[str, list[float]] | None = None,
        session_factory=None,
    ) -> None:
        self.repository = repository
        if use_pgvector is None:
            use_pgvector = os.getenv("MTG_USE_PGVECTOR", "").lower() in {"1", "true", "yes"}
        self.use_pgvector = use_pgvector and self._pgvector_available()
        # Stored dense embeddings (vector mode). Loaded eagerly when not
        # injected; empty dict means fall back to lexical.
        if embeddings is not None:
            self._embeddings = embeddings
        else:
            self._embeddings = load_card_embeddings(session_factory)
        self._feature_cache: dict[str, Counter] = {}

    @property
    def mode(self) -> str:
        if self.use_pgvector:
            return "pgvector"
        if self._embeddings:
            return "vector"
        return "lexical"

    # -- public API -----------------------------------------------------

    def similar_to(self, card_name: str, *, k: int = 10) -> list[RetrievalHit]:
        seed = self.repository.get_card(card_name)
        if seed is None:
            return []
        if self.use_pgvector:
            hits = self._pgvector_neighbors(card_name, k)
            if hits:
                return hits
            logger.info("pgvector returned no rows for %s; falling back", card_name)
        if self._embeddings:
            seed_vec = self._embeddings.get(card_name) or embed_card(seed)
            return self._rank_dense(seed_vec, k=k, exclude={self._norm(card_name)})
        return self._rank(_featurize(seed), k=k, exclude={self._norm(card_name)})

    def search(self, query_text: str, *, k: int = 10) -> list[RetrievalHit]:
        """Free-text semantic-ish search."""
        if self._embeddings:
            return self._rank_dense(embed_text(query_text), k=k, exclude=set())
        return self._rank(featurize_text(query_text), k=k, exclude=set())

    # -- internals ------------------------------------------------------

    def _norm(self, name: str) -> str:
        norm = getattr(self.repository, "_normalize_name", None)
        return norm(name) if callable(norm) else name.lower()

    def _all_cards(self):
        repo = self.repository
        if hasattr(repo, "_cards_by_name"):
            return list(repo._cards_by_name.values())
        if hasattr(repo, "list_cards_for_format"):
            return repo.list_cards_for_format("modern")
        return []

    def _features_for(self, card) -> Counter:
        name = getattr(card, "name", None) or (card.get("name") if isinstance(card, dict) else None)
        if name and name in self._feature_cache:
            return self._feature_cache[name]
        feats = _featurize(card)
        if name:
            self._feature_cache[name] = feats
        return feats

    def _rank_dense(self, query_vec: list[float], *, k: int, exclude: set[str]) -> list[RetrievalHit]:
        """Rank stored dense embeddings by cosine to ``query_vec``."""
        if not query_vec:
            return []
        scored: list[RetrievalHit] = []
        for name, vec in self._embeddings.items():
            if self._norm(name) in exclude:
                continue
            score = cosine_dense(query_vec, vec)
            if score > 0.0:
                scored.append(RetrievalHit(name=name, score=score))
        scored.sort(key=lambda h: (-h.score, h.name))
        return scored[:k]

    def _rank(self, query_feats: Counter, *, k: int, exclude: set[str]) -> list[RetrievalHit]:
        if not query_feats:
            return []
        scored: list[RetrievalHit] = []
        for card in self._all_cards():
            name = getattr(card, "name", None) or (card.get("name") if isinstance(card, dict) else None)
            if not name or self._norm(name) in exclude:
                continue
            score = _cosine(query_feats, self._features_for(card))
            if score > 0.0:
                scored.append(RetrievalHit(name=name, score=score))
        scored.sort(key=lambda h: (-h.score, h.name))
        return scored[:k]

    def _pgvector_available(self) -> bool:
        try:
            from app.db import session_scope  # noqa: F401
        except ImportError:
            return False
        try:
            from sqlalchemy import inspect
            from app.db import engine  # type: ignore
            return "card_embeddings" in inspect(engine).get_table_names()
        except Exception as exc:  # noqa: BLE001
            logger.info("pgvector availability check failed (%s); using fallback", exc)
            return False

    def _pgvector_neighbors(self, card_name: str, k: int) -> list[RetrievalHit]:
        """Nearest neighbours via pgvector cosine distance. Returns [] on
        any failure so callers fall back to lexical retrieval."""
        try:
            from sqlalchemy import text
            from app.db import session_scope
            with session_scope() as session:
                seed = session.execute(
                    text("SELECT embedding FROM card_embeddings WHERE name = :n"),
                    {"n": card_name},
                ).first()
                if not seed:
                    return []
                rows = session.execute(
                    text(
                        "SELECT name, 1 - (embedding <=> :emb) AS score "
                        "FROM card_embeddings WHERE name != :n "
                        "ORDER BY embedding <=> :emb LIMIT :k"
                    ),
                    {"emb": seed[0], "n": card_name, "k": k},
                ).fetchall()
            return [RetrievalHit(name=r[0], score=float(r[1])) for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("pgvector neighbour query failed (%s); using fallback", exc)
            return []
