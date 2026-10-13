"""Build the test-suite card database from a full Scryfall-ingested DB.

CI used to run against the 29-card sample JSON, which meant every test that
needed a real card pool was either skipped (``MTG_FULL_DATASET``) or written
against the developer's local 33k-card DB and failed in CI. This script cuts a
small, deterministic subset of the full DB that both use:

- every card named anywhere in ``app/`` or ``tests/`` source (builtin
  archetype anchors, mana-base tables, commander staples, test literals), in
  the corpus tables (archetypes, tournament decks) and in ``app/data`` JSON;
- every basic land (snow basics and Wastes included);
- a color-balanced, hash-ordered sample of legal cards per format, so the
  generator has a real pool to fill from;
- a few legendary creatures per color identity for commander tests.

The archetypes and tournament_decks tables are copied whole; card_profiles
and card_embeddings are copied for the selected cards.

Usage (from ``api/``, against the full DB)::

    python -m app.scripts.build_test_fixture            # writes tests/fixtures/cards.db.gz

Rerun it after re-ingesting Scryfall or when a new test needs cards that
aren't in the fixture (naming them in the test is enough).
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import itertools
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from app.config import APP_DIR, DATABASE_URL

API_DIR = APP_DIR.parent
DEFAULT_OUTPUT = API_DIR / "tests" / "fixtures" / "cards.db.gz"
FORMATS = ("standard", "pioneer", "modern", "legacy", "commander")
COLORS = ("W", "U", "B", "R", "G")
# Copied whole: small, and the generator's retrieval depends on all of them.
WHOLE_TABLES = ("archetypes", "tournament_decks")
PER_CARD_TABLES = {"card_profiles": "name", "card_embeddings": "name"}
# Test runs used to ingest tests/fixtures/decks_curated.json into the dev DB
# (example.com URLs). Keep that pollution out of the fixture.
WHOLE_TABLE_FILTERS = {"tournament_decks": " WHERE source_url IS NULL OR source_url NOT LIKE 'https://example.com/%'"}
SAMPLE_PER_BUCKET = 30
COMMANDERS_PER_IDENTITY = 4


def _stable_key(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8")).hexdigest()


def _string_literals(paths: list[Path]) -> set[str]:
    out: set[str] = set()
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) <= 160:
                out.add(node.value)
    return out


def _json_names(value: object, out: set[str]) -> None:
    """Collect every ``name`` / ``commander`` string inside a JSON value."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"name", "commander"} and isinstance(item, str):
                out.add(item)
            else:
                _json_names(item, out)
    elif isinstance(value, list):
        for item in value:
            _json_names(item, out)
    elif isinstance(value, str) and value[:1] in "[{":
        try:
            _json_names(json.loads(value), out)
        except ValueError:
            pass


def _referenced_names(conn: sqlite3.Connection) -> set[str]:
    sources = sorted((API_DIR / "app").rglob("*.py")) + sorted((API_DIR / "tests").rglob("*.py"))
    names = _string_literals(sources)
    for path in sorted((API_DIR / "app" / "data").glob("*.json")):
        _json_names(json.loads(path.read_text(encoding="utf-8")), names)
    for table in WHOLE_TABLES:
        for row in conn.execute(f"SELECT * FROM {table}"):
            for value in row:
                if isinstance(value, str):
                    _json_names(value, names)
    for row in conn.execute("SELECT commander FROM tournament_decks WHERE commander IS NOT NULL"):
        names.add(row[0])
    return names


def _select_cards(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name, normalized_name, type_line, color_identity, legalities, oracle_text FROM cards"
    ).fetchall()
    by_name = {row[0]: row for row in rows}
    by_normalized = {row[1]: row[0] for row in rows}
    # DFCs are referenced by front face ("Fable of the Mirror-Breaker").
    by_front = {row[0].split(" // ", 1)[0].lower(): row[0] for row in rows if " // " in row[0]}

    selected: set[str] = set()
    for raw in _referenced_names(conn):
        key = raw.strip()
        if key in by_name:
            selected.add(key)
        elif key.lower() in by_normalized:
            selected.add(by_normalized[key.lower()])
        elif key.split(" // ", 1)[0].lower() in by_front:
            selected.add(by_front[key.split(" // ", 1)[0].lower()])

    buckets: dict[tuple[str, frozenset[str]], list[str]] = {}
    commanders: dict[frozenset[str], list[str]] = {}
    for name, _normalized, type_line, identity_json, legalities_json, oracle_text in rows:
        front = type_line.split(" // ", 1)[0]
        if "Basic" in front.split("—", 1)[0].split() and "Land" in front:
            selected.add(name)
            continue
        identity = frozenset(json.loads(identity_json or "[]"))
        legalities = json.loads(legalities_json or "{}")
        if len(identity) <= 2:
            for fmt in FORMATS:
                if legalities.get(fmt) in {"legal", "restricted"}:
                    buckets.setdefault((fmt, identity), []).append(name)
        is_commander = ("Legendary" in front and "Creature" in front) or "can be your commander" in (oracle_text or "").lower()
        if is_commander and legalities.get("commander") == "legal":
            commanders.setdefault(identity, []).append(name)

    for names in buckets.values():
        selected.update(sorted(names, key=_stable_key)[:SAMPLE_PER_BUCKET])
    for size in range(0, 6):
        for combo in itertools.combinations(COLORS, size):
            pool = commanders.get(frozenset(combo), [])
            selected.update(sorted(pool, key=_stable_key)[:COMMANDERS_PER_IDENTITY])
    return selected


def build(source_db: Path, output: Path) -> dict[str, int]:
    source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    selected = _select_cards(source)

    with tempfile.TemporaryDirectory() as tmp:
        target_path = Path(tmp) / "cards.db"
        target = sqlite3.connect(target_path)
        tables = ["cards", *WHOLE_TABLES, *PER_CARD_TABLES]
        for (sql,) in source.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND tbl_name IN ({})".format(
                ",".join("?" * len(tables))
            ),
            tables,
        ):
            target.execute(sql)

        counts: dict[str, int] = {}
        placeholders = ",".join("?" * len(selected))
        ordered = sorted(selected)
        for table, column in [("cards", "name"), *PER_CARD_TABLES.items()]:
            rows = source.execute(f"SELECT * FROM {table} WHERE {column} IN ({placeholders})", ordered).fetchall()
            if rows:
                target.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)
            counts[table] = len(rows)
        for table in WHOLE_TABLES:
            rows = source.execute(f"SELECT * FROM {table}{WHOLE_TABLE_FILTERS.get(table, '')}").fetchall()
            if rows:
                target.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)
            counts[table] = len(rows)
        target.commit()
        target.execute("VACUUM")
        target.close()

        output.parent.mkdir(parents=True, exist_ok=True)
        # mtime=0 and no embedded filename keep rebuilds of the same data byte-identical.
        with open(target_path, "rb") as raw, open(output, "wb") as fh:
            with gzip.GzipFile(filename="", fileobj=fh, mode="wb", mtime=0, compresslevel=9) as gz:
                shutil.copyfileobj(raw, gz)
    source.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, default=None, help="full SQLite DB (default: DATABASE_URL)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    source = args.source or Path(DATABASE_URL.removeprefix("sqlite:///"))
    counts = build(source, args.output)
    size_kb = args.output.stat().st_size // 1024
    print(f"wrote {args.output} ({size_kb} KB): " + ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
