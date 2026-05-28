"""Shared card featurization used by both lexical retrieval and the
embedding pipeline.

Keeping this in one place means the stored embeddings and the lexical
fallback describe cards the *same* way — so the two retrieval modes
agree on what "similar" means.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "for", "with", "this", "that",
    "you", "your", "it", "its", "is", "are", "be", "as", "at", "on", "in",
    "from", "up", "may", "if", "then", "each", "any", "all", "card", "cards",
    "target", "control", "controls", "player", "players", "into", "onto",
}


def _get(card, field: str, default=""):
    if isinstance(card, dict):
        return card.get(field, default)
    return getattr(card, field, default)


def featurize(card) -> Counter:
    """Bag-of-features for a card record (dataclass or dict)."""
    feats: Counter = Counter()
    type_line = str(_get(card, "type_line", "")).lower()
    for tok in _TOKEN_RE.findall(type_line):
        feats[f"type:{tok}"] += 2.0  # type is a strong signal
    for color in _get(card, "color_identity", []) or []:
        feats[f"ci:{color}"] += 1.5
    for kw in _get(card, "keywords", []) or []:
        feats[f"kw:{str(kw).lower()}"] += 1.5
    for tag in _get(card, "tags", []) or []:
        feats[f"tag:{str(tag).lower()}"] += 1.0
    oracle = str(_get(card, "oracle_text", "")).lower()
    for tok in _TOKEN_RE.findall(oracle):
        if tok in _STOPWORDS or len(tok) <= 2:
            continue
        feats[f"o:{tok}"] += 1.0
    mv = _get(card, "mana_value", 0) or 0
    try:
        feats[f"mv:{int(float(mv))}"] += 0.5
    except (TypeError, ValueError):
        pass
    return feats


def featurize_text(text: str) -> Counter:
    """Featurize a free-text query the same way a card's oracle/type is."""
    feats: Counter = Counter()
    for tok in _TOKEN_RE.findall(text.lower()):
        if tok in _STOPWORDS or len(tok) <= 2:
            continue
        feats[f"o:{tok}"] += 1.0
        feats[f"type:{tok}"] += 1.0
    return feats


def cosine(a: Counter, b: Counter) -> float:
    """Sparse cosine similarity between two feature Counters."""
    if not a or not b:
        return 0.0
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    dot = sum(w * big.get(k, 0.0) for k, w in small.items())
    if dot == 0.0:
        return 0.0
    na = math.sqrt(sum(w * w for w in a.values()))
    nb = math.sqrt(sum(w * w for w in b.values()))
    return dot / (na * nb) if na and nb else 0.0
