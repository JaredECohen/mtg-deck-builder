"""Public deck pages, secret scrubbing, and optional magic-link accounts."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
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
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("MTG_AUTH_DAILY_EMAIL_CAP", raising=False)
    return history, accounts


def _link_headers(api_key: str | None = None, preauth: str | None = None) -> tuple[dict[str, str], str]:
    secret = preauth or secrets.token_urlsafe(32)
    headers = {"X-Preauth": secret}
    if api_key:
        headers["X-API-Key"] = api_key
    return headers, secret


def _sign_in(email: str, monkeypatch, api_key: str | None = None) -> dict:
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    headers, preauth = _link_headers(api_key)
    requested = client.post("/v1/auth/magic-link", json={"email": email}, headers=headers)
    assert requested.status_code == 200, requested.text
    token = parse_qs(urlparse(requested.json()["debug_url"]).query)["token"][0]
    verify_headers = {"X-API-Key": api_key} if api_key else {}
    verified = client.post("/v1/auth/verify", json={"token": token, "preauth": preauth}, headers=verify_headers)
    assert verified.status_code == 200, verified.text
    return verified.json()


def test_share_snapshot_roundtrip_and_public_index(isolated):
    saved = client.post("/v1/decks/save", json={**_DECK, "visibility": "public"})
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
    anon_id = anon.json()["id"]
    key_history = client.get("/v1/decks/history", headers={"X-API-Key": "server-key-123"})
    assert key_history.status_code == 401
    assert anon_id not in key_history.text

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

    alice_list = client.get("/v1/decks/history", headers=alice_headers)
    assert [deck["name"] for deck in alice_list.json()["decks"]] == ["Alice deck"]
    assert anon_id not in alice_list.text
    assert client.get("/v1/decks/history", headers=bob_headers).json()["decks"] == []
    # The site-wide API key does not see the personal library or the anonymous id.
    shared_key = client.get("/v1/decks/history", headers={"X-API-Key": "server-key-123"})
    assert shared_key.status_code == 401
    assert anon_id not in shared_key.text
    assert deck_id not in shared_key.text
    # The share link still opens it.
    assert client.get(f"/v1/decks/shared/{saved.json()['share_token']}").status_code == 200

    renamed = client.patch(f"/v1/decks/saved/{deck_id}", json={"name": "Alice renamed", "visibility": "unlisted"}, headers=alice_headers)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Alice renamed"
    assert renamed.json()["visibility"] == "unlisted"
    assert client.patch(
        f"/v1/decks/saved/{deck_id}", json={"name": "Hijacked", "visibility": "public"}, headers={"X-API-Key": "server-key-123"}
    ).status_code == 401
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
    listed = client.get("/v1/decks/history")
    assert listed.status_code == 401
    open_id = history.history(owner=None)[0]["id"]
    assert open_id not in listed.text
    assert client.get("/v1/decks/saved/" + history.history(owner="user:abc")[0]["id"]).status_code == 404


def test_magic_link_is_single_use_and_hidden_without_debug(isolated, monkeypatch):
    quiet_headers, quiet_preauth = _link_headers()
    quiet = client.post("/v1/auth/magic-link", json={"email": "Pilot@Example.com"}, headers=quiet_headers)
    assert quiet.status_code == 200
    assert quiet.json() == {"ok": True}
    assert "token" not in quiet.text
    assert "debug_url" not in quiet.text
    assert quiet_preauth not in quiet.text

    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    headers, preauth = _link_headers()
    requested = client.post("/v1/auth/magic-link", json={"email": "Pilot@Example.com"}, headers=headers)
    assert requested.status_code == 200, requested.text
    token = parse_qs(urlparse(requested.json()["debug_url"]).query)["token"][0]
    first = client.post("/v1/auth/verify", json={"token": token, "preauth": preauth})
    assert first.status_code == 200, first.text
    assert first.json()["user"]["email"] == "pilot@example.com"
    session = first.json()["session_token"]
    assert client.post("/v1/auth/verify", json={"token": token, "preauth": preauth}).status_code == 400

    me = client.get("/v1/auth/me", headers={"X-User-Session": session})
    assert me.json()["user"]["email"] == "pilot@example.com"
    assert client.get("/v1/auth/me").status_code == 401
    assert client.post("/v1/auth/logout", headers={"X-User-Session": session}).status_code == 200
    assert client.get("/v1/auth/me", headers={"X-User-Session": session}).status_code == 401


def test_magic_link_claimed_by_another_request_mints_no_second_session(isolated, monkeypatch):
    _, accounts = isolated
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    headers, preauth = _link_headers()
    requested = client.post("/v1/auth/magic-link", json={"email": "race@example.com"}, headers=headers)
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
    assert accounts.verify(token, preauth) is None
    monkeypatch.setattr(accounts, "_session", real_session)
    check = real_session()
    try:
        assert check.query(auth_module.AuthSession).count() == 0
    finally:
        check.close()


def test_expired_magic_link_is_rejected(isolated, monkeypatch):
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    headers, preauth = _link_headers()
    requested = client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}, headers=headers).json()
    token = parse_qs(urlparse(requested["debug_url"]).query)["token"][0]
    engine = isolated[1]._session_factory.kw["bind"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE login_tokens SET expires_at = '2000-01-01T00:00:00+00:00'"))
    assert client.post("/v1/auth/verify", json={"token": token, "preauth": preauth}).status_code == 400


def test_invalid_email_and_sign_in_rate_limit(isolated):
    isolated[1]._ensure()
    assert client.post("/v1/auth/magic-link", json={"email": "not-an-email"}).status_code == 400
    engine = isolated[1]._session_factory.kw["bind"]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM login_tokens")).scalar() == 0
    for _ in range(5):
        headers, _preauth = _link_headers()
        assert client.post("/v1/auth/magic-link", json={"email": "rate@example.com"}, headers=headers).status_code == 200
    headers, _preauth = _link_headers()
    assert client.post("/v1/auth/magic-link", json={"email": "rate@example.com"}, headers=headers).status_code == 429


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
    listed = client.get("/v1/decks/history", headers=headers)
    assert listed.status_code == 401
    assert saved["id"] not in listed.text


def test_magic_link_requires_the_api_key_when_auth_is_enabled(isolated, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    assert client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}).status_code == 401
    headers, _preauth = _link_headers("server-key-123")
    allowed = client.post(
        "/v1/auth/magic-link",
        json={"email": "pilot@example.com"},
        headers=headers,
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
    assert "press Sign in" in body["text"]
    assert "another device" in body["text"]
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
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(saved_decks)"))}
    assert "edit_secret_hash" in columns


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


def test_omitted_visibility_stays_out_of_the_index(isolated):
    saved = client.post(
        "/v1/decks/save",
        json={"name": "Quiet", "format": "modern", "mainboard": [{"name": "Island", "quantity": 1}]},
    ).json()
    assert saved["visibility"] == "unlisted"
    assert "edit_secret" in saved
    shared = client.get(f"/v1/decks/shared/{saved['share_token']}")
    assert shared.json()["visibility"] == "unlisted"
    assert "edit_secret" not in shared.text
    assert saved["edit_secret"] not in shared.text
    assert client.get("/v1/decks/public").json()["decks"] == []


def test_forged_session_cannot_list_rename_publish_or_delete_anonymous_decks(isolated, monkeypatch):
    """A cookie that only matches the shape check is not the shared API-key owner."""
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    key = {"X-API-Key": "server-key-123"}
    saved = client.post(
        "/v1/decks/save",
        json={"name": "Anon", "format": "modern", "mainboard": [{"name": "Mountain", "quantity": 1}], "visibility": "unlisted"},
        headers=key,
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    deck_id = body["id"]
    secret = body["edit_secret"]
    forged = {**key, "X-User-Session": "a" * 32}
    expired_shape = {**key, "X-User-Session": "nope"}

    for headers in (forged, expired_shape, key):
        listed = client.get("/v1/decks/history", headers=headers)
        assert listed.status_code == 401, listed.text
        assert deck_id not in listed.text
        published = client.patch(
            f"/v1/decks/saved/{deck_id}",
            json={"name": "Hijacked", "visibility": "public"},
            headers=headers,
        )
        assert published.status_code == 401, published.text

    fetched = client.get(f"/v1/decks/saved/{deck_id}", headers=forged)
    assert fetched.status_code == 401
    assert deck_id not in fetched.text
    assert client.delete(f"/v1/decks/saved/{deck_id}", headers=forged).status_code == 401
    assert client.delete(f"/v1/decks/saved/{deck_id}", headers=key).status_code == 404
    assert client.delete(
        f"/v1/decks/saved/{deck_id}",
        headers={**key, "X-Deck-Edit-Secret": "wrong-secret-value-0123456789"},
    ).status_code == 404
    shared = client.get(f"/v1/decks/shared/{body['share_token']}")
    assert shared.status_code == 200
    assert shared.json()["name"] == "Anon"
    assert shared.json()["visibility"] == "unlisted"
    assert client.get("/v1/decks/public").json()["decks"] == []

    deleted = client.delete(f"/v1/decks/saved/{deck_id}", headers={**key, "X-Deck-Edit-Secret": secret})
    assert deleted.status_code == 200, deleted.text
    assert client.get(f"/v1/decks/shared/{body['share_token']}").status_code == 404


def test_expired_session_does_not_fall_back_to_the_shared_owner(isolated, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    key = {"X-API-Key": "server-key-123"}
    anon = client.post(
        "/v1/decks/save",
        json={"name": "Anon", "format": "modern", "mainboard": [{"name": "Island", "quantity": 1}]},
        headers=key,
    ).json()
    signed = _sign_in("pilot@example.com", monkeypatch, "server-key-123")
    engine = isolated[1]._session_factory.kw["bind"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE auth_sessions SET expires_at = '2000-01-01T00:00:00+00:00'"))
    expired = {**key, "X-User-Session": signed["session_token"]}
    listed = client.get("/v1/decks/history", headers=expired)
    assert listed.status_code == 401
    assert anon["id"] not in listed.text
    assert client.post(
        "/v1/decks/save",
        json={"name": "Should not land in the shared library", "format": "modern", "mainboard": [{"name": "Swamp", "quantity": 1}]},
        headers=expired,
    ).status_code == 401
    assert client.delete(f"/v1/decks/saved/{anon['id']}", headers=expired).status_code == 401
    assert client.get(f"/v1/decks/shared/{anon['share_token']}").status_code == 200


def test_signed_in_user_can_rename_and_publish_only_their_deck(isolated, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    signed = _sign_in("pilot@example.com", monkeypatch, "server-key-123")
    headers = {"X-API-Key": "server-key-123", "X-User-Session": signed["session_token"]}
    saved = client.post(
        "/v1/decks/save",
        json={"name": "Mine", "format": "modern", "mainboard": [{"name": "Bolt", "quantity": 1}], "visibility": "unlisted"},
        headers=headers,
    ).json()
    assert "edit_secret" not in saved
    renamed = client.patch(
        f"/v1/decks/saved/{saved['id']}",
        json={"name": "Published", "visibility": "public"},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["visibility"] == "public"
    assert client.get("/v1/decks/public").json()["decks"][0]["share_token"] == saved["share_token"]
    assert client.delete(f"/v1/decks/saved/{saved['id']}", headers=headers).status_code == 200


def test_wrong_preauth_does_not_consume_the_magic_link(isolated, monkeypatch):
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    headers, preauth = _link_headers()
    requested = client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}, headers=headers)
    token = parse_qs(urlparse(requested.json()["debug_url"]).query)["token"][0]
    for extra in ({"preauth": "q" * 32}, {}):
        rejected = client.post("/v1/auth/verify", json={"token": token, **extra})
        assert rejected.status_code == 400, rejected.text
        assert rejected.json()["detail"]["code"] == "preauth_mismatch"
    accepted = client.post("/v1/auth/verify", json={"token": token, "preauth": preauth})
    assert accepted.status_code == 200, accepted.text


def test_new_magic_link_replaces_only_the_same_browsers_pending_link(isolated, monkeypatch):
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    alice_headers, alice_preauth = _link_headers()
    alice = client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}, headers=alice_headers)
    alice_token = parse_qs(urlparse(alice.json()["debug_url"]).query)["token"][0]
    bob_headers, bob_preauth = _link_headers()
    bob = client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}, headers=bob_headers)
    bob_token = parse_qs(urlparse(bob.json()["debug_url"]).query)["token"][0]
    # Another browser's request does not wipe the in-flight link.
    assert client.post("/v1/auth/verify", json={"token": alice_token, "preauth": alice_preauth}).status_code == 200
    # The same browser's next request replaces only its own unused link.
    again_headers, _same = _link_headers(preauth=bob_preauth)
    again = client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}, headers=again_headers)
    again_token = parse_qs(urlparse(again.json()["debug_url"]).query)["token"][0]
    assert client.post("/v1/auth/verify", json={"token": bob_token, "preauth": bob_preauth}).status_code == 400
    assert client.post("/v1/auth/verify", json={"token": again_token, "preauth": bob_preauth}).status_code == 200


def test_one_network_cannot_use_the_whole_email_budget(isolated, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    monkeypatch.setattr(auth_module, "EMAIL_NETWORK_DAILY_LIMIT", 1)
    monkeypatch.setattr(auth_module, "EMAIL_LIMIT", 100)
    monkeypatch.setattr(auth_module, "EMAIL_DAILY_LIMIT", 100)
    monkeypatch.setattr(auth_module, "IP_LIMIT", 100)
    monkeypatch.setattr(auth_module, "IP_DAILY_LIMIT", 100)
    monkeypatch.setenv("MTG_AUTH_DAILY_EMAIL_CAP", "1000")

    def post(ip: str, preauth: str | None = None):
        headers, secret = _link_headers("server-key-123", preauth)
        headers["X-Forwarded-For"] = ip
        response = client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}, headers=headers)
        return response, secret

    first, first_preauth = post("203.0.113.10")
    assert first.status_code == 200, first.text
    token = parse_qs(urlparse(first.json()["debug_url"]).query)["token"][0]
    blocked, _blocked_preauth = post("203.0.113.10")
    assert blocked.status_code == 429
    # The throttled request did not delete the pending link.
    assert client.post(
        "/v1/auth/verify",
        json={"token": token, "preauth": first_preauth},
        headers={"X-API-Key": "server-key-123"},
    ).status_code == 200
    other_network, _other = post("203.0.113.11")
    assert other_network.status_code == 200, other_network.text


def test_purge_removes_expired_tokens_and_sessions(isolated, monkeypatch):
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    _, accounts = isolated
    _sign_in("live@example.com", monkeypatch)
    old_headers, _old_preauth = _link_headers()
    client.post("/v1/auth/magic-link", json={"email": "old@example.com"}, headers=old_headers)
    engine = accounts._session_factory.kw["bind"]
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE login_tokens SET expires_at = '2000-01-01T00:00:00+00:00' WHERE email = 'old@example.com'"
        ))
        conn.execute(text("UPDATE auth_sessions SET expires_at = '2000-01-01T00:00:00+00:00'"))
    keep_headers, keep_preauth = _link_headers()
    kept = client.post("/v1/auth/magic-link", json={"email": "keep@example.com"}, headers=keep_headers)
    keep_token = parse_qs(urlparse(kept.json()["debug_url"]).query)["token"][0]
    accounts.purge_expired()
    with engine.connect() as conn:
        emails = [row[0] for row in conn.execute(text("SELECT email FROM login_tokens"))]
        sessions = conn.execute(text("SELECT COUNT(*) FROM auth_sessions")).scalar()
    assert emails == ["keep@example.com"]
    assert sessions == 0
    assert client.post("/v1/auth/verify", json={"token": keep_token, "preauth": keep_preauth}).status_code == 200


def test_login_rotates_the_presented_session_id(isolated, monkeypatch):
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    laptop = _sign_in("pilot@example.com", monkeypatch, "server-key-123")
    phone_headers, phone_preauth = _link_headers("server-key-123")
    phone_link = client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}, headers=phone_headers)
    phone_token = parse_qs(urlparse(phone_link.json()["debug_url"]).query)["token"][0]
    phone = client.post(
        "/v1/auth/verify",
        json={"token": phone_token, "preauth": phone_preauth},
        headers={"X-API-Key": "server-key-123"},
    )
    assert phone.status_code == 200, phone.text
    key = {"X-API-Key": "server-key-123"}
    assert client.get("/v1/auth/me", headers={**key, "X-User-Session": laptop["session_token"]}).status_code == 200

    rotate_headers, rotate_preauth = _link_headers("server-key-123")
    rotate_link = client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}, headers=rotate_headers)
    rotate_token = parse_qs(urlparse(rotate_link.json()["debug_url"]).query)["token"][0]
    rotated = client.post(
        "/v1/auth/verify",
        json={"token": rotate_token, "preauth": rotate_preauth, "previous_session": laptop["session_token"]},
        headers=key,
    )
    assert rotated.status_code == 200, rotated.text
    new_token = rotated.json()["session_token"]
    assert new_token != laptop["session_token"]
    assert client.get("/v1/auth/me", headers={**key, "X-User-Session": laptop["session_token"]}).status_code == 401
    assert client.get("/v1/auth/me", headers={**key, "X-User-Session": phone.json()["session_token"]}).status_code == 200
    assert client.get("/v1/auth/me", headers={**key, "X-User-Session": new_token}).status_code == 200

    def session_id(raw: str) -> str | None:
        digest = hashlib.sha256(raw.encode()).hexdigest()
        engine = isolated[1]._session_factory.kw["bind"]
        with engine.connect() as conn:
            return conn.execute(text("SELECT id FROM auth_sessions WHERE token_hash = :h"), {"h": digest}).scalar()

    assert session_id(laptop["session_token"]) is None
    assert session_id(new_token) != session_id(phone.json()["session_token"])


def test_auth_debug_is_refused_in_production(isolated, monkeypatch, caplog):
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    monkeypatch.setenv("FLY_APP_NAME", "mtg-deck-lab-api")
    caplog.set_level(logging.ERROR)
    auth_module.log_auth_debug_configuration()
    assert "refused" in caplog.text.lower()
    assert auth_module.auth_debug_enabled() is False
    headers, _preauth = _link_headers()
    body = client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}, headers=headers).json()
    assert body == {"ok": True}

    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.setenv("ENV", "production")
    assert auth_module.auth_debug_enabled() is False
    caplog.clear()
    auth_module.log_auth_debug_configuration()
    assert "refused" in caplog.text.lower()


def test_auth_debug_warns_when_enabled_outside_production(monkeypatch, caplog):
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    caplog.set_level(logging.WARNING)
    auth_module.log_auth_debug_configuration()
    assert "MTG_AUTH_DEBUG is enabled" in caplog.text
    assert auth_module.auth_debug_enabled() is True


def test_sign_in_budgets_persist_and_honor_the_daily_cap(isolated, monkeypatch):
    monkeypatch.setenv("MTG_AUTH_DAILY_EMAIL_CAP", "2")
    _, accounts = isolated

    def post(email: str):
        headers, _preauth = _link_headers()
        return client.post("/v1/auth/magic-link", json={"email": email}, headers=headers)

    assert post("one@example.com").status_code == 200
    assert post("two@example.com").status_code == 200
    assert post("three@example.com").status_code == 429
    monkeypatch.setattr(auth_module, "auth_service", AuthService(session_factory=accounts._session_factory))
    assert post("four@example.com").status_code == 429


def test_magic_link_without_preauth_stores_nothing(isolated):
    isolated[1]._ensure()
    assert client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}).status_code == 400
    engine = isolated[1]._session_factory.kw["bind"]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM login_tokens")).scalar() == 0


def test_legacy_anonymous_deck_without_a_secret_cannot_be_deleted(isolated):
    history, _accounts = isolated
    saved = client.post(
        "/v1/decks/save",
        json={"name": "Old anon", "format": "modern", "mainboard": [{"name": "Plains", "quantity": 1}]},
    ).json()
    engine = history._session_factory.kw["bind"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE saved_decks SET edit_secret_hash = NULL WHERE id = :id"), {"id": saved["id"]})
    assert client.delete(
        f"/v1/decks/saved/{saved['id']}",
        headers={"X-Deck-Edit-Secret": saved["edit_secret"]},
    ).status_code == 404
    assert client.get(f"/v1/decks/shared/{saved['share_token']}").status_code == 200


def test_old_login_token_table_gains_preauth_hash():
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE login_tokens (id VARCHAR(64) PRIMARY KEY, email VARCHAR(320), "
            "token_hash VARCHAR(64), expires_at VARCHAR(40), used_at VARCHAR(40))"
        ))
        conn.execute(text(
            "CREATE TABLE user_accounts (id VARCHAR(64) PRIMARY KEY, email VARCHAR(320), created_at VARCHAR(40))"
        ))
        conn.execute(text(
            "CREATE TABLE auth_sessions (id VARCHAR(64) PRIMARY KEY, user_id VARCHAR(64), "
            "token_hash VARCHAR(64), expires_at VARCHAR(40), created_at VARCHAR(40))"
        ))
    accounts = AuthService(session_factory=sessionmaker(bind=engine, future=True))
    accounts._ensure()
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(login_tokens)"))}
    assert "preauth_hash" in columns


def test_pytest_is_not_a_runtime_dependency():
    api = __import__("pathlib").Path(__file__).resolve().parents[1]
    runtime = (api / "requirements.txt").read_text()
    dev = (api / "requirements-dev.txt").read_text()
    runtime_deps = [line.strip() for line in runtime.splitlines() if line.strip() and not line.strip().startswith("#")]
    assert not any(line.lower().startswith("pytest") for line in runtime_deps)
    assert "pytest==" in dev
    docker = (api / "Dockerfile").read_text()
    assert "requirements.txt" in docker
    assert "requirements-dev" not in docker
    ci = (api.parent / ".github" / "workflows" / "ci.yml").read_text()
    assert "requirements-dev.txt" in ci


def test_fresh_engine_gets_auth_rate_buckets_even_when_its_id_was_cached():
    """id(engine) is reused after GC. A cache of those ids skips CREATE TABLE."""
    engine = _engine()
    stale = getattr(auth_module, "_ready_engines", None)
    if isinstance(stale, set):
        stale.add(id(engine))
    accounts = AuthService(session_factory=sessionmaker(bind=engine, future=True))
    assert accounts.consume_ip("203.0.113.60") is True
    with engine.connect() as conn:
        found = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='auth_rate_buckets'"
        )).scalar()
    assert found == "auth_rate_buckets"


def test_ipv6_sign_in_limit_groups_a_slash_64(isolated, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    monkeypatch.setattr(auth_module, "IP_LIMIT", 1)
    monkeypatch.setattr(auth_module, "IP_DAILY_LIMIT", 100)
    assert auth_module.rate_limit_ip("2001:db8:85a3::1") == auth_module.rate_limit_ip("2001:db8:85a3::ffff")
    assert auth_module.rate_limit_ip("2001:db8:85a3::1") != auth_module.rate_limit_ip("2001:db8:85a4::1")
    assert auth_module.rate_limit_ip("::ffff:192.0.2.1") == "192.0.2.1"

    def post(ip: str, email: str):
        headers, _preauth = _link_headers("server-key-123")
        headers["X-Forwarded-For"] = ip
        return client.post("/v1/auth/magic-link", json={"email": email}, headers=headers)

    assert post("2001:db8:85a3::1", "a@example.com").status_code == 200
    assert post("2001:db8:85a3::ffff", "b@example.com").status_code == 429
    assert post("2001:db8:85a4::1", "c@example.com").status_code == 200


def test_ten_addresses_cannot_exhaust_the_global_daily_cap(monkeypatch):
    monkeypatch.delenv("MTG_AUTH_DAILY_EMAIL_CAP", raising=False)
    assert auth_module.IP_DAILY_LIMIT * 10 < auth_module.daily_email_cap()
    assert auth_module.EMAIL_DAILY_LIMIT < auth_module.daily_email_cap()
    assert auth_module.EMAIL_NETWORK_DAILY_LIMIT < auth_module.EMAIL_DAILY_LIMIT


def test_throttled_sign_in_keeps_the_pending_link(isolated, monkeypatch):
    monkeypatch.setenv("MTG_AUTH_DEBUG", "1")
    monkeypatch.setattr(auth_module, "EMAIL_DAILY_LIMIT", 1)
    monkeypatch.setattr(auth_module, "EMAIL_LIMIT", 100)
    monkeypatch.setattr(auth_module, "IP_LIMIT", 100)
    monkeypatch.setattr(auth_module, "IP_DAILY_LIMIT", 100)
    monkeypatch.setenv("MTG_AUTH_DAILY_EMAIL_CAP", "1000")
    headers, preauth = _link_headers()
    first = client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}, headers=headers)
    assert first.status_code == 200, first.text
    token = parse_qs(urlparse(first.json()["debug_url"]).query)["token"][0]
    again, _again_preauth = _link_headers()
    rejected = client.post("/v1/auth/magic-link", json={"email": "pilot@example.com"}, headers=again)
    assert rejected.status_code == 429
    verified = client.post("/v1/auth/verify", json={"token": token, "preauth": preauth})
    assert verified.status_code == 200, verified.text


def test_per_ip_daily_cap_is_separate_from_the_hourly_cap(isolated, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "server-key-123")
    monkeypatch.setattr(auth_module, "IP_LIMIT", 100)
    monkeypatch.setattr(auth_module, "IP_DAILY_LIMIT", 2)
    monkeypatch.setattr(auth_module, "EMAIL_LIMIT", 100)
    monkeypatch.setattr(auth_module, "EMAIL_DAILY_LIMIT", 100)
    monkeypatch.setenv("MTG_AUTH_DAILY_EMAIL_CAP", "1000")

    def post(email: str):
        headers, _preauth = _link_headers("server-key-123")
        headers["X-Forwarded-For"] = "203.0.113.77"
        return client.post("/v1/auth/magic-link", json={"email": email}, headers=headers)

    assert post("one@example.com").status_code == 200
    assert post("two@example.com").status_code == 200
    assert post("three@example.com").status_code == 429
    other, _preauth = _link_headers("server-key-123")
    other["X-Forwarded-For"] = "203.0.113.78"
    assert client.post("/v1/auth/magic-link", json={"email": "four@example.com"}, headers=other).status_code == 200


def test_rate_bucket_bump_stops_at_the_limit_and_rolls_back(isolated, monkeypatch):
    _, accounts = isolated
    accounts._ensure()
    session = accounts._session()
    try:
        assert auth_module._bump(session, "email:test", "2026-10-28T06", 2) is True
        assert auth_module._bump(session, "email:test", "2026-10-28T06", 2) is True
        assert auth_module._bump(session, "email:test", "2026-10-28T06", 2) is False
        session.commit()
        count = session.execute(text("SELECT count FROM auth_rate_buckets WHERE bucket = 'email:test'")).scalar()
        assert count == 2
        assert auth_module._bump(session, "email:test", "2026-10-28T07", 2) is True
        session.commit()
    finally:
        session.close()

    monkeypatch.setenv("MTG_AUTH_DAILY_EMAIL_CAP", "1")
    assert accounts.consume_email_send("a@example.com") is True
    assert accounts.consume_email_send("b@example.com") is False
    check = accounts._session()
    try:
        rows = dict(check.execute(text("SELECT bucket, count FROM auth_rate_buckets")).all())
    finally:
        check.close()
    kept = "email:" + hashlib.sha256(b"a@example.com").hexdigest()
    dropped = "email:" + hashlib.sha256(b"b@example.com").hexdigest()
    assert rows[kept] == 1
    assert dropped not in rows
