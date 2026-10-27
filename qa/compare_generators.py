#!/usr/bin/env python
"""Compare the legacy generator with the optimizer-default path.

Uses the same card fixture as CI unless ``--database-url`` is set. Scores
both lists with ``evaluate_decklist`` (the deck-evaluation service). Does
not change ``MTG_USE_OPTIMIZER_DEFAULT``.

A win on this fixture is not a reason to flip the default: the production
pool is the full Scryfall ingest, and the annealer often keeps the legacy
list when the fitness gain is under 0.01. Re-run with ``--database-url``
pointed at that database before switching the flag.

Usage (from the repo root)::

    python3 qa/compare_generators.py
    python3 qa/compare_generators.py --limit 1 --games 40
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

QA_DIR = Path(__file__).resolve().parent
ROOT = QA_DIR.parent
API_DIR = ROOT / "api"
FIXTURE_DB = API_DIR / "tests" / "fixtures" / "cards.db.gz"
REPORT = QA_DIR / "OPTIMIZER_COMPARISON.md"

SCENARIOS = [
    {
        "name": "Modern mono-red aggro",
        "format": "modern",
        "colors": ["R"],
        "playstyle_tags": ["aggro", "spells"],
        "budget": 80,
    },
    {
        "name": "Modern Izzet spells",
        "format": "modern",
        "colors": ["U", "R"],
        "playstyle_tags": ["spells"],
        "budget": 120,
    },
    {
        "name": "Pioneer mono-black midrange",
        "format": "pioneer",
        "colors": ["B"],
        "playstyle_tags": ["midrange"],
        "budget": 100,
    },
    {
        "name": "Standard mono-white aggro",
        "format": "standard",
        "colors": ["W"],
        "playstyle_tags": ["aggro"],
        "budget": 60,
    },
]


def _prepare_database(database_url: str | None) -> tuple[str, str]:
    tmp_dir = Path(tempfile.mkdtemp(prefix="mtg-compare-db-"))
    if not database_url:
        db_path = tmp_dir / "cards.db"
        with gzip.open(FIXTURE_DB, "rb") as src, open(db_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return f"sqlite:///{db_path}", "CI fixture (about 2,000 cards)"
    if database_url.startswith("sqlite:///"):
        path = Path(database_url[len("sqlite:///") :]).expanduser().resolve()
        if (ROOT / "var") in path.parents:
            copy = tmp_dir / path.name
            shutil.copyfile(path, copy)
            return f"sqlite:///{copy}", f"temp copy of {path.name}"
        return f"sqlite:///{path}", path.name
    return database_url, "custom database"


def _list_key(cards) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((ref.name, ref.quantity) for ref in cards))


def _price(cards, repository) -> float:
    total = 0.0
    for ref in cards:
        card = repository.get_card(ref.name)
        if card and card.price_usd:
            total += card.price_usd * ref.quantity
    return round(total, 2)


def _score(deck, repository, games: int) -> dict:
    from app.services.deck_evaluation_service import evaluate_decklist

    return evaluate_decklist(
        format_id=deck.format,
        mainboard=deck.mainboard,
        repository=repository,
        games=games,
        seed=1729,
    )


def _run(repository, games: int, limit: int | None) -> list[dict]:
    from app.models import GenerateDeckRequest
    from app.services.deck_generator import DeckGenerator
    from app.services.deck_validator import DeckValidator
    from app.services.optimizer_default_path import generate_via_optimizer

    validator = DeckValidator(repository)
    generator = DeckGenerator(repository, validator)
    rows = []
    scenarios = SCENARIOS[:limit] if limit else SCENARIOS
    for spec in scenarios:
        request = GenerateDeckRequest(
            format=spec["format"],
            colors=spec["colors"],
            playstyle_tags=spec["playstyle_tags"],
            budget=spec["budget"],
        )
        started = time.perf_counter()
        legacy = generator.generate(request)
        legacy_seconds = round(time.perf_counter() - started, 1)
        started = time.perf_counter()
        optimized = generate_via_optimizer(
            request, repository=repository, validator=validator, generator=generator
        )
        optimizer_seconds = round(time.perf_counter() - started, 1)
        legacy_eval = _score(legacy, repository, games)
        optimized_eval = _score(optimized, repository, games)
        kept = _list_key(legacy.mainboard) == _list_key(optimized.mainboard)
        note = next((n for n in optimized.provenance.notes if "Simulator" in n), "")
        rows.append(
            {
                "name": spec["name"],
                "budget": spec["budget"],
                "kept_legacy": kept,
                "note": note,
                "legacy_seconds": legacy_seconds,
                "optimizer_seconds": optimizer_seconds,
                "legacy_legal": legacy.is_legal,
                "optimizer_legal": optimized.is_legal,
                "legacy_price": legacy.estimated_price_usd or _price(legacy.mainboard, repository),
                "optimizer_price": optimized.estimated_price_usd or _price(optimized.mainboard, repository),
                "legacy_win": legacy_eval["win_rate"],
                "optimizer_win": optimized_eval["win_rate"],
                "legacy_kill": legacy_eval["avg_kill_turn"],
                "optimizer_kill": optimized_eval["avg_kill_turn"],
                "legacy_consistency": legacy_eval["consistency"],
                "optimizer_consistency": optimized_eval["consistency"],
                "games": games,
            }
        )
        print(
            f"{spec['name']}: kept_legacy={kept} "
            f"win {legacy_eval['win_rate']:.3f} -> {optimized_eval['win_rate']:.3f} "
            f"in {optimizer_seconds}s",
            flush=True,
        )
    return rows


def _markdown(rows: list[dict], label: str, card_count: int | None, games: int) -> str:
    lines = [
        "# Optimizer vs legacy generator",
        "",
        f"Database: {label}.",
        f"Cards: {card_count if card_count is not None else 'unknown'}.",
        "Each optimized list is what `generate_via_optimizer` would return",
        "(the production annealer: 8 rounds, 3 proposals, 120 sims, seed 1729).",
        "Win rate, average kill turn, and consistency come from",
        f"`evaluate_decklist` on that returned list, {games} games, seed 1729.",
        "Commander is not in this table: the optimizer path returns the legacy",
        "Commander deck without annealing.",
        "",
        "The default stays `MTG_USE_OPTIMIZER_DEFAULT=false`. A result on the",
        "CI fixture (about 2,000 cards) is not a production result. Re-run",
        "`python3 qa/compare_generators.py --database-url sqlite:///...` against",
        "the full ingest before flipping the flag. The annealer also keeps the",
        "legacy list when fitness does not rise by at least 0.01.",
        "",
        "A win rate of 0.000 with kill turn at the cap means the goldfish",
        "never closed the game. Those rows still count: the optimizer returned",
        "the same list, so the scores match.",
        "",
        "| Scenario | Kept legacy | Legacy win | Optimizer win | Legacy kill | Optimizer kill | Legacy consistency | Optimizer consistency | Legacy $ | Optimizer $ | Optimizer seconds |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    wins = 0
    for row in rows:
        delta = row["optimizer_win"] - row["legacy_win"]
        if not row["kept_legacy"] and row["optimizer_legal"] and delta >= 0.03:
            wins += 1
        lines.append(
            "| {name} | {kept} | {lw:.3f} | {ow:.3f} | {lk:.2f} | {ok:.2f} | {lc:.3f} | {oc:.3f} | {lp:.2f} | {op:.2f} | {sec:.1f} |".format(
                name=row["name"],
                kept="yes" if row["kept_legacy"] else "no",
                lw=row["legacy_win"],
                ow=row["optimizer_win"],
                lk=row["legacy_kill"],
                ok=row["optimizer_kill"],
                lc=row["legacy_consistency"],
                oc=row["optimizer_consistency"],
                lp=row["legacy_price"],
                op=row["optimizer_price"],
                sec=row["optimizer_seconds"],
            )
        )
    lines.extend(["", "## Notes", ""])
    for row in rows:
        if row["note"]:
            lines.append(f"- {row['name']}: {row['note']}")
        lines.append(
            f"- {row['name']}: legacy legal={row['legacy_legal']}, "
            f"optimizer legal={row['optimizer_legal']}, "
            f"legacy generate {row['legacy_seconds']}s, "
            f"evaluation games={row['games']}."
        )
    lines.extend(
        [
            "",
            f"Scenarios where the optimizer changed the list, stayed legal, and gained at least 0.03 win rate: {wins} of {len(rows)}.",
            "That count is not a decision to switch the default.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database-url")
    parser.add_argument("--games", type=int, default=60)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args(argv)

    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MTG_API_KEY", "MTG_USE_OPTIMIZER_DEFAULT"):
        os.environ[key] = ""
    database_url, label = _prepare_database(args.database_url)
    os.environ["DATABASE_URL"] = database_url
    if str(API_DIR) not in sys.path:
        sys.path.insert(0, str(API_DIR))

    from sqlalchemy import func, select

    from app.db import session_scope
    from app.db_models import Card
    from app.services.card_repository import CardRepository

    repository = CardRepository()
    with session_scope() as session:
        card_count = int(session.scalar(select(func.count()).select_from(Card)) or 0)
    rows = _run(repository, args.games, args.limit)
    text = _markdown(rows, label, card_count, args.games)
    args.output.write_text(text)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
