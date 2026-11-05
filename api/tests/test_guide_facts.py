"""Token cards in an official product list are not part of the deck."""

from app.scripts.build_guide_facts import (
    _goldfish,
    example_format,
    is_token_entry,
    is_token_type_line,
    world_championship_specs,
    worlds_example_id,
)


def test_token_type_line_matches_supertype_only():
    assert is_token_type_line("Token Creature — Dinosaur Egg")
    assert is_token_type_line("Token Artifact — Treasure")
    assert not is_token_type_line("Creature — Dinosaur")
    assert not is_token_type_line("Instant")
    # A spell that mentions tokens in its name is still a card.
    assert not is_token_type_line("Creature — Human Wizard")


def test_price_scope_and_legality_wording():
    from app.scripts.guide_articles import illegal_sentence, price_scope

    priced = price_scope({"analysis": {"unpriced": []}})
    assert priced == "main deck, sideboard, and commander"
    partial = price_scope({"analysis": {"unpriced": ["Obuun, Mul Daya Ancestor"]}})
    assert partial == "priced cards only, 1 unpriced card (Obuun, Mul Daya Ancestor)"
    assert "main deck, sideboard, and commander" not in partial
    many = price_scope({"analysis": {"unpriced": ["Veyran, Voice of Duality", "Zaffai, Thunder Conductor"]}})
    assert many.startswith("priced cards only, 2 unpriced cards")
    text = illegal_sentence(
        {"name": "Izzet Phoenix", "format": "pioneer", "analysis": {"illegal_in_format": ["Expressive Iteration"]}},
        "2026-11-01",
    )
    assert text == "Expressive Iteration is not legal today per the Scryfall bulk of 2026-11-01."
    assert "printed before" not in text


def test_world_championship_ids_and_a_missing_card_do_not_crash():
    assert example_format({"type": "World Championship Deck"}) == "legacy"
    assert example_format({"type": "Commander Deck"}) == "commander"
    assert example_format({"type": "Pioneer Challenger Deck"}) == "pioneer"
    assert example_format({}) == "legacy"
    assert worlds_example_id("JonFinkelMonoBlueTinker_WC00").startswith("wc-")
    specs = world_championship_specs(
        {
            "data": [
                {"type": "World Championship Deck", "fileName": "JonFinkelMonoBlueTinker_WC00"},
                {"type": "World Championship Deck", "fileName": ""},
                {"type": "Commander Deck", "fileName": "NotWorlds_C21"},
                {"type": "Theme Deck", "fileName": "SkipMe"},
            ]
        }
    )
    assert specs == [("wc-jonfinkelmonobluetinker-wc00", "JonFinkelMonoBlueTinker_WC00", "midrange")]
    # A typo and a profile that cannot be built are unresolved, not an exception.
    report = _goldfish(
        [{"name": "Not A Real Card", "quantity": 4}, {"name": "Broken Profile", "quantity": 1}],
        {"Broken Profile": {"mana_cost": "{R}", "cmc": 1, "type_line": "Instant", "oracle_text": "Deal 3 damage."}},
        policy="aggro",
        fmt="legacy",
    )
    assert report["wins"] == 0
    assert "Not A Real Card" in report["unresolved_cards"]
    assert report["cards_simulated"] >= 0


def test_a_real_card_with_a_token_namesake_is_kept():
    from app.scripts.precon_stats import is_bulk_token

    oracle = {
        "Dinosaur Egg": {"type_line": "Creature — Dinosaur Egg", "layout": "normal"},
        "Champion of Wits": {"type_line": "Creature — Snake Wizard", "layout": "normal"},
        "Ornithopter": {"type_line": "Artifact Creature — Thopter", "layout": "normal"},
        "Akroma's Will": {"type_line": "Instant", "layout": "normal"},
    }
    assert not is_token_entry({"name": "Dinosaur Egg", "count": 1}, oracle)
    assert not is_token_entry({"name": "Champion of Wits", "count": 1}, oracle)
    assert not is_token_entry({"name": "Ornithopter", "count": 4}, oracle)
    # The token printing is skipped while indexing, so the real card wins.
    assert is_bulk_token({"name": "Ornithopter", "layout": "token", "set_type": "token"})
    assert is_bulk_token({"name": "Dinosaur Egg", "layout": "token", "set_type": "token"})
    assert not is_bulk_token({"name": "Ornithopter", "layout": "normal", "set_type": "masters"})
    assert is_token_entry({"name": "Treasure Token", "count": 1, "layout": "token"}, oracle)
    assert is_token_entry({"name": "Copy", "count": 1, "types": ["Token", "Creature"]}, {})
    assert not is_token_entry({"name": "Akroma's Will", "count": 1}, oracle)
    assert not is_token_entry({"name": "Secure the Wastes", "count": 1}, {"Secure the Wastes": {"type_line": "Sorcery", "layout": "normal"}})
