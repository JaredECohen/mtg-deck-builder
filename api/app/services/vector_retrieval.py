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
import math
import os
import re
from collections import Counter
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "for", "with", "this", "that",
    "you", "your", "it", "its", "is", "are", "be", "as", "at", "on", "in",
    "from", "up", "may", "if", "then", "each", "any", "all", "card", "cards",
    "target", "control", "controls", "player", "players", "into", "onto",
}


@dataclass
class RetrievalHit:
    name: str
    score: float

    def to_dict(self) -> dict:
        return {"name": self.name, "score": round(self.score, 4)}


def _featurize(card) -> Counter:
    """Bag-of-features for a card record (dataclass or dict)."""
    def get(field: str, default=""):
        if isinstance(card, dict):
            return card.get(field, default)
        return getattr(card, field, default)

    feats: Counter = Counter()
    type_line = str(get("type_line", "")).lower()
    for tok in _TOKEN_RE.findall(type_line):
        feats[f"type:{tok}"] += 2.0  # type is a strong signal
    for color in get("color_identity", []) or []:
        feats[f"ci:{color}"] += 1.5
    for kw in get("keywords", []) or []:
        feats[f"kw:{str(kw).lower()}"] += 1.5
    for tag in get("tags", []) or []:
        feats[f"tag:{str(tag).lower()}"] += 1.0
    oracle = str(get("oracle_text", "")).lower()
    for tok in _TOKEN_RE.findall(oracle):
        if tok in _STOPWORDS or len(tok) <= 2:
            continue
        feats[f"o:{tok}"] += 1.0
    mv = get("mana_value", 0) or 0
    try:
        feats[f"mv:{int(float(mv))}"] += 0.5
    except (TypeError, ValueError):
        pass
    return feats


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    # Iterate the smaller vector for the dot product.
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    dot = sum(w * big.get(k, 0.0) for k, w in small.items())
    if dot == 0.0:
        return 0.0
    na = math.sqrt(sum(w * w for w in a.values()))
    nb = math.sqrt(sum(w * w for w in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class CardVectorRetriever:
    """Find cards similar to a seed card or free-text query."""

    def __init__(self, repository, *, use_pgvector: bool | None = None) -> None:
        self.repository = repository
        if use_pgvector is None:
            use_pgvector = os.getenv("MTG_USE_PGVECTOR", "").lower() in {"1", "true", "yes"}
        self.use_pgvector = use_pgvector and self._pgvector_available()
        self._feature_cache: dict[str, Counter] = {}

    # -- public API -----------------------------------------------------

    def similar_to(self, card_name: str, *, k: int = 10) -> list[RetrievalHit]:
        seed = self.repository.get_card(card_name)
        if seed is None:
            return []
        if self.use_pgvector:
            hits = self._pgvector_neighbors(card_name, k)
            if hits:
                return hits
            logger.info("pgvector returned no rows for %s; using lexical fallback", card_name)
        seed_feats = _featurize(seed)
        return self._rank(seed_feats, k=k, exclude={self._norm(card_name)})

    def search(self, query_text: str, *, k: int = 10) -> list[RetrievalHit]:
        """Free-text semantic-ish search via the lexical features."""
        query_feats: Counter = Counter()
        for tok in _TOKEN_RE.findall(query_text.lower()):
            if tok in _STOPWORDS or len(tok) <= 2:
                continue
            query_feats[f"o:{tok}"] += 1.0
            query_feats[f"type:{tok}"] += 1.0
        return self._rank(query_feats, k=k, exclude=set())

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
