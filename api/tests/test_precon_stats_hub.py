"""The precon stats table, checked against the MTGJSON lists and the facts file.

The web page reads the same two files. These expectations are the raw counts
for three products: the mainboard names, the stored curve, and the role lists
the facts build wrote from Scryfall oracle text.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / "web" / "src" / "data" / "precon_facts.json"
OFFICIAL_PATH = ROOT / "api" / "app" / "data" / "official_decks.json"

EXPECTED = {
    "mtgjson-VelociRampTor_LCC": {
        "name": "Veloci-Ramp-Tor",
        "set_code": "LCC",
        "release_date": "2023-11-17",
        "commanders": ["Pantlaza, Sun-Favored"],
        "land_count": 39,
        "curve": [0, 3, 9, 17, 9, 9, 6, 7],
        "average": 3.97,
        "ramp_count": 14,
        "draw_count": 7,
        "removal_count": 9,
        "game_changers": [],
        "price_usd": 107.34,
        "ramp_names": ["Sol Ring", "Cultivate", "Farseek"],
    },
    "mtgjson-ExitFromExile_CLB": {
        "name": "Exit from Exile",
        "set_code": "CLB",
        "release_date": "2022-06-10",
        "commanders": ["Faldorn, Dread Wolf Herald"],
        "land_count": 39,
        "curve": [0, 1, 9, 17, 12, 7, 6, 8],
        "average": 4.08,
        "ramp_count": 15,
        "draw_count": 7,
        "removal_count": 6,
        "game_changers": ["Jeska's Will"],
        "price_usd": 131.73,
        "ramp_names": ["Sol Ring", "Cultivate", "Jeska's Will"],
    },
    "mtgjson-EldraziUnbound_CMM": {
        "name": "Eldrazi Unbound",
        "set_code": "CMM",
        "release_date": "2023-08-04",
        "commanders": ["Zhulodok, Void Gorger"],
        "land_count": 38,
        "curve": [5, 1, 11, 10, 9, 2, 8, 15],
        "average": 4.13,
        "ramp_count": 15,
        "draw_count": 10,
        "removal_count": 11,
        "game_changers": [],
        "price_usd": 239.72,
        "ramp_names": ["Sol Ring"],
    },
}


def _load():
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    official = json.loads(OFFICIAL_PATH.read_text(encoding="utf-8"))
    return facts, official


def _curve_average(curve: list[int]) -> float:
    cards = sum(curve)
    return sum(mana_value * count for mana_value, count in enumerate(curve)) / cards


def _names(board: list[dict]) -> dict[str, int]:
    return {card["name"]: card["quantity"] for card in board}


def test_commander_table_population_matches_both_files():
    facts, official = _load()
    fact_commanders = [deck for deck in facts["decks"].values() if deck["format"] == "commander"]
    official_commanders = [deck for deck in official["decks"] if deck["format"] == "commander"]
    assert facts["summary"]["commander_products"] == 182
    assert len(fact_commanders) == 182
    assert len(official_commanders) == 182
    assert {deck["id"] for deck in fact_commanders} == {deck["id"] for deck in official_commanders}
    assert facts["summary"]["pioneer_challenger"] == 8
    for deck in fact_commanders:
        curve = [point["card_count"] for point in deck["mana_curve"]]
        assert len(curve) == 8
        assert deck["land_count"] is not None
        assert sum(curve) == deck["nonland_count"]
        assert deck["land_count"] + sum(curve) == deck["mainboard_cards"]
        assert not deck["missing_oracle"]
        assert deck["mainboard_cards"] > 0


def test_known_decks_match_the_official_mainboard_and_the_curve():
    facts, official = _load()
    official_by_id = {deck["id"]: deck for deck in official["decks"]}
    for deck_id, expected in EXPECTED.items():
        facts_deck = facts["decks"][deck_id]
        source = official_by_id[deck_id]
        mainboard = _names(source["mainboard"])
        curve = [point["card_count"] for point in facts_deck["mana_curve"]]
        assert source["name"] == expected["name"]
        assert source["set_code"] == expected["set_code"]
        assert source["release_date"] == expected["release_date"]
        assert source["commanders"] == expected["commanders"]
        assert facts_deck["land_count"] == expected["land_count"]
        assert curve == expected["curve"]
        assert round(_curve_average(curve), 2) == expected["average"]
        assert sum(mainboard.values()) == facts_deck["mainboard_cards"]
        assert facts_deck["land_count"] + sum(curve) == sum(mainboard.values())
        for flag, count_key in (("ramp_cards", "ramp_count"), ("draw_cards", "draw_count"), ("removal_cards", "removal_count")):
            listed = facts_deck[flag]
            assert sum(card["quantity"] for card in listed) == facts_deck[count_key] == expected[count_key]
            for card in listed:
                assert card["name"] in mainboard
                assert mainboard[card["name"]] == card["quantity"]
        assert facts_deck["ramp_count"] == expected["ramp_count"]
        assert facts_deck["draw_count"] == expected["draw_count"]
        assert facts_deck["removal_count"] == expected["removal_count"]
        zone = set(mainboard) | set(source["commanders"])
        assert set(facts_deck["game_changers"]) <= zone
        assert facts_deck["game_changers"] == expected["game_changers"]
        assert facts_deck["price_usd"] == expected["price_usd"]
        assert facts_deck["unpriced"] == []
        for name in expected["ramp_names"]:
            assert name in mainboard
            assert any(card["name"] == name for card in facts_deck["ramp_cards"])
        for commander in expected["commanders"]:
            assert commander not in mainboard
