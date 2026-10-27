"""Profile coverage: a full ingest is stale below 90%, the fixture is not."""

from app.scripts.build_card_profiles import want_every_card
from app.services.profile_coverage import coverage_report


def test_full_ingest_at_sixty_five_percent_is_stale() -> None:
    # The production gap this change is aimed at: Modern-only profiling.
    report = coverage_report(35_134, 22_718)
    assert report["status"] == "stale"
    assert report["target"] == 0.90
    assert report["coverage"] < 0.90


def test_full_ingest_at_ninety_percent_is_ok() -> None:
    report = coverage_report(35_134, 32_000)
    assert report["status"] == "ok"


def test_fixture_sized_database_keeps_the_lower_bar() -> None:
    # tests/fixtures/cards.db.gz is ~1.9k cards, ~85% profiled.
    report = coverage_report(1_928, 1_638)
    assert report["status"] == "ok"
    assert report["target"] == 0.60


def test_empty_database_is_not_stale() -> None:
    assert coverage_report(0, 0)["status"] == "ok"


def test_profile_builder_defaults_to_every_card() -> None:
    assert want_every_card(modern_only=False, all_flag=False) is True
    assert want_every_card(modern_only=True, all_flag=False) is False
    assert want_every_card(modern_only=True, all_flag=True) is True
