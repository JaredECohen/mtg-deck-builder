"""Built-in seed detection must match whole words and respect the requested
colors (2026-09-19). The workshop's default brief — "Build me a strong Modern
prowess deck…" — matched Mono-Green Tron through the substring "tron" in
"strong"; the blend then carried a green ramp seed's name and tags into a U/R
prowess deck ("Mono-Green Tron + Mono-Red Prowess") while color gating dropped
every Tron card."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import builtin_archetypes as ba

client = TestClient(app)

DEFAULT_BRIEF = "Build me a strong Modern prowess deck that feels explosive and is still friendly to a newer player."


def _seed(id_: str, name: str, keywords: tuple[str, ...], colors: tuple[str, ...]) -> ba.BuiltinArchetype:
    return ba.BuiltinArchetype(
        id=id_, display_name=name, keywords=keywords, formats=("modern",),
        colors=colors, playstyle_tags=(), theme_tags=(), anchor_cards=(("Lightning Bolt", 4),),
    )


def test_keywords_match_whole_words_not_substrings():
    tron = _seed("tron", "Mono-Green Tron", ("mono-green tron", "tron"), ("G",))
    assert ba._find_matching_keyword(tron, "a strong deck") is None
    assert ba._find_matching_keyword(tron, "an electron microscope") is None
    assert ba._find_matching_keyword(tron, "mono-green tron please") == "mono-green tron"
    assert ba._find_matching_keyword(tron, "urza tron") == "tron"
    assert ba._find_matching_keyword(tron, "trons are fun") == "tron"
    assert ba._find_matching_keyword(tron, "tron.") == "tron"

    mill = _seed("mill", "Mill", ("mill",), ("U", "B"))
    assert ba._find_matching_keyword(mill, "budget of a million") is None
    storm = _seed("storm", "Storm", ("storm",), ("U", "R"))
    assert ba._find_matching_keyword(storm, "runs brainstorm") is None
    assert ba._find_matching_keyword(storm, "a storm deck") == "storm"


def test_default_workshop_brief_matches_prowess_only():
    ids = [m.id for m in ba.detect_builtin_archetypes(DEFAULT_BRIEF, "modern")]
    assert ids == ["modern-mono-red-prowess"], ids


def test_prefer_color_compatible_drops_off_color_seeds_but_never_all():
    tron = _seed("tron", "Mono-Green Tron", ("tron",), ("G",))
    prowess = _seed("prowess", "Mono-Red Prowess", ("prowess",), ("R",))
    colorless = _seed("affinity", "Affinity", ("affinity",), ())
    assert ba.prefer_color_compatible([tron, prowess, colorless], ["U", "R"]) == [prowess, colorless]
    assert ba.prefer_color_compatible([tron, prowess], []) == [tron, prowess], "no colors → unchanged"
    assert ba.prefer_color_compatible([tron], ["U", "R"]) == [tron], "nothing compatible → unchanged"
    assert ba.prefer_color_compatible([prowess], ["r"]) == [prowess], "case-insensitive"


def test_generated_title_no_longer_carries_the_phantom_seed():
    resp = client.post(
        "/v1/decks/generate",
        json={"format": "modern", "colors": ["U", "R"], "playstyle_tags": ["aggro", "spells"],
              "mode": "constraint-aware", "prompt": DEFAULT_BRIEF},
    )
    assert resp.status_code == 200, resp.text
    deck = resp.json()
    names = " ".join([deck["title"], (deck.get("selected_archetype") or {}).get("name", "")] + deck["source_archetypes"])
    assert "Tron" not in names, names
    assert "Prowess" in names, names
