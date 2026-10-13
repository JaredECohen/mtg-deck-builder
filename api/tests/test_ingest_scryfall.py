"""Scryfall ingest: bulk-file formats, reissued oracle ids, data freshness."""

from __future__ import annotations

import gzip
import json
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db_models import Base, Card
from app.models import CardRecord
from app.scripts.ingest_scryfall import _iter_bulk_cards
from app.services.card_repository import CardRepository

_ROWS = [{"name": "A"}, {"name": "B"}]


def test_reads_gzipped_jsonl_plain_jsonl_and_json_arrays(tmp_path):
    lines = "\n".join(json.dumps(r) for r in _ROWS) + "\n"
    (tmp_path / "a.jsonl.gz").write_bytes(gzip.compress(lines.encode()))
    (tmp_path / "b.jsonl").write_text(lines)
    (tmp_path / "c.json").write_text(json.dumps(_ROWS))
    for name in ("a.jsonl.gz", "b.jsonl", "c.json"):
        assert [row["name"] for row in _iter_bulk_cards(tmp_path / name)] == ["A", "B"]


def test_card_data_as_of_ignores_preview_cards_with_future_dates(monkeypatch):
    repo = CardRepository()
    cards = [
        CardRecord(name="Old", type_line="Instant", released_at="2026-07-17"),
        CardRecord(name="Preview", type_line="Instant", released_at="2027-04-09"),
    ]
    monkeypatch.setattr(CardRepository, "_all_cards_cache", cards, raising=False)
    monkeypatch.setitem(repo.__dict__, "_all_cards_cache", cards)
    assert repo.card_data_as_of(today=date(2026, 10, 12)) == "2026-07-17"
    assert repo.card_data_is_stale(today=date(2026, 10, 12)) is True
    assert repo.card_data_is_stale(today=date(2026, 8, 1)) is False


def test_reissued_oracle_id_replaces_the_stale_row(monkeypatch, tmp_path):
    """Scryfall can issue a new oracle_id for an existing name; the ingest
    must replace the old row instead of failing the unique-name constraint."""
    import app.scripts.ingest_scryfall as ingest

    engine = create_engine(f"sqlite:///{tmp_path / 'cards.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)

    def card(oracle_id: str) -> dict:
        return {
            "object": "card", "oracle_id": oracle_id, "id": oracle_id + "-print", "name": "Very Cryptic Command",
            "lang": "en", "layout": "normal", "type_line": "Instant", "set_type": "funny", "set": "ust",
            "legalities": {}, "prices": {}, "released_at": "2017-12-08",
        }

    with factory() as session:
        session.merge(Card(**{k: v for k, v in ingest.normalize_card(card("old-id")).items()}))
        session.commit()

    bulk = tmp_path / "bulk.jsonl"
    bulk.write_text(json.dumps(card("new-id")) + "\n")
    from contextlib import contextmanager

    @contextmanager
    def scope():
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    class _Resp:
        def raise_for_status(self):
            return self

        def json(self):
            return {"data": [{"type": "default_cards", "jsonl_download_uri": "https://example.invalid/bulk.jsonl"}]}

    class _Client:
        def __init__(self, *a, **k): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return _Resp()

    monkeypatch.setattr(ingest, "session_scope", scope)
    monkeypatch.setattr(ingest, "create_schema", lambda: None)
    monkeypatch.setattr(ingest.httpx, "Client", _Client)
    monkeypatch.setattr(ingest, "_download_bulk", lambda client, entry, dest: dest.write_bytes(bulk.read_bytes()))
    ingest.main()

    with factory() as session:
        rows = session.execute(select(Card.oracle_id, Card.set_type)).all()
    assert rows == [("new-id", "funny")]  # replaced, and set_type is now stored
