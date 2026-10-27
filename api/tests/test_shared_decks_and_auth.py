"""Public deck pages, secret scrubbing, and optional magic-link accounts."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
import app.services.auth_service as auth_module
import app.services.deck_history_service as history_module
from app.main import app
from app.services.auth_service import AuthService, _send_magic_link
from app.services.deck_history_service import DeckHistoryService

client = TestClient(app)

_DECK = {
    "name": "Modern Burn",
    "format": "modern",
    "mainboard": [
        {"name": "Lightning Bolt", "quantity": 4},
        {"name": "Mountain", "quantity": 20},
    ],
    "colors": ["R"],
    "price_usd": 42.5,
    "card_notes": [{"name": "Lightning Bolt", "role": "removal", "reason": "Kills a creature or a player."}],
    "mana_curve": [{"mana_value": 1, "card_count": 4}],
    "card_types": {"Lightning Bolt": "Instant", "Mountain": "Land"},
    "key_cards": ["Lightning Bolt"],
    "notes": "Burn them out.",
}


def _engine():
    return create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def isolated(monkeypatch):
    engine = _engine()
    factory = sessionmaker(bind=engine, future=True)
    history = DeckHistoryService(session_factory=factory)
    accounts = AuthService(session_factory=factory)
    monkeypatch.setattr(main_module, "deck_history", history)
    monkeypatch.setattr(auth_module, "auth_service", accounts)
    monkeypatch.delenv("MTG_API_KEY", raising=False)
    monkeypatch.delenv("MTG_AUTH_DEBUG", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("AUTH_FROM_EMAIL", raising=False)
    return history, accounts


def _sign_in(email: str, monkeypatch, api_key: str | None = None) -> dict:
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    headers = {"X-API-Key": api_key} if api_key else {}
    requested = client.post("/v1/auth/magic-link", json={"email": email}, headers=headers)
    assert requested.status_code == 200, requested.text
    token = parse_qs(urlparse(requested.json()["debug_url"]).query)["token"][0]
    verified = client.post("/v1/auth/verify", json={"token": token}, headers=headers)
    assert verified.status_code == 200, verified.text
    return verified.json()


def test_share_snapshot_roundtrip_and_public_index(isolated):
    saved = client.post("/v1/decks/save", json=_DECK)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["visibility"] == "public"
    assert "owner" not in body

    shared = client.get(f"/v1/decks/shared/{body['share_token']}")
    assert shared.status_code == 200, shared.text
    deck = shared.json()
    assert deck["card_notes"][0]["reason"] == "Kills a creature or a player."
    assert deck["mana_curve"] == [{"mana_value": 1, "card_count": 4}]
    assert deck["colors"] == ["R"]
    assert deck["price_usd"] == 42.5
    assert deck["key_cards"] == ["Lightning Bolt"]
    assert deck["card_types"]["Mountain"] == "Land"
    assert "owner" not in deck

    listed = client.get("/v1/decks/public").json()["decks"]
    assert len(listed) == 1
    assert set(listed[0]) == {"share_token", "updated_at"}
    assert listed[0]["share_token"] == body["share_token"]


def test_unlisted_decks_stay_reachable_and_out_of_the_index(isolated):
    saved = client.post("/v1/decks/save", json={**_DECK, "name": "Private", "visibility": "unlisted"}).json()
    assert client.get(f"/v1/decks/shared/{saved['share_token']}").json()["visibility"] == "unlisted"
    assert client.get("/v1/decks/public").json()["decks"] == []


def test_key_cards_default_to_nonlands(isolated):
    payload = {key: value for key, value in _DECK.items() if key != "key_cards"}
    saved = client.post("/v1/decks/save", json=payload).json()
    assert saved["key_cards"] == ["Lightning Bolt"]


def test_shared_payload_never_contains_secrets_or_the_account(isolated, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    monkeypatch.setenv("RESEND_API_KEY", "re_live_secret_value")
    signed = _sign_in("pilot@example.com", monkeypatch, "server-key-123")
    session = signed["session_token"]
    headers = {"X-API-Key": "server-key-123", "X-User-Session": session}
    payload = {
        **_DECK,
        "name": "server-key-123 burn",
        "notes": f"session {session} and re_live_secret_value",
        "evaluation": {"owner": "server-key-123", "api_key": "re_live_secret_value", "win_rate": 0.5},
        "card_notes": [{
            "name": "Lightning Bolt",
            "role": "removal",
            "reason": "Uses server-key-123",
        }],
    }
    saved = client.post("/v1/decks/save", json=payload, headers=headers)
    assert saved.status_code == 200, saved.text
    responses = [
        saved,
        client.get(f"/v1/decks/shared/{saved.json()['share_token']}"),
        client.get("/v1/decks/history", headers=headers),
        client.get("/v1/decks/public"),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        assert "server-key-123" not in response.text
        assert session not in response.text
        assert "re_live_secret_value" not in response.text
        assert "pilot@example.com" not in response.text
        assert '"owner"' not in response.text
        assert '"api_key"' not in response.text
        assert '"email"' not in response.text

    engine = isolated[0]._session_factory.kw["bind"]
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT notes, name, owner FROM saved_decks")).one()
    assert "server-key-123" not in stored.notes
    assert session not in stored.notes
    assert stored.owner.startswith("user:")
    assert "pilot@example.com" not in stored.owner


def test_anonymous_save_still_works_and_user_libraries_stay_separate(isolated, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    anon = client.post(
        "/v1/decks/save",
        json={"name": "Anon deck", "format": "modern", "mainboard": [{"name": "Mountain", "quantity": 1}]},
        headers={"X-API-Key": "server-key-123"},
    )
    assert anon.status_code == 200, anon.text
    key_history = client.get("/v1/decks/history", headers={"X-API-Key": "server-key-123"}).json()["decks"]
    assert [deck["name"] for deck in key_history] == ["Anon deck"]

    alice = _sign_in("alice@example.com", monkeypatch, "server-key-123")
    bob = _sign_in("bob@example.com", monkeypatch, "server-key-123")
    alice_headers = {"X-API-Key": "server-key-123", "X-User-Session": alice["session_token"]}
    bob_headers = {"X-API-Key": "server-key-123", "X-User-Session": bob["session_token"]}
    saved = client.post(
        "/v1/decks/save",
        json={"name": "Alice deck", "format": "legacy", "mainboard": [{"name": "Brainstorm", "quantity": 4}]},
        headers=alice_headers,
    )
    assert saved.status_code == 200, saved.text
    deck_id = saved.json()["id"]

    assert [deck["name"] for deck in client.get("/v1/decks/history", headers=alice_headers).json()["decks"]] == ["Alice deck"]
    assert client.get("/v1/decks/history", headers=bob_headers).json()["decks"] == []
    # The site-wide API key does not see the personal library.
    assert [deck["name"] for deck in client.get("/v1/decks/history", headers={"X-API-Key": "server-key-123"}).json()["decks"]] == ["Anon deck"]
    # The share link still opens it.
    assert client.get(f"/v1/decks/shared/{saved.json()['share_token']}").status_code == 200

    renamed = client.patch(f"/v1/decks/saved/{deck_id}", json={"name": "Alice renamed", "visibility": "unlisted"}, headers=alice_headers)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Alice renamed"
    assert renamed.json()["visibility"] == "unlisted"
    assert client.patch(
        f"/v1/decks/saved/{deck_id}", json={"name": "Hijacked"}, headers={"X-API-Key": "server-key-123"}
    ).status_code == 404
    assert client.patch(f"/v1/decks/saved/{deck_id}", json={"name": "Bob's"}, headers=bob_headers).status_code == 404
    assert client.delete(f"/v1/decks/saved/{deck_id}", headers=bob_headers).status_code == 404
    assert client.get(f"/v1/decks/shared/{saved.json()['share_token']}").json()["name"] == "Alice renamed"

    # Reopen by id is limited to the owner.
    assert client.get(f"/v1/decks/saved/{deck_id}", headers=alice_headers).json()["name"] == "Alice renamed"
    assert client.delete(f"/v1/decks/saved/{deck_id}", headers=alice_headers).status_code == 200
    assert client.get(f"/v1/decks/shared/{saved.json()['share_token']}").status_code == 404


def test_user_libraries_stay_hidden_when_api_key_auth_is_off(isolated):
    history, _accounts = isolated
    history.save(name="Personal", format_id="modern", mainboard=[], owner="user:abc")
    client.post("/v1/decks/save", json={"name": "Open", "format": "modern", "mainboard": [{"name": "Island", "quantity": 1}]})
    names = [deck["name"] for deck in client.get("/v1/decks/history").json()["decks"]]
    assert names == ["Open"]
    assert client.get("/v1/decks/saved/" + history.history(owner="user:abc")[0]["id"]).status_code == 404


def test_magic_link_is_single_use_and_hidden_without_debug(isolated, monkeypatch):
    quiet = client.post("/v1/auth/magic-link", json={"email": "Pilot@Example.com"})
    assert quiet.status_code == 200
    assert quiet.json() == {"ok": True}
    assert "token" not in quiet.text
    assert "debug_url" not in quiet.text

    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    requested = client.post("/v1/auth/magic-link", json={"email": "Pilot@Example.com"})
    assert requested.status_code == 200, requested.text
    token = parse_qs(urlparse(requested.json()["debug_url"]).query)["token"][0]
    first = client.post("/v1/auth/verify", json={"token": token})
    assert first.status_code == 200, first.text
    assert first.json()["user"]["email"] == "pilot@example.com"
    session = first.json()["session_token"]
    assert client.post("/v1/auth/verify", json={"token": token}).status_code == 400

    me = client.get("/v1/auth/me", headers={"X-User-Session": session})
    assert me.json()["user"]["email"] == "pilot@example.com"
    assert client.get("/v1/auth/me").status_code == 401
    assert client.post("/v1/auth/logout", headers={"X-User-Session": session}).status_code == 200
    assert client.get("/v1/auth/me", headers={"X-User-Session": session}).status_code == 401


def test_magic_link_claimed_by_another_request_mints_no_second_session(isolated, monkeypatch):
    _, accounts = isolated
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    requested = client.post("/v1/auth/magic-link", json={"email": "race@example.com"})
    token = parse_qs(urlparse(requested.json()["debug_url"]).query)["token"][0]

    # Simulate a concurrent verify that claims the link after this request read
    # it (used_at still unset) and before this request claims it.
    real_session = accounts._session

    def racing_session():
        session = real_session()
        original_query = session.query
        token_queries = 0

        def query(*entities):
            nonlocal token_queries
            if entities and entities[0] is auth_module.LoginToken:
                token_queries += 1
                if token_queries == 2:
                    session.execute(text("UPDATE login_tokens SET used_at = 'claimed'"))
            return original_query(*entities)

        session.query = query
        return session

    monkeypatch.setattr(accounts, "_session", racing_session)
    assert accounts.verify(token) is None
    monkeypatch.setattr(accounts, "_session", real_session)
    check = real_session()
    try:
        assert check.query(auth_module.AuthSession).count() == 0
    finally:
        check.close()


def test_expired_magic_link_is_rejected(isolated, monkeypatch):
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    requested = client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}).json()
    token = parse_qs(urlparse(requested["debug_url"]).query)["token"][0]
    engine = isolated[1]._session_factory.kw["bind"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE login_tokens SET expires_at = '2000-01-01T00:00:00+00:00'"))
    assert client.post("/v1/auth/verify", json={"token": token}).status_code == 400


def test_invalid_email_and_sign_in_rate_limit(isolated):
    isolated[1]._ensure()
    assert client.post("/v1/auth/magic-link", json={"email": "not-an-email"}).status_code == 400
    engine = isolated[1]._session_factory.kw["bind"]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM login_tokens")).scalar() == 0
    for _ in range(5):
        assert client.post("/v1/auth/magic-link", json={"email": "rate@example.com"}).status_code == 200
    assert client.post("/v1/auth/magic-link", json={"email": "rate@example.com"}).status_code == 429


def test_delete_account_removes_library_and_session(isolated, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    signed = _sign_in("pilot@example.com", monkeypatch, "server-key-123")
    headers = {"X-API-Key": "server-key-123", "X-User-Session": signed["session_token"]}
    saved = client.post(
        "/v1/decks/save",
        json={"name": "Mine", "format": "modern", "mainboard": [{"name": "Bolt", "quantity": 1}]},
        headers=headers,
    ).json()
    deleted = client.delete("/v1/auth/me", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"deleted": True}
    assert "pilot@example.com" not in deleted.text
    assert client.get("/v1/auth/me", headers=headers).status_code == 401
    assert client.get(f"/v1/decks/shared/{saved['share_token']}").status_code == 404
    assert client.get("/v1/decks/history", headers=headers).json()["decks"] == []


def test_magic_link_requires_the_api_key_when_auth_is_enabled(isolated, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    assert client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}).status_code == 401
    allowed = client.post(
        "/v1/auth/magic-link",
        json={"email": "pilot@example.com"},
        headers={"X-API-Key": "server-key-123"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json() == {"ok": True}


def test_resend_payload_contains_the_link_and_not_api_keys(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_live_secret_value")
    monkeypatch.setenv("AUTH_FROM_EMAIL", "MTG Deck Lab <decks@mtgdecklab.app>")
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    captured: dict[str, str] = {}

    class _Response:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=0):
        captured["body"] = request.data.decode()
        captured["auth"] = request.headers["Authorization"]
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _send_magic_link("pilot@example.com", "https://mtgdecklab.app/auth/verify?token=abc")
    body = json.loads(captured["body"])
    assert body["to"] == ["pilot@example.com"]
    assert "https://mtgdecklab.app/auth/verify?token=abc" in body["text"]
    assert "re_live_secret_value" not in captured["body"]
    assert "server-key-123" not in captured["body"]
    assert captured["auth"] == "Bearer re_live_secret_value"


def test_added_columns_migrate_in_place():
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE saved_decks ("
            "id VARCHAR(64) PRIMARY KEY, share_token VARCHAR(64), owner VARCHAR(255), "
            "name VARCHAR(255), format VARCHAR(32), commander VARCHAR(255), "
            "mainboard JSON, sideboard JSON, notes TEXT, evaluation JSON, "
            "created_at VARCHAR(32), updated_at VARCHAR(32))"
        ))
        conn.execute(text(
            "INSERT INTO saved_decks VALUES ("
            "'id1', 'tok1', NULL, 'Old', 'modern', NULL, "
            "'[]', '[]', '', '{}', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        ))
    history = DeckHistoryService(session_factory=sessionmaker(bind=engine, future=True))
    deck = history.get_by_share_token("tok1")
    assert deck is not None
    assert deck["name"] == "Old"
    # Saved before decks could be public: stays a link-only share.
    assert deck["visibility"] == "unlisted"
    assert history.public_index() == []
    assert deck["card_notes"] == []
    assert deck["mana_curve"] == []
    assert deck["key_cards"] == []


def test_user_owner_ids_are_not_hashed_on_startup():
    engine = _engine()
    history = DeckHistoryService(session_factory=sessionmaker(bind=engine, future=True))
    history.save(name="Library", format_id="modern", mainboard=[], owner="user:abc123")
    history.save(name="Legacy key", format_id="modern", mainboard=[], owner="raw-secret-key")
    with engine.begin() as conn:
        conn.execute(text("UPDATE saved_decks SET owner = 'raw-secret-key' WHERE name = 'Legacy key'"))
    history_module._ready_engines.discard(id(engine))
    assert history.history(owner="user:abc123")[0]["name"] == "Library"
    with engine.connect() as conn:
        owners = dict(conn.execute(text("SELECT name, owner FROM saved_decks")).all())
    assert owners["Library"] == "user:abc123"
    assert owners["Legacy key"] != "raw-secret-key"
    assert owners["Legacy key"].startswith("key:")
