"""Per-card "Why?" notes and the shared role classifier."""

from __future__ import annotations

from app.main import generator, repository
from app.models import GenerateDeckRequest
from app.services.card_roles import primary_role


def test_roles_follow_card_type_not_coarse_tags() -> None:
    # Ingest tags put "land" on Goblin Guide, "creature" on Ashnod's Altar
    # and "spells" (→ engine) on every instant and sorcery.
    assert primary_role(repository.get_card("Goblin Guide")) == "threat"
    assert primary_role(repository.get_card("Ashnod's Altar")) != "threat"
    assert primary_role(repository.get_card("Lightning Bolt")) == "interaction"
    assert primary_role(repository.get_card("Lava Spike")) == "reach"


def test_notes_explain_each_card_specifically() -> None:
    deck = generator.generate(
        GenerateDeckRequest(format="modern", colors=["R"], playstyle_tags=["aggro"], include_cards=["Lightning Bolt"])
    )
    notes = {note.name: note.reason for note in deck.card_notes}
    nonbasic = [ref.name for ref in deck.mainboard if "Basic" not in (repository.get_card(ref.name).type_line or "")]
    assert set(nonbasic) <= set(notes), "every non-basic card gets a note, not just the first 15"
    assert notes["Lightning Bolt"].startswith("You asked for this card.")
    # In-game reasons only: what the card does, never where the list came from.
    assert "deals 3 damage" in notes["Lightning Bolt"]
    for reason in notes.values():
        assert "list this deck is built from" not in reason
        assert "retrieved shell or package set" not in reason


def test_mana_rocks_are_mana_development() -> None:
    assert primary_role(repository.get_card("Sol Ring")) == "mana development"


def test_commander_notes_describe_what_cards_do() -> None:
    deck = generator.generate(GenerateDeckRequest(format="commander", colors=["B", "G"]))
    notes = {note.name: note.reason for note in deck.card_notes}
    assert len(notes) >= 30
    for reason in notes.values():
        assert "round out the deck" not in reason
        assert "Commander staple" not in reason
        if deck.commander and " // " in deck.commander:
            assert deck.commander not in reason, "commander named by its front face"
    assert "adds two mana" in notes["Sol Ring"]


def test_planeswalker_note_names_its_abilities() -> None:
    from app.services.card_function import describe

    teferi = describe(repository.get_card("Teferi, Hero of Dominaria"))
    assert teferi == "its +1 draws a card and untaps lands, and its −3 tucks an opposing nonland permanent"
