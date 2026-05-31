"""One-shot migration: add the set_type column on SQLite and backfill from
a known set_code → set_type map. Run after deploying the db_models.py change
that adds Card.set_type. Idempotent — re-running is safe.

Why this exists: full re-ingestion of default_cards is heavy (~500MB) and
all_cards is far heavier (~5GB). For the immediate goal of filtering joke /
funny / memorabilia cards out of generated decks, a static map of well-known
joke set codes covers ~95% of the offenders. Cards whose set_code isn't in
the map keep set_type=NULL — the pool filter treats NULL as "trusted normal
printing" so this is failure-open in the safe direction.

Usage:
    cd api && source .venv/bin/activate && python -m app.scripts.backfill_set_type
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import get_engine, session_scope
from app.db_models import Card


# Set codes that are categorically NOT competitive-format-legal in any of
# {standard, modern, pioneer, legacy, commander}. Cards from these sets
# should be excluded from the deckbuilding card pool entirely.
JOKE_OR_NONCOMPETITIVE_SETS: dict[str, str] = {
    # Un-sets (silver-bordered, joke)
    "ugl": "funny",
    "unh": "funny",
    "ust": "funny",
    "unf": "funny",
    "sunf": "funny",  # Unfinity stickers
    "und": "funny",  # Unsanctioned
    # Promo / memorabilia (most are alt-art reprints with no real legal status)
    "htr": "memorabilia",  # Heroes of the Realm
    "htr17": "memorabilia",
    "htr18": "memorabilia",
    "htr19": "memorabilia",
    "htr20": "memorabilia",
    # Alchemy / Arena-only
    "ymid": "alchemy",
    "yvow": "alchemy",
    "yneo": "alchemy",
    "ysnc": "alchemy",
    "ydmu": "alchemy",
    "ybro": "alchemy",
    "yone": "alchemy",
    "ymom": "alchemy",
    "ywoe": "alchemy",
    "ylci": "alchemy",
    "ymkm": "alchemy",
    "yotj": "alchemy",
    # Treasure Chest exclusives (MTGO only)
    "pf19": "promo",
    "pf20": "promo",
}


def ensure_column() -> None:
    """Add the set_type column on SQLite if it doesn't already exist."""
    eng = get_engine()
    inspector = inspect(eng)
    columns = {col["name"] for col in inspector.get_columns("cards")}
    if "set_type" in columns:
        return
    with eng.begin() as conn:
        conn.execute(text("ALTER TABLE cards ADD COLUMN set_type VARCHAR(32)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cards_set_type ON cards (set_type)"))


def backfill() -> dict[str, int]:
    counts: dict[str, int] = {}
    with session_scope() as session:
        for set_code, set_type in JOKE_OR_NONCOMPETITIVE_SETS.items():
            result = session.execute(
                text(
                    "UPDATE cards SET set_type = :st "
                    "WHERE LOWER(set_code) = :sc AND (set_type IS NULL OR set_type = '')"
                ),
                {"st": set_type, "sc": set_code.lower()},
            )
            counts[set_code] = result.rowcount or 0
    return counts


def main() -> None:
    ensure_column()
    counts = backfill()
    total = sum(counts.values())
    print(f"set_type backfilled for {total} cards across {len([k for k,v in counts.items() if v])} sets")
    for set_code, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if n:
            print(f"  {set_code}: {n}")


if __name__ == "__main__":
    main()
