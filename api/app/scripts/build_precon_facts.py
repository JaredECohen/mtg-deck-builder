"""Build precon_facts.json from the MTGJSON snapshot and Scryfall oracle cards.

The deck lists are the committed official snapshot (MIT, via MTGJSON): the
Commander precons and Pioneer Challenger Decks ``ingest_official_decks``
keeps. Collector products are already excluded there. Rules text and types
come from the Scryfall oracle-cards bulk file. Prices are the lowest nonfoil
``prices.usd`` across English printings in the default-cards bulk file, not
the sealed product's exact printing and not the single printing attached to
the oracle card (that printing is often an unpriced new set). A card with no
nonfoil USD on any English printing is unpriced and left out of the sum.

Nothing here calls a paid API or an LLM. Regenerate from ``api/``::

    python -m app.scripts.build_precon_facts

The oracle file is cached under /tmp/mtgdata. Pass ``--oracle`` to reuse a
file you already downloaded.
"""

from __future__ import annotations

import argparse
import gzip
import json
import urllib.request
from pathlib import Path

from app.models import CardRecord
from app.scripts.build_guide_facts import TOKEN_LAYOUTS, is_token_type_line
from app.scripts.ingest_official_decks import USER_AGENT
from app.scripts.precon_stats import (
    distribution,
    is_draw,
    is_land_type,
    is_ramp,
    is_removal,
    line_usd,
    parse_usd,
    sum_usd,
)
from app.services.brackets import assess, bracket_data

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / "api" / "app" / "data" / "official_decks.json"
OUT = ROOT / "web" / "src" / "data" / "precon_facts.json"
CACHE = Path("/tmp/mtgdata")
BULK_INDEX = "https://api.scryfall.com/bulk-data"


class _Repo:
    def __init__(self, cards: dict[str, CardRecord]) -> None:
        self._cards = cards

    def get_card(self, name: str) -> CardRecord | None:
        return self._cards.get(name)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    temporary = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
    temporary.replace(dest)


def _face_text(card: dict) -> str:
    text = str(card.get("oracle_text") or "")
    if text.strip():
        return text
    parts = []
    for face in card.get("card_faces") or []:
        face_text = str(face.get("oracle_text") or "")
        if face_text:
            parts.append(face_text)
    return "\n".join(parts)


def _face_type(card: dict) -> str:
    type_line = str(card.get("type_line") or "")
    if type_line:
        return type_line
    faces = [str(face.get("type_line") or "") for face in card.get("card_faces") or [] if face.get("type_line")]
    return " // ".join(faces)


def load_min_usd(path: Path, wanted: set[str]) -> dict[str, float]:
    """Lowest nonfoil USD for each name in the default-cards bulk file."""
    best: dict[str, float] = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            card = json.loads(line)
            name = card.get("name")
            if name not in wanted:
                continue
            usd = parse_usd((card.get("prices") or {}).get("usd"))
            if usd is None:
                continue
            current = best.get(name)
            if current is None or usd < current:
                best[name] = usd
    return best


def load_oracle(path: Path, wanted: set[str]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            card = json.loads(line)
            name = card.get("name")
            if name not in wanted or name in found:
                continue
            prices = card.get("prices") or {}
            found[name] = {
                "name": name,
                "type_line": _face_type(card),
                "oracle_text": _face_text(card),
                "cmc": card.get("cmc") or 0,
                "usd": parse_usd(prices.get("usd")),
                "layout": str(card.get("layout") or ""),
                "color_identity": list(card.get("color_identity") or []),
                "legalities": card.get("legalities") or {},
            }
            if len(found) == len(wanted):
                break
    return found


def resolve_card(name: str, oracle: dict[str, dict]) -> dict | None:
    if name in oracle:
        return oracle[name]
    if " // " in name:
        return oracle.get(name.split(" // ", 1)[0])
    return None


def _is_token(info: dict | None) -> bool:
    if info is None:
        return False
    if info.get("layout") in TOKEN_LAYOUTS:
        return True
    return is_token_type_line(str(info.get("type_line") or ""))


def _curve(cards: list[dict]) -> list[dict]:
    buckets = [0] * 8
    for card in cards:
        if card["land"] or card["token"] or card["missing"]:
            continue
        mana_value = min(7, int(float(card["cmc"])))
        buckets[mana_value] += card["quantity"]
    return [{"mana_value": mana_value, "card_count": count} for mana_value, count in enumerate(buckets)]


def _classify_board(entries: list[dict], oracle: dict[str, dict]) -> list[dict]:
    rows = []
    for entry in entries:
        name = str(entry.get("name") or "")
        quantity = int(entry.get("quantity") or 0)
        if not name or quantity <= 0:
            continue
        info = resolve_card(name, oracle)
        token = _is_token(info)
        missing = info is None
        type_line = "" if info is None else info["type_line"]
        text = "" if info is None else info["oracle_text"]
        land = bool(info) and not token and is_land_type(type_line)
        rows.append(
            {
                "name": name,
                "quantity": quantity,
                "missing": missing,
                "token": token,
                "land": land,
                "ramp": bool(info) and not token and is_ramp(type_line, text),
                "draw": bool(info) and not token and is_draw(type_line, text),
                "removal": bool(info) and not token and is_removal(type_line, text),
                "cmc": 0 if info is None else info["cmc"],
                "usd": None if info is None else info["usd"],
                "legalities": {} if info is None else info["legalities"],
                "type_line": type_line,
                "oracle_text": text,
            }
        )
    return rows


def _names(rows: list[dict], flag: str) -> list[dict]:
    return [{"name": row["name"], "quantity": row["quantity"]} for row in rows if row[flag]]


def _copies(rows: list[dict], flag: str) -> int:
    return sum(row["quantity"] for row in rows if row[flag])


def _price_block(rows: list[dict]) -> dict:
    lines = []
    unpriced = []
    for row in rows:
        if row["token"]:
            continue
        amount = line_usd(row["usd"], row["quantity"])
        if amount is None:
            if row["name"] not in unpriced:
                unpriced.append(row["name"])
        else:
            lines.append(amount)
    return {"total_usd": sum_usd(lines), "priced_cards": len(lines), "unpriced": unpriced}


def _record(deck: dict, data: dict) -> dict:
    return CardRecord(
        name=deck["name"],
        type_line=deck["type_line"],
        oracle_text=deck["oracle_text"],
        mana_value=float(deck["cmc"] or 0),
        legalities=deck["legalities"],
    )


def _bracket(names: list[str], rows_by_name: dict[str, dict]) -> dict:
    cards = {name: _record(rows_by_name[name], {}) for name in names if name in rows_by_name and not rows_by_name[name]["missing"]}
    assessment = assess(names, _Repo(cards))
    return {
        "estimated": assessment.estimated,
        "game_changers": list(assessment.game_changers),
        "mass_land_denial": list(assessment.mass_land_denial),
        "extra_turns": list(assessment.extra_turns),
        "tutors": list(assessment.tutors),
        "two_card_combos": [list(pair) for pair in assessment.two_card_combos],
        "game_changers_as_of": assessment.game_changers_as_of,
    }


def build_deck(deck: dict, oracle: dict[str, dict], *, game_changers: frozenset[str]) -> dict:
    main_rows = _classify_board(deck.get("mainboard") or [], oracle)
    side_rows = _classify_board(deck.get("sideboard") or [], oracle)
    commanders = [{"name": name, "quantity": 1} for name in deck.get("commanders") or [] if name]
    command_rows = _classify_board(commanders, oracle)
    priced = _price_block(main_rows + side_rows + command_rows)
    playable = [row for row in main_rows + command_rows if not row["token"]]
    by_name = {row["name"]: row for row in playable}
    bracket_names = [row["name"] for row in command_rows if not row["token"]] + [
        row["name"] for row in main_rows if not row["token"]
    ]
    illegal_format = deck.get("format") or "commander"
    illegal = sorted(
        {
            row["name"]
            for row in main_rows + side_rows + command_rows
            if not row["token"] and row["legalities"].get(illegal_format) in {"banned", "not_legal"}
        }
    )
    gc_copies = sum(row["quantity"] for row in main_rows + command_rows if row["name"] in game_changers and not row["token"])
    identity = [color for color in deck.get("color_identity") or [] if color in "WUBRG"]
    return {
        "id": deck["id"],
        "file_name": deck.get("file_name"),
        "name": deck["name"],
        "format": deck.get("format"),
        "type": deck.get("type"),
        "release_date": deck.get("release_date"),
        "source_url": deck.get("source_url"),
        "commanders": list(deck.get("commanders") or []),
        "color_identity": identity,
        "mainboard_cards": sum(row["quantity"] for row in main_rows if not row["token"]),
        "sideboard_cards": sum(row["quantity"] for row in side_rows if not row["token"]),
        "land_count": _copies(main_rows, "land"),
        "nonland_count": sum(point["card_count"] for point in _curve(main_rows)),
        "ramp_count": _copies(main_rows, "ramp"),
        "draw_count": _copies(main_rows, "draw"),
        "removal_count": _copies(main_rows, "removal"),
        "commander_ramp": _copies(command_rows, "ramp"),
        "commander_draw": _copies(command_rows, "draw"),
        "commander_removal": _copies(command_rows, "removal"),
        "ramp_cards": _names(main_rows, "ramp"),
        "draw_cards": _names(main_rows, "draw"),
        "removal_cards": _names(main_rows, "removal"),
        "mana_curve": _curve(main_rows),
        "price_usd": priced["total_usd"],
        "priced_cards": priced["priced_cards"],
        "unpriced": priced["unpriced"],
        "missing_oracle": [row["name"] for row in main_rows + side_rows + command_rows if row["missing"]],
        "tokens_skipped": [row["name"] for row in main_rows + side_rows + command_rows if row["token"]],
        "game_changers": sorted({row["name"] for row in main_rows + command_rows if row["name"] in game_changers and not row["token"]}),
        "game_changer_copies": gc_copies,
        "bracket": _bracket(bracket_names, by_name),
        "illegal_in_format": illegal,
    }


def _index(decks: list[dict]) -> dict[str, dict]:
    return {deck["id"]: deck for deck in decks}


def _labeled(dist: dict, decks: dict[str, dict]) -> dict:
    labeled = dict(dist)
    for key in ("lowest", "highest"):
        labeled[key] = [
            {"id": row["id"], "name": decks[row["id"]]["name"], "value": row["value"]} for row in dist[key]
        ]
    return labeled


def summarize(decks: list[dict]) -> dict:
    by_id = _index(decks)
    commanders = [deck for deck in decks if deck["format"] == "commander"]

    def dist_of(key: str, *, ndigits: int = 1) -> dict:
        return _labeled(distribution([(deck["id"], deck[key]) for deck in commanders], ndigits=ndigits), by_id)

    identities: dict[str, int] = {}
    for deck in commanders:
        label = "".join(deck["color_identity"]) or "C"
        identities[label] = identities.get(label, 0) + 1
    identity_rows = sorted(identities.items(), key=lambda item: (-item[1], item[0]))
    bracket_counts = {str(level): 0 for level in (2, 3, 4)}
    for deck in commanders:
        level = str(deck["bracket"]["estimated"])
        bracket_counts[level] = bracket_counts.get(level, 0) + 1
    unpriced_decks = [deck for deck in commanders if deck["unpriced"]]
    return {
        "official_decks": len(decks),
        "commander_precons": len(commanders),
        "pioneer_challenger": sum(1 for deck in decks if deck["format"] == "pioneer"),
        "lands": dist_of("land_count"),
        "ramp": dist_of("ramp_count"),
        "draw": dist_of("draw_count"),
        "removal": dist_of("removal_count"),
        "price": dist_of("price_usd", ndigits=2),
        "price_complete": _labeled(
            distribution([(deck["id"], deck["price_usd"]) for deck in commanders if not deck["unpriced"]], ndigits=2),
            by_id,
        ),
        "precons_fully_priced": sum(1 for deck in commanders if not deck["unpriced"]),
        "color_identity": [
            {"identity": label, "decks": count, "pct": round(100 * count / len(commanders), 1)}
            for label, count in identity_rows
        ],
        "bracket_floors": bracket_counts,
        "precons_with_unpriced": len(unpriced_decks),
        "precons_with_a_game_changer": sum(1 for deck in commanders if deck["game_changers"]),
        "precons_missing_oracle": sum(1 for deck in commanders if deck["missing_oracle"]),
    }


def game_changer_report(commanders: list[dict], oracle: dict[str, dict], names: list[str]) -> list[dict]:
    rows = []
    for name in names:
        info = resolve_card(name, oracle)
        precons = [
            {"id": deck["id"], "name": deck["name"], "release_date": deck.get("release_date")}
            for deck in commanders
            if name in deck["game_changers"]
        ]
        precons.sort(key=lambda row: (row["release_date"] or "", row["name"]))
        rows.append(
            {
                "name": name,
                "usd": None if info is None else info["usd"],
                "unpriced": info is None or info["usd"] is None,
                "missing_oracle": info is None,
                "precon_count": len(precons),
                "precons": precons,
            }
        )
    rows.sort(key=lambda row: (-row["precon_count"], row["name"]))
    return rows


def _bulk_item(bulk_type: str) -> tuple[str, str]:
    index_path = CACHE / "scryfall-bulk.json"
    payload = None
    if index_path.exists():
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        request = urllib.request.Request(BULK_INDEX, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(json.dumps(payload), encoding="utf-8")
    for item in payload.get("data") or []:
        if item.get("type") == bulk_type:
            return str(item["jsonl_download_uri"]), str(item.get("updated_at") or "")
    raise RuntimeError(f"Scryfall bulk-data index has no {bulk_type} file")


def build(oracle_path: Path | None = None, prices_path: Path | None = None) -> dict:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    decks = [deck for deck in snapshot.get("decks") or [] if isinstance(deck, dict)]
    data = bracket_data()
    game_changers = data["game_changers"]
    wanted: set[str] = set(game_changers)
    for deck in decks:
        boards = (deck.get("mainboard") or []) + (deck.get("sideboard") or [])
        names = [card.get("name") for card in boards] + list(deck.get("commanders") or [])
        for name in names:
            if not name:
                continue
            wanted.add(str(name))
            if " // " in str(name):
                wanted.add(str(name).split(" // ", 1)[0])
    oracle_url_value, updated = _bulk_item("oracle_cards")
    price_url, price_updated = _bulk_item("default_cards")
    if oracle_path is None:
        oracle_path = CACHE / "oracle-cards.jsonl.gz"
        _download(oracle_url_value, oracle_path)
    if prices_path is None:
        prices_path = CACHE / "default-cards.jsonl.gz"
        _download(price_url, prices_path)
    print(f"reading oracle for {len(wanted)} names from {oracle_path}")
    oracle = load_oracle(oracle_path, wanted)
    print(f"matched {len(oracle)} oracle cards")
    print(f"reading nonfoil prices from {prices_path}")
    cheapest = load_min_usd(prices_path, wanted)
    for info in oracle.values():
        info["usd"] = cheapest.get(info["name"])
    print(f"priced {sum(1 for info in oracle.values() if info['usd'] is not None)} of {len(oracle)} names")
    built = [build_deck(deck, oracle, game_changers=game_changers) for deck in decks]
    built.sort(key=lambda deck: deck["id"])
    commanders = [deck for deck in built if deck["format"] == "commander"]
    summary = summarize(built)
    changer_rows = game_changer_report(commanders, oracle, sorted(game_changers))
    summary["game_changer_list_size"] = len(game_changers)
    summary["game_changers_found_in_precons"] = sum(1 for row in changer_rows if row["precon_count"])
    summary["precons_with_99_card_mainboard"] = sum(1 for deck in commanders if deck["mainboard_cards"] == 99)
    document = {
        "fetched_at": (price_updated or updated or "")[:10],
        "sources": {
            "decks": {
                "name": "MTGJSON official product decks",
                "snapshot": "api/app/data/official_decks.json",
                "license": "https://www.mtgjson.com/license/",
                "note": "Commander Deck and Pioneer Challenger Deck products. Collector editions are excluded as duplicate lists.",
            },
            "cards": {
                "name": "Scryfall oracle_cards bulk",
                "url": oracle_url_value,
                "terms": "https://scryfall.com/docs/api",
                "updated_at": updated,
            },
            "prices": {
                "name": "Scryfall default_cards bulk",
                "url": price_url,
                "terms": "https://scryfall.com/docs/api",
                "updated_at": price_updated,
                "price_field": "prices.usd",
                "price_note": (
                    "Lowest nonfoil USD among English printings in the default-cards bulk. "
                    "Not the sealed product's exact printing. Cards with no nonfoil USD are unpriced and excluded from totals."
                ),
            },
            "brackets": {
                "name": "Deck Lab Commander bracket inputs",
                "game_changers_as_of": data.get("as_of"),
                "module": "app.services.brackets",
            },
        },
        "summary": summary,
        "game_changers": changer_rows,
        "decks": {deck["id"]: deck for deck in built},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    summary = document["summary"]
    print(
        f"wrote {OUT} ({summary['official_decks']} decks, {summary['commander_precons']} precons, "
        f"{summary['pioneer_challenger']} pioneer)"
    )
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description="Build precon facts from MTGJSON and Scryfall bulk data.")
    parser.add_argument("--oracle", type=Path, default=None, help="Oracle-cards JSONL or JSONL.GZ to read instead of downloading")
    parser.add_argument("--prices", type=Path, default=None, help="Default-cards JSONL or JSONL.GZ to read instead of downloading")
    args = parser.parse_args()
    build(oracle_path=args.oracle, prices_path=args.prices)


if __name__ == "__main__":
    main()
