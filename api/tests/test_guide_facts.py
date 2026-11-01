"""Token cards in an official product list are not part of the deck."""

from app.scripts.build_guide_facts import is_token_entry, is_token_type_line


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


def test_dinosaur_egg_is_filtered_and_a_real_spell_is_not():
    oracle = {
        "Dinosaur Egg": {"type_line": "Token Creature — Dinosaur Egg", "layout": "token"},
        "Akroma's Will": {"type_line": "Instant", "layout": "normal"},
    }
    assert is_token_entry({"name": "Dinosaur Egg", "count": 1}, oracle)
    assert is_token_entry({"name": "Treasure Token", "count": 1, "layout": "token"}, oracle)
    assert is_token_entry({"name": "Copy", "count": 1, "types": ["Token", "Creature"]}, {})
    assert not is_token_entry({"name": "Akroma's Will", "count": 1}, oracle)
    assert not is_token_entry({"name": "Secure the Wastes", "count": 1}, {"Secure the Wastes": {"type_line": "Sorcery", "layout": "normal"}})
