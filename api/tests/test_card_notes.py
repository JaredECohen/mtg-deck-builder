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
