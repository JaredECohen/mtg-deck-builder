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
    assert all("retrieved shell or package set" not in reason for reason in notes.values())
    assert all("mana" in reason for reason in notes.values())


def test_mana_rocks_are_mana_development() -> None:
    assert primary_role(repository.get_card("Sol Ring")) == "mana development"


def test_commander_notes_name_the_commander_and_staples() -> None:
    deck = generator.generate(GenerateDeckRequest(format="commander", colors=["B", "G"]))
    reasons = [note.reason for note in deck.card_notes]
    assert len(reasons) >= 30
    front_face = deck.commander.split(" // ")[0]
    assert all("round out the deck" not in reason for reason in reasons)
    assert any(front_face in reason for reason in reasons)
    assert all(" // " not in reason.split(".")[0] for reason in reasons), "commander named by its front face"
    staples = [note for note in deck.card_notes if note.name == "Sol Ring"]
    assert staples and staples[0].reason.startswith("A Commander staple")


def test_impulse_draw_is_card_advantage_and_walkers_are_threats() -> None:
    assert primary_role(repository.get_card("Light Up the Stage")) == "card advantage"
    assert primary_role(repository.get_card("Chandra, Torch of Defiance")) == "threat"
