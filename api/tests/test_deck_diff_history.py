"""Tests for deck diff + persistent deck history / sharing."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.main import app
from app.services.deck_diff import diff_decks
from app.services.deck_history_service import DeckHistoryService

client = TestClient(app)


# --- diff --------------------------------------------------------------


def test_diff_detects_add_remove_and_quantity_changes():
    before = [{"name": "Bolt", "quantity": 4}, {"name": "Goblin", "quantity": 4},
              {"name": "Mountain", "quantity": 20}]
    after = [{"name": "Bolt", "quantity": 2}, {"name": "Goblin", "quantity": 4},
             {"name": "Mountain", "quantity": 21}, {"name": "Eidolon", "quantity": 3}]
    d = diff_decks(before, after).to_dict()
    assert {"name": "Eidolon", "quantity": 3} in d["added"]
    assert any(e["name"] == "Bolt" and e["delta"] == 2 for e in d["decreased"])
    assert any(e["name"] == "Mountain" and e["delta"] == 1 for e in d["increased"])
    assert {"name": "Goblin", "quantity": 4} in d["unchanged"]
    assert not d["summary"]["identical"]


def test_diff_identical_decks():
    deck = [{"name": "Bolt", "quantity": 4}]
    d = diff_decks(deck, deck).to_dict()
    assert d["summary"]["identical"] is True
    assert d["summary"]["total_changes"] == 0


def test_diff_endpoint():
    resp = client.post("/v1/decks/diff", json={
        "before": [{"name": "Bolt", "quantity": 4}],
        "after": [{"name": "Bolt", "quantity": 3}, {"name": "Spike", "quantity": 1}],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["total_changes"] == 2


# --- history (isolated in-memory DB) -----------------------------------


@pytest.fixture
def isolated_history(monkeypatch):
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    sf = sessionmaker(bind=engine, future=True)
    svc = DeckHistoryService(session_factory=sf)
    monkeypatch.setattr(main_module, "deck_history", svc)
    monkeypatch.delenv("MTG_API_KEY", raising=False)
    return svc


def test_save_list_share_and_delete_roundtrip(isolated_history):
    payload = {
        "name": "Modern Burn",
        "format": "modern",
        "mainboard": [{"name": "Lightning Bolt", "quantity": 4}],
    }
    saved = client.post("/v1/decks/save", json=payload).json()
    assert saved["name"] == "Modern Burn"
    assert saved["share_token"]

    # Appears in history.
    history = client.get("/v1/decks/history").json()["decks"]
    assert any(d["id"] == saved["id"] for d in history)

    # Fetch by id and by share token.
    assert client.get(f"/v1/decks/saved/{saved['id']}").json()["name"] == "Modern Burn"
    assert client.get(f"/v1/decks/shared/{saved['share_token']}").json()["id"] == saved["id"]

    # Delete.
    assert client.delete(f"/v1/decks/saved/{saved['id']}").status_code == 200
    assert client.get(f"/v1/decks/saved/{saved['id']}").status_code == 404


def test_get_unknown_saved_deck_404(isolated_history):
    assert client.get("/v1/decks/saved/nope").status_code == 404
    assert client.get("/v1/decks/shared/nope").status_code == 404


def test_history_scoped_by_owner(isolated_history, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "alice-key")
    payload = {"name": "Alice deck", "format": "modern",
               "mainboard": [{"name": "Lightning Bolt", "quantity": 4}]}
    client.post("/v1/decks/save", json=payload, headers={"X-API-Key": "alice-key"})
    # Alice sees her deck.
    alice = client.get("/v1/decks/history", headers={"X-API-Key": "alice-key"}).json()["decks"]
    assert len(alice) == 1 and alice[0]["owner"] == "alice-key"
