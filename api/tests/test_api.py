from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_generate_modern_deck() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["U", "R"],
            "playstyle_tags": ["aggro", "spells"],
            "theme_tags": ["prowess"],
            "mode": "constraint-aware",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "modern"
    assert len(payload["mainboard"]) > 0
    assert payload["score"]["legality"] == 100
    assert payload["is_legal"] is True
    assert payload["validation_errors"] == []
    assert "estimated_price_usd" in payload


def test_validate_bad_deck() -> None:
    response = client.post(
        "/v1/decks/validate",
        json={
            "format": "modern",
            "mainboard": [{"name": "Lightning Bolt", "quantity": 8}],
            "sideboard": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is False
    assert payload["errors"]


def test_export_csv_format() -> None:
    generate_response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["U", "R"],
            "playstyle_tags": ["aggro", "spells"],
            "theme_tags": ["prowess"],
        },
    )
    assert generate_response.status_code == 200
    deck = generate_response.json()

    export_response = client.post(
        "/v1/decks/export",
        json={
            "deck": deck,
            "target": "csv",
        },
    )
    assert export_response.status_code == 200
    payload = export_response.json()
    assert payload["target"] == "csv"
    assert payload["content"].startswith("section,quantity,name")


def test_refine_budget_prompt_changes_deck_and_reduces_price() -> None:
    generate_response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["U", "R"],
            "playstyle_tags": ["aggro", "spells"],
            "theme_tags": ["prowess"],
        },
    )
    assert generate_response.status_code == 200
    deck = generate_response.json()

    refine_response = client.post(
        "/v1/decks/refine",
        json={
            "deck": deck,
            "refinement_prompt": "Make it cheaper while keeping the deck aggressive.",
        },
    )
    assert refine_response.status_code == 200
    refined = refine_response.json()
    assert refined["title"].endswith("Refined")
    assert refined["mainboard"] != deck["mainboard"]
    assert refined["estimated_price_usd"] < deck["estimated_price_usd"]
    assert refined["is_legal"] is True


def test_generate_deck_returns_full_sideboard_without_sideboard_land_penalty() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["U", "R"],
            "playstyle_tags": ["aggro", "spells"],
            "theme_tags": ["prowess"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["score"]["legality"] == 100
    assert sum(card["quantity"] for card in payload["sideboard"]) == 15
    assert not any("15-card sideboard" in warning for warning in payload["warnings"])


def test_generate_modern_lifegain_keeps_legal_legendary_playsets() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["W"],
            "playstyle_tags": ["lifegain"],
            "theme_tags": ["lifegain"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is True
    assert payload["score"]["legality"] == 100
    heliod = next(card for card in payload["mainboard"] if card["name"] == "Heliod, Sun-Crowned")
    assert heliod["quantity"] == 4


def test_generate_standard_deck_filters_out_illegal_cards() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "standard",
            "colors": ["R", "W"],
            "playstyle_tags": ["aggro"],
            "theme_tags": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is True
    assert payload["validation_errors"] == []
    assert payload["score"]["legality"] == 100
