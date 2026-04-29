from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.config import TOURNAMENT_DECK_PATH
from app.db import session_scope
from app.db_models import IngestionRun, TournamentDeck
from app.scripts.ingest_deck_source import normalize_raw_deck, normalized_record_payload
from app.scripts.sources import load_csv_decks, load_json_decks
from app.services.card_repository import CardRepository
from app.services.database_bootstrap import create_schema


SOURCE_PRIORITY = {
    "commander_csv": 40,
    "curated_csv": 35,
    "curated_json": 30,
    "sample": 10,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest tournament or commander deck corpora.")
    parser.add_argument("--source-path", action="append", help="Path to a JSON or CSV deck source.")
    parser.add_argument("--source-format", choices=["json", "csv"], help="Force a source format.")
    parser.add_argument("--source-name", help="Override the logical source name for all provided paths.")
    return parser.parse_args(argv)


def resolve_sources(args: argparse.Namespace) -> list[tuple[Path, str, str]]:
    if not args.source_path:
        return [(TOURNAMENT_DECK_PATH, "json", "sample")]

    resolved: list[tuple[Path, str, str]] = []
    for raw_path in args.source_path:
        path = Path(raw_path).resolve()
        source_format = args.source_format or infer_format(path)
        source_name = args.source_name or infer_source_name(path, source_format)
        resolved.append((path, source_format, source_name))
    return resolved


def infer_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        return "csv"
    raise ValueError(f"Unsupported source format for {path}")


def infer_source_name(path: Path, source_format: str) -> str:
    stem = path.stem.lower()
    if "commander" in stem and source_format == "csv":
        return "commander_csv"
    if source_format == "csv":
        return "curated_csv"
    return "curated_json"


def load_source(path: Path, source_format: str) -> list[dict[str, object]]:
    if source_format == "json":
        return load_json_decks(path)
    if source_format == "csv":
        return load_csv_decks(path)
    raise ValueError(f"Unsupported source format {source_format}")


def should_replace(existing: TournamentDeck, incoming_payload: dict[str, object], incoming_source: str) -> bool:
    existing_priority = SOURCE_PRIORITY.get(existing.source, 0)
    incoming_priority = SOURCE_PRIORITY.get(incoming_source, 0)
    existing_confidence = existing.confidence or 0.0
    incoming_confidence = float(incoming_payload.get("confidence") or 0.0)
    if incoming_priority != existing_priority:
        return incoming_priority > existing_priority
    if incoming_confidence != existing_confidence:
        return incoming_confidence > existing_confidence
    incoming_event_date = str(incoming_payload.get("event_date") or "")
    existing_event_date = existing.event_date or ""
    return incoming_event_date >= existing_event_date


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    sources = resolve_sources(args)
    result = ingest_sources(sources)
    print(json.dumps(result))


def ingest_sources(sources: list[tuple[Path, str, str]]) -> dict[str, object]:
    create_schema()
    repository = CardRepository()

    processed = 0
    inserted = 0
    replaced = 0
    skipped = 0
    with session_scope() as session:
        run = IngestionRun(source="tournament_decks", status="running", records_processed=0)
        session.add(run)
        session.flush()

        for path, source_format, source_name in sources:
            raw_decks = load_source(path, source_format)
            for raw_deck in raw_decks:
                normalized = normalize_raw_deck(
                    repository,
                    raw_deck,
                    source_name=source_name,
                    ingested_from=path,
                )
                payload = normalized_record_payload(normalized)
                existing = session.scalar(
                    select(TournamentDeck).where(TournamentDeck.dedupe_key == normalized.dedupe_key)
                )
                if existing is not None:
                    if not should_replace(existing, payload, source_name):
                        skipped += 1
                        processed += 1
                        continue
                    payload["id"] = existing.id
                    replaced += 1
                else:
                    inserted += 1
                session.merge(TournamentDeck(**payload))
                processed += 1

        run.status = "completed"
        run.records_processed = processed
        run.notes = json.dumps(
            {
                "sources": [
                    {"path": str(path), "format": source_format, "source_name": source_name}
                    for path, source_format, source_name in sources
                ],
                "inserted": inserted,
                "replaced": replaced,
                "skipped": skipped,
            }
        )

    return {
        "status": "ok",
        "records_processed": processed,
        "inserted": inserted,
        "replaced": replaced,
        "skipped": skipped,
    }


if __name__ == "__main__":
    main()
