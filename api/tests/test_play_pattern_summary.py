"""Play-pattern copy agrees with 'It will usually ...' for every cadence."""

from types import SimpleNamespace

from app.services.deck_analysis import DeckAnalysisService

BAD_VERBS = ("gets", "spends", "snowballs", "closes", "tries")


def _summary(*, curve: list[tuple[int, int]], fmt: str = "modern") -> str:
    points = [SimpleNamespace(mana_value=mana_value, card_count=count) for mana_value, count in curve]
    roles = [SimpleNamespace(role="threat", total_cards=8)]
    request = SimpleNamespace(format=fmt)
    return DeckAnalysisService._build_play_pattern_summary(None, request, roles, points)


def test_early_cadence_uses_base_verbs() -> None:
    text = _summary(curve=[(1, 10), (2, 6), (3, 4)])
    assert "It will usually get on board early and snowball pressure" in text
    assert "then try to convert incremental edges into a win" in text
    for verb in BAD_VERBS:
        assert verb not in text.split()


def test_setup_cadence_uses_base_verbs() -> None:
    text = _summary(curve=[(1, 4), (2, 2), (6, 3)])
    assert "It will usually spend its first turns setting up" in text
    assert "then try to convert incremental edges into a win" in text
    for verb in BAD_VERBS:
        assert verb not in text.split()


def test_high_end_finisher_uses_a_base_verb() -> None:
    text = _summary(curve=[(2, 4), (5, 8), (6, 2)])
    assert "It will usually spend its first turns setting up" in text
    assert "then close with a higher-end payoff package" in text
    for verb in BAD_VERBS:
        assert verb not in text.split()


def test_early_and_high_end_cadences_agree() -> None:
    text = _summary(curve=[(1, 14), (5, 8)])
    assert "It will usually get on board early and snowball pressure" in text
    assert "then close with a higher-end payoff package" in text
    for verb in BAD_VERBS:
        assert verb not in text.split()


def test_commander_note_still_follows_the_cadence() -> None:
    text = _summary(curve=[(1, 4)], fmt="commander")
    assert text.endswith("signature engine.")
    assert "spends" not in text
