"""Tests for semantic card retrieval (lexical fallback path)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.card_repository import CardRepository
from app.services.vector_retrieval import CardVectorRetriever, _cosine, _featurize

client = TestClient(app)


def test_retriever_uses_lexical_fallback_without_pgvector():
    r = CardVectorRetriever(CardRepository(), use_pgvector=False)
    assert r.use_pgvector is False


def test_similar_to_red_burn_surfaces_other_red_damage():
    r = CardVectorRetriever(CardRepository(), use_pgvector=False)
    hits = r.similar_to("Lightning Bolt", k=5)
    assert hits, "expected at least one similar card"
    names = [h.name for h in hits]
    assert "Lightning Bolt" not in names  # seed excluded
    # Lava Dart is the other red one-mana damage instant in the sample.
    assert "Lava Dart" in names
    # Scores are sorted descending and bounded.
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_search_free_text_returns_results():
    r = CardVectorRetriever(CardRepository(), use_pgvector=False)
    hits = r.search("deal damage to any target", k=5)
    assert hits
    assert all(0.0 <= h.score <= 1.0 for h in hits)


def test_cosine_identical_features_is_one():
    feats = _featurize({"type_line": "Instant", "oracle_text": "deal 3 damage",
                        "color_identity": ["R"]})
    assert abs(_cosine(feats, feats) - 1.0) < 1e-9
    assert _cosine(feats, type(feats)()) == 0.0


def test_similar_endpoint_404_for_unknown_card():
    resp = client.get("/v1/cards/Totally Made Up Card/similar")
    assert resp.status_code == 404


def test_similar_endpoint_returns_neighbours():
    resp = client.get("/v1/cards/Lightning Bolt/similar", params={"k": 5})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "lexical"
    assert isinstance(body["similar"], list) and body["similar"]
