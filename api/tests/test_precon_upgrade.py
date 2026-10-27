"""Commander precon upgrade: budget, legality, explanations, cart link."""

from fastapi.testclient import TestClient

from app.main import app
from app.models import PreconUpgradeRequest
from app.services.card_repository import CardRepository
from app.services.deck_validator import DeckValidator
from app.services.precon_upgrade import upgrade_precon


client = TestClient(app)


def _krenko_list() -> str:
    # 99-card mainboard: three weak off-theme creatures and the rest basics.
    # The Commander section is how the deck parser takes a commander out of the 99.
    return "\n".join([
        "Commander",
        "1 Krenko, Mob Boss",
        "Deck",
        "96 Mountain",
        "1 Bedhead Beastie",
        "1 Shatterskull Minotaur",
        "1 Bosh, Iron Golem",
    ])


def test_upgrade_stays_in_red_under_budget_and_explains_each_swap() -> None:
    repository = CardRepository()
    result = upgrade_precon(
        PreconUpgradeRequest(deck_text=_krenko_list(), budget_usd=15, max_bracket=2),
        repository=repository,
        validator=DeckValidator(repository),
    )
    assert result.commander == "Krenko, Mob Boss"
    assert result.swaps, "expected at least one swap"
    assert result.total_cost_usd <= 15
    assert abs(result.total_cost_usd - round(sum(swap.add_price_usd for swap in result.swaps), 2)) < 0.001
    cuts = {swap.cut for swap in result.swaps}
    adds = [swap.add for swap in result.swaps]
    assert cuts <= {"Bedhead Beastie", "Shatterskull Minotaur", "Bosh, Iron Golem"}
    assert "Mountain" not in cuts
    assert len(adds) == len(set(adds))
    for swap in result.swaps:
        assert swap.cut_explanation and swap.add_explanation
        assert swap.add_price_usd >= 0
        card = repository.get_card(swap.add)
        assert card is not None
        identity = set(card.color_identity or card.colors)
        assert identity <= {"R"}
        assert card.name not in {"Bedhead Beastie", "Shatterskull Minotaur", "Bosh, Iron Golem", "Krenko, Mob Boss"}
    assert result.legality.is_legal, result.legality.errors
    assert 1 <= result.bracket.estimated <= 4
    assert result.bracket.target == 2
    assert result.tcgplayer_cart_url
    assert "massentry" in result.tcgplayer_cart_url
    # Bracket 2 refuses Game Changers, so a cheap upgrade must not add one.
    assert "Rhystic Study" not in adds
    # The useful cheap upgrades for a rock-less Goblin deck.
    assert set(adds) & {"Sol Ring", "Arcane Signet", "Mind Stone", "Goblin Warchief", "Goblin Chieftain"}


def test_zero_budget_makes_no_purchases() -> None:
    repository = CardRepository()
    result = upgrade_precon(
        PreconUpgradeRequest(deck_text=_krenko_list(), budget_usd=0),
        repository=repository,
        validator=DeckValidator(repository),
    )
    assert result.swaps == []
    assert result.total_cost_usd == 0
    assert result.tcgplayer_cart_url is None


def test_api_lists_real_precons_and_upgrades_a_pasted_list() -> None:
    listed = client.get("/v1/commander/precons", params={"q": "Calling All Angels", "limit": 5})
    assert listed.status_code == 200
    precons = listed.json()["precons"]
    assert precons
    assert precons[0]["commander"]
    assert precons[0]["id"].startswith("mtgjson-")

    upgraded = client.post(
        "/v1/commander/precon-upgrade",
        json={"deck_text": _krenko_list(), "budget_usd": 10, "max_bracket": 3},
    )
    assert upgraded.status_code == 200, upgraded.text
    body = upgraded.json()
    assert body["total_cost_usd"] <= 10
    assert body["legality"]["is_legal"] is True
    assert body["bracket"]["estimated"] >= 2
    for swap in body["swaps"]:
        assert swap["cut_explanation"]
        assert swap["add_explanation"]


def test_unknown_precon_is_404_and_over_budget_is_422() -> None:
    missing = client.post("/v1/commander/precon-upgrade", json={"precon_id": "nope", "budget_usd": 20})
    assert missing.status_code == 404
    huge = client.post("/v1/commander/precon-upgrade", json={"deck_text": _krenko_list(), "budget_usd": 9000})
    assert huge.status_code == 422
    empty = client.post("/v1/commander/precon-upgrade", json={"budget_usd": 20})
    assert empty.status_code == 400


def test_catalog_precon_round_trip_uses_its_commander() -> None:
    # Lathril's precon is in the snapshot and the commander is in the fixture DB.
    listed = client.get("/v1/commander/precons", params={"q": "Elven Empire", "limit": 5})
    assert listed.status_code == 200
    precons = listed.json()["precons"]
    assert precons
    chosen = next(item for item in precons if item["commander"] == "Lathril, Blade of the Elves")
    # A $0 request still resolves the catalog id and returns the bracket.
    response = client.post(
        "/v1/commander/precon-upgrade",
        json={"precon_id": chosen["id"], "budget_usd": 0},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["precon_id"] == chosen["id"]
    assert body["commander"] == chosen["commander"]
    assert body["swaps"] == []
    assert isinstance(body["upgraded_mainboard"], list)
    assert sum(card["quantity"] for card in body["upgraded_mainboard"]) in {98, 99}
