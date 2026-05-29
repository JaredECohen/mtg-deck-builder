"""Deterministic card embeddings.

A real deployment would back this with a learned text-embedding model
(OpenAI, Cohere, a local SBERT). That requires network + a model, which
isn't available everywhere, so the default embedder here is a
**deterministic feature-hashing** projection of the shared card features
into a fixed-dimension L2-normalized vector.

Properties that make it a drop-in for the pgvector path:

* deterministic across processes (hashing via blake2b, *not* the
  salted builtin ``hash``), so embeddings are stable and reproducible;
* cosine similarity over these vectors approximates the lexical-feature
  cosine, so retrieval quality degrades gracefully vs. a learned model;
* dimensionality is fixed (``EMBEDDING_DIM``), matching a
  ``vector(EMBEDDING_DIM)`` pgvector column.

Swap ``embed_features`` for a model call when one is provisioned; the
table schema, ingest script, and retriever don't change.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter

from app.services.card_features import featurize, featurize_text

EMBEDDING_DIM = 256
EMBEDDING_MODEL = f"feature-hash-v1-d{EMBEDDING_DIM}"


def _stable_hash(key: str) -> int:
    """Process-stable hash (builtin hash() is salted per run)."""
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def embed_features(feats: Counter, *, dim: int = EMBEDDING_DIM) -> list[float]:
    """Hash a feature Counter into a signed, L2-normalized dense vector."""
    vec = [0.0] * dim
    for key, weight in feats.items():
        h = _stable_hash(key)
        idx = h % dim
        sign = 1.0 if (h >> 1) % 2 == 0 else -1.0  # signed hashing cuts collision bias
        vec[idx] += sign * float(weight)
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0.0:
        vec = [x / norm for x in vec]
    return vec


def embed_card(card, *, dim: int = EMBEDDING_DIM) -> list[float]:
    return embed_features(featurize(card), dim=dim)


def embed_text(text: str, *, dim: int = EMBEDDING_DIM) -> list[float]:
    return embed_features(featurize_text(text), dim=dim)


def cosine_dense(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def load_card_embeddings(session_factory=None) -> dict[str, list[float]]:
    """Load all stored embeddings as {name: vector}. Returns {} on any
    failure (missing table, no DB) so callers fall back to lexical."""
    try:
        from app.db_models import CardEmbedding
        if session_factory is not None:
            session = session_factory()
        else:
            from app.db import _get_session_factory
            session = _get_session_factory()()
        try:
            return {row.name: list(row.vector) for row in session.query(CardEmbedding)}
        finally:
            session.close()
    except Exception:  # noqa: BLE001 — missing table / no DB / etc.
        return {}
