"""Tests for deck diff + persistent deck history / sharing."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.main import app
from app.services.deck_diff import diff_decks
from app.services.deck_history_service import DeckHistoryService, owner_id

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
    assert len(alice) == 1 and alice[0]["name"] == "Alice deck"


_DECK = {"name": "Keyed deck", "format": "modern",
         "mainboard": [{"name": "Lightning Bolt", "quantity": 4}]}


def test_no_response_ever_contains_the_api_key_or_owner(isolated_history, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "alice-key,bob-key")
    alice = {"X-API-Key": "alice-key"}
    saved = client.post("/v1/decks/save", json=_DECK, headers=alice)
    responses = [
        saved,
        client.get("/v1/decks/history", headers=alice),
        client.get(f"/v1/decks/saved/{saved.json()['id']}", headers=alice),
        client.get(f"/v1/decks/shared/{saved.json()['share_token']}"),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        assert "alice-key" not in response.text
        assert '"owner"' not in response.text


def test_owner_is_stored_hashed(isolated_history, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "alice-key")
    saved = client.post("/v1/decks/save", json=_DECK, headers={"X-API-Key": "alice-key"}).json()
    engine = isolated_history._session_factory.kw["bind"]
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT owner FROM saved_decks WHERE id = :id"), {"id": saved["id"]}).scalar()
    assert stored == owner_id("alice-key")
    assert "alice-key" not in stored


def test_saved_by_id_requires_key_and_ownership(isolated_history, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "alice-key,bob-key")
    saved = client.post("/v1/decks/save", json=_DECK, headers={"X-API-Key": "alice-key"}).json()
    url = f"/v1/decks/saved/{saved['id']}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"X-API-Key": "bob-key"}).status_code == 404
    assert client.delete(url, headers={"X-API-Key": "bob-key"}).status_code == 404
    assert client.get(url, headers={"X-API-Key": "alice-key"}).status_code == 200
    # Bob's history does not include Alice's deck.
    bob = client.get("/v1/decks/history", headers={"X-API-Key": "bob-key"}).json()["decks"]
    assert bob == []
    # The share link stays public.
    assert client.get(f"/v1/decks/shared/{saved['share_token']}").status_code == 200


def _fresh_engine():
    return create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )


def test_legacy_saved_decks_table_is_set_aside(monkeypatch):
    """The deck-lab era table shares the name but not the schema; saving
    must not 500 on a database that still has it."""
    engine = _fresh_engine()
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE saved_decks (id VARCHAR(64) PRIMARY KEY, session_id VARCHAR(64) NOT NULL, "
            "title VARCHAR(255) NOT NULL, format VARCHAR(32) NOT NULL, deck_json JSON NOT NULL, "
            "created_at VARCHAR(32) NOT NULL, chat_history JSON DEFAULT '[]')"
        ))
        conn.execute(text("CREATE INDEX ix_saved_decks_format ON saved_decks (format)"))
        conn.execute(text(
            "INSERT INTO saved_decks VALUES ('old', 's', 'Old deck', 'modern', '{}', '2026-05-31', '[]')"
        ))
    svc = DeckHistoryService(session_factory=sessionmaker(bind=engine, future=True))
    monkeypatch.setattr(main_module, "deck_history", svc)
    monkeypatch.delenv("MTG_API_KEY", raising=False)

    response = client.post("/v1/decks/save", json=_DECK)
    assert response.status_code == 200, response.text
    tables = inspect(engine).get_table_names()
    legacy = [name for name in tables if name.startswith("saved_decks_legacy_")]
    assert len(legacy) == 1
    with engine.connect() as conn:
        assert conn.execute(text(f'SELECT title FROM "{legacy[0]}"')).scalar() == "Old deck"


def test_raw_key_owners_are_hashed_on_startup():
    engine = _fresh_engine()
    svc = DeckHistoryService(session_factory=sessionmaker(bind=engine, future=True))
    svc.save(name="pre-fix", format_id="modern", mainboard=[], owner="raw-secret-key")
    # Simulate a row written before hashing existed, then a restart.
    import app.services.deck_history_service as history_module
    history_module._ready_engines.discard(id(engine))
    with engine.begin() as conn:
        conn.execute(text("UPDATE saved_decks SET owner = 'raw-secret-key'"))
    assert svc.history(owner=owner_id("raw-secret-key"))[0]["name"] == "pre-fix"
