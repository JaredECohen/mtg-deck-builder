"""Role counts, prices, and the committed precon facts file."""

from app.scripts.precon_stats import distribution, is_draw, is_land_type, is_ramp, is_removal, line_usd, parse_usd, sum_usd


def test_lands_are_not_also_ramp_draw_or_removal():
    assert is_land_type("Basic Land — Forest")
    assert is_land_type("Land Creature — Forest Dryad")
    assert not is_land_type("Creature — Elf Druid")
    text = "{T}: Add {G}. {T}: Draw a card. Destroy target creature."
    assert not is_ramp("Basic Land — Forest", text)
    assert not is_draw("Basic Land — Forest", text)
    assert not is_removal("Basic Land — Forest", text)


def test_ramp_matches_rocks_dorks_and_land_search_not_compensation():
    assert is_ramp("Artifact", "{T}: Add {C}{C}.")
    assert is_ramp("Artifact", "{T}: Add one mana of any color in your commander's color identity.")
    assert is_ramp("Creature — Elf Druid", "{T}: Add {G}.")
    assert is_ramp(
        "Sorcery",
        "Search your library for up to two basic land cards, reveal those cards, put one onto the battlefield tapped and the other into your hand, then shuffle.",
    )
    assert is_ramp(
        "Sorcery",
        "Search your library for a Plains, Island, Swamp, or Mountain card, put it onto the battlefield tapped, then shuffle.",
    )
    assert is_ramp("Instant", "Add {R}{R}{R}.")
    assert is_ramp("Creature — Goblin", "When this creature enters, create X Treasure tokens, where X is the number of artifacts and enchantments your opponents control.")
    assert not is_ramp(
        "Instant",
        "Destroy target permanent. Its controller may search their library for a basic land card, put that card onto the battlefield tapped, then shuffle.",
    )
    assert not is_ramp("Instant", "Counter target spell.")
    assert not is_ramp("Instant", "Lightning Bolt deals 3 damage to any target.")


def test_draw_counts_your_cards_and_impulse_not_opponent_only():
    assert is_draw("Sorcery", "You draw two cards and you lose 2 life.")
    assert is_draw("Enchantment", "Whenever an opponent casts a spell, you may draw a card unless that player pays {1}.")
    assert is_draw("Sorcery", "Target player draws two cards and loses 2 life.")
    assert is_draw("Sorcery", "Exile the top two cards of your library. Until the end of your turn, you may play those cards.")
    assert not is_draw("Sorcery", "Each opponent draws a card.")
    assert not is_draw("Instant", "Counter target spell.")


def test_removal_is_not_a_counterspell_or_a_graveyard_exile():
    assert is_removal("Instant", "Exile target creature. Its controller may search their library for a basic land card, put that card onto the battlefield tapped, then shuffle.")
    assert is_removal("Sorcery", "Destroy all creatures. They can't be regenerated.")
    assert is_removal("Instant", "Lightning Bolt deals 3 damage to any target.")
    assert is_removal("Sorcery", "The owner of target permanent shuffles it into their library, then reveals the top card of their library. If it's a permanent card, they put it onto the battlefield.")
    assert not is_removal("Instant", "Counter target spell.")
    assert not is_removal("Instant", "Exile target card from a graveyard.")
    assert not is_removal("Artifact", "{T}: Add {C}{C}.")


def test_unpriced_cards_are_left_out_of_the_total():
    assert parse_usd(None) is None
    assert parse_usd("") is None
    assert parse_usd("1.50") == 1.5
    assert line_usd(None, 4) is None
    assert line_usd(1.5, 4) == 6.0
    assert sum_usd([6.0, None, 0.25]) == 6.25


def test_distribution_names_the_extremes():
    stats = distribution([("b", 10), ("a", 10), ("c", 30), ("d", 20)])
    assert stats["min"] == 10
    assert stats["max"] == 30
    assert stats["median"] == 15
    assert stats["lowest"][0] == {"id": "a", "value": 10}
    assert stats["highest"][0] == {"id": "c", "value": 30}
    assert stats["in_middle_half"] == 3
    assert stats["in_middle_half_pct"] == 75.0


def test_committed_facts_cover_the_official_snapshot():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    facts = json.loads((root / "web" / "src" / "data" / "precon_facts.json").read_text(encoding="utf-8"))
    summary = facts["summary"]
    decks = facts["decks"]
    assert summary["official_decks"] == 190
    assert summary["commander_precons"] == 182
    assert summary["pioneer_challenger"] == 8
    assert len(decks) == 190
    assert facts["sources"]["prices"]["price_field"] == "prices.usd"
    assert facts["sources"]["decks"]["license"].endswith("/license/")
    commanders = [deck for deck in decks.values() if deck["format"] == "commander"]
    assert len(commanders) == 182
    for deck in decks.values():
        assert deck["land_count"] >= 0
        assert deck["price_usd"] >= 0
        assert isinstance(deck["unpriced"], list)
        assert set(deck["game_changers"]) <= {row["name"] for row in facts["game_changers"]}
        curve = sum(point["card_count"] for point in deck["mana_curve"])
        assert curve == deck["nonland_count"]
        if not deck["missing_oracle"]:
            assert deck["land_count"] + deck["nonland_count"] == deck["mainboard_cards"]
    assert facts["summary"]["precons_fully_priced"] + facts["summary"]["precons_with_unpriced"] == 182
    assert facts["summary"]["game_changer_list_size"] == len(facts["game_changers"])
    assert facts["summary"]["game_changers_found_in_precons"] == sum(1 for row in facts["game_changers"] if row["precon_count"])
    assert facts["summary"]["precons_with_99_card_mainboard"] == sum(
        1 for deck in commanders if deck["mainboard_cards"] == 99
    )
    assert "price_complete" in facts["summary"]
    pioneer = [deck for deck in decks.values() if deck["format"] == "pioneer"]
    assert len(pioneer) == 8
    assert all(deck["mainboard_cards"] == 60 for deck in pioneer)
    priced = [row for row in facts["game_changers"] if not row["unpriced"]]
    assert priced, "Scryfall bulk should price at least one Game Changer"
    assert all(isinstance(row["usd"], (int, float)) and row["usd"] >= 0 for row in priced)
