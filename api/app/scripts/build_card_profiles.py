"""Build CardProfile rows for every Modern-legal card in the DB.

Usage::

    python -m app.scripts.build_card_profiles                 # all Modern-legal
    python -m app.scripts.build_card_profiles --all           # every card
    python -m app.scripts.build_card_profiles --rebuild       # bump version
    python -m app.scripts.build_card_profiles --limit 100     # smoke test

The script is idempotent. Existing rows whose ``profile_version`` matches
the current code version are skipped unless ``--rebuild`` is passed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from app.config import CARD_CACHE_PATH
from app.db import session_scope
from app.db_models import Card, CardProfile as CardProfileRow
from app.oracle.profile import PROFILE_VERSION
from app.oracle.ast_to_profile import build_card_profile


def _load_cards_from_db(session: Session, modern_only: bool, limit: int | None) -> list[dict]:
    query = session.query(Card)
    if limit:
        query = query.limit(limit)
    cards: list[dict] = []
    for row in query:
        if modern_only:
            legality = (row.legalities or {}).get("modern")
            if legality not in {"legal", "restricted"}:
                continue
        cards.append(_card_row_to_dict(row))
    return cards


def _card_row_to_dict(row: Card) -> dict:
    return {
        "oracle_id": row.oracle_id,
        "scryfall_id": row.scryfall_id,
        "name": row.name,
        "mana_cost": row.mana_cost,
        "mana_value": row.mana_value,
        "type_line": row.type_line,
        "oracle_text": row.oracle_text or "",
        "keywords": row.keywords or [],
        "tags": row.tags or [],
        "color_identity": row.color_identity or [],
        "colors": row.colors or [],
    }


def _load_cards_from_sample(modern_only: bool, limit: int | None) -> list[dict]:
    cards = json.loads(Path(CARD_CACHE_PATH).read_text())
    if modern_only:
        cards = [c for c in cards if (c.get("legalities") or {}).get("modern") in {"legal", "restricted"}]
    if limit:
        cards = cards[:limit]
    out = []
    for c in cards:
        out.append({
            **c,
            "oracle_id": c.get("oracle_id") or c.get("name"),
        })
    return out


def _existing_profile_keys(session: Session, version: int) -> set[str]:
    rows = session.query(CardProfileRow.card_id).filter(CardProfileRow.profile_version == version).all()
    return {r[0] for r in rows}


def _persist_profile(session: Session, profile) -> None:
    payload = profile.to_dict()
    existing = session.get(CardProfileRow, profile.card_id)
    if existing is None:
        existing = CardProfileRow(card_id=profile.card_id)
        session.add(existing)
    existing.name = profile.name
    existing.profile_version = profile.profile_version
    existing.parse_method = profile.parse_method
    existing.parse_coverage = profile.parse_coverage
    existing.cost_vector = payload["cost_vector"]
    existing.effect_vector = payload["effect_vector"]
    existing.role_weights = payload["role_weights"]
    existing.combo_primitives = payload["combo_primitives"]
    existing.oracle_ast = payload["oracle_ast"]
    existing.notes = payload["notes"]


def _iter_cards(args: argparse.Namespace) -> Iterable[dict]:
    if args.from_sample:
        yield from _load_cards_from_sample(modern_only=not args.all, limit=args.limit)
        return
    try:
        with session_scope() as session:
            yield from _load_cards_from_db(session, modern_only=not args.all, limit=args.limit)
    except Exception as exc:
        print(f"[warn] DB read failed ({exc}); falling back to sample JSON", file=sys.stderr)
        yield from _load_cards_from_sample(modern_only=not args.all, limit=args.limit)


def run(args: argparse.Namespace) -> int:
    cards = list(_iter_cards(args))
    if not cards:
        print("no cards found", file=sys.stderr)
        return 1

    if args.dry_run:
        sample = build_card_profile(cards[0])
        print(json.dumps(sample.to_dict(), indent=2)[:2000])
        return 0

    written = 0
    skipped = 0
    failed: list[tuple[str, str]] = []
    coverage_sum = 0.0
    pattern_count = 0
    fallback_count = 0

    with session_scope() as session:
        existing = set() if args.rebuild else _existing_profile_keys(session, PROFILE_VERSION)
        for card in cards:
            try:
                profile = build_card_profile(card)
            except Exception as exc:
                failed.append((card.get("name") or "<unknown>", str(exc)))
                continue
            coverage_sum += profile.parse_coverage
            if profile.parse_method == "pattern":
                pattern_count += 1
            else:
                fallback_count += 1
            if not args.rebuild and profile.card_id in existing:
                skipped += 1
                continue
            _persist_profile(session, profile)
            written += 1
            if written % 500 == 0:
                session.flush()
                print(f"  wrote {written} profiles…")

    total = len(cards)
    avg_coverage = coverage_sum / max(1, total)
    print(f"done: total={total} written={written} skipped={skipped} failed={len(failed)}")
    print(f"  pattern={pattern_count} fallback={fallback_count} avg_coverage={avg_coverage:.3f}")
    if failed:
        print("  first failures:")
        for name, err in failed[:10]:
            print(f"    {name}: {err}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Profile every card, not just Modern-legal")
    parser.add_argument("--rebuild", action="store_true", help="Re-profile cards even if a current-version row exists")
    parser.add_argument("--limit", type=int, default=None, help="Limit cards for smoke testing")
    parser.add_argument("--from-sample", action="store_true", help="Read cards from sample JSON instead of DB")
    parser.add_argument("--dry-run", action="store_true", help="Print one profile and exit")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
