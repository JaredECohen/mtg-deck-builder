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
    # Cycling's draw is reminder text. A "whenever you draw" trigger is not a draw spell.
    assert not is_draw("Instant", "Cycling {2} ({2}, Discard this card: Draw a card.)")
    assert not is_draw("Artifact Creature — Phyrexian Horror", "Whenever you draw a card, put a +1/+1 counter on this creature.")
    assert not is_draw(
        "Enchantment",
        "Whenever an opponent draws a card, that player may pay {2}. If the player doesn't, you create a Treasure token.",
    )
    assert not is_draw(
        "Enchantment",
        "Whenever you draw a card, surveil 1. (To surveil 1, look at the top card of your library. You may put that card into your graveyard.)",
    )


def test_blink_is_not_removal_and_a_minus_spell_is():
    assert not is_removal(
        "Instant",
        "Exile target creature you control, then return that card to the battlefield under its owner's control.",
    )
    assert not is_removal(
        "Artifact",
        "{T}: Exile target nontoken creature you control, then return it to the battlefield under your control.",
    )
    assert not is_removal(
        "Sorcery",
        "Exile all creatures you control, then reveal cards from the top of your library until you reveal that many creature cards.",
    )
    assert is_removal("Instant", "Target creature gets -4/-4 until end of turn.")
    assert is_removal("Sorcery", "All creatures get -2/-2 until end of turn.")
    assert is_removal("Sorcery", "Each creature gets -1/-1 until end of turn.")
    assert is_removal("Instant", "Exile target creature. Its controller may search their library for a basic land card.")


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
    assert summary["commander_products"] == 182
    assert summary["commander_precons"] == 174
    assert len(summary["duplicate_reprints"]) == 8
    assert summary["pioneer_challenger"] == 8
    assert summary["decks_at_100_cards"] == 182
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
    assert facts["summary"]["precons_fully_priced"] + facts["summary"]["precons_with_unpriced"] == 174
    assert facts["summary"]["game_changer_list_size"] == 53
    assert facts["summary"]["game_changers_found_in_precons"] == sum(1 for row in facts["game_changers"] if row["precon_count"])
    assert all(deck["mainboard_cards"] + len(deck["commanders"]) == 100 for deck in commanders)
    assert "price_complete" in facts["summary"]
    pioneer = [deck for deck in decks.values() if deck["format"] == "pioneer"]
    assert len(pioneer) == 8
    assert all(deck["mainboard_cards"] == 60 for deck in pioneer)
    priced = [row for row in facts["game_changers"] if not row["unpriced"]]
    assert priced, "Scryfall bulk should price at least one Game Changer"
    assert all(isinstance(row["usd"], (int, float)) and row["usd"] >= 0 for row in priced)


def test_committed_game_changers_match_the_facts_census():
    """CI does not download the oracle bulk.

    ``build_precon_facts`` raises when ``game_changers.json`` drifts from the
    Scryfall ``game_changer`` field. This locks the committed file to the census
    that was built from that bulk, so the two artifacts cannot diverge in CI.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    listed = json.loads((root / "api" / "app" / "data" / "game_changers.json").read_text(encoding="utf-8"))
    facts = json.loads((root / "web" / "src" / "data" / "precon_facts.json").read_text(encoding="utf-8"))
    names = sorted(listed["game_changers"])
    assert listed["as_of"] == "2026-11-01"
    assert names == sorted(row["name"] for row in facts["game_changers"])
    assert facts["summary"]["game_changer_list_size"] == len(names) == 53


def test_load_oracle_keeps_the_real_card_when_a_token_row_is_first(tmp_path):
    import json

    from app.scripts.build_precon_facts import load_oracle

    path = tmp_path / "oracle.jsonl"
    rows = [
        {
            "name": "Dinosaur Egg",
            "layout": "token",
            "set_type": "token",
            "type_line": "Token Creature — Dinosaur Egg",
            "oracle_text": "This token is not the card.",
        },
        {
            "name": "Dinosaur Egg",
            "layout": "normal",
            "set_type": "commander",
            "type_line": "Creature — Dinosaur Egg",
            "oracle_text": "Trample",
            "cmc": 1,
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    found = load_oracle(path, {"Dinosaur Egg"})
    assert found["Dinosaur Egg"]["type_line"] == "Creature — Dinosaur Egg"
    assert found["Dinosaur Egg"]["oracle_text"] == "Trample"
    assert found["Dinosaur Egg"]["layout"] == "normal"


def test_study_guide_template_calls_a_full_total_the_whole_list():
    from pathlib import Path

    text = Path(__file__).resolve().parents[1].joinpath("app/scripts/build_study_guides.py").read_text(encoding="utf-8")
    assert "the rest of the product" not in text.lower()
    assert "The whole list sums to" in text
