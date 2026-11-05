"""Cache MTGJSON prices and Scryfall card data, then goldfish the guide decks.

Nothing here is a paid API. Scryfall is read from the oracle-cards bulk file
(one download, then a local filter). MTGJSON deck files are the official
product lists; AllPricesToday supplies the TCGplayer / ManaPool retail price
for the exact printing in each list. Both dumps are cached under /tmp/mtgdata
and the extracted facts are written into the repo as compact JSON.

Tokens that ship in a product box are not cards. They are dropped before
price totals, land and spell counts, and the goldfish. Regenerate, from
``api/``:

    python -m app.scripts.build_guide_facts
    python -m app.scripts.guide_articles
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import urllib.request
from pathlib import Path
from urllib.parse import quote

from app.oracle.ast_to_profile import build_card_profile
from app.scripts.precon_stats import is_bulk_token
from app.rules import count_color_sources
from app.scripts.ingest_official_decks import DECKLIST_URL, USER_AGENT, clean_card_name
from app.sim.goldfish import GoldfishConfig, goldfish
from app.sim.policy import POLICIES

ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = Path("/tmp/mtgdata")
ORACLE_GZ = CACHE_DIR / "oracle-cards.jsonl.gz"
PRICES_GZ = CACHE_DIR / "AllPricesToday.json.gz"
DECK_DIR = CACHE_DIR / "decks"
SNAPSHOT = ROOT / "api" / "app" / "data" / "official_decks.json"
CARD_CACHE = ROOT / "api" / "app" / "data" / "guide_card_cache.json"
EXAMPLE_OUT = ROOT / "web" / "src" / "data" / "example-decks.json"
EXAMPLE_LISTS_OUT = ROOT / "web" / "src" / "data" / "example-deck-lists.json"

# Scryfall layouts that are not sleeveable cards. A token in the main board
# (Dinosaur Egg in the Pantlaza precon) must not affect price, counts, or the sim.
TOKEN_LAYOUTS = {"token", "double_faced_token", "emblem", "art_series"}

ORACLE_URL = "https://data.scryfall.io/oracle-cards/oracle-cards-20261101100202.jsonl.gz"
PRICES_URL = "https://mtgjson.com/api/v5/AllPricesToday.json.gz"
DECK_URL = "https://mtgjson.com/api/v5/decks/{file_name}.json"
SCRYFALL_UPDATED = "2026-11-01T10:02:02.149+00:00"
FETCHED_ON = "2026-11-01"

# id, MTGJSON file, goldfish policy. Format comes from the deck file.
EXAMPLE_DECKS: list[tuple[str, str, str]] = [
    ("mono-red-burn", "MonoRedBurn_Q06", "aggro"),
    ("gruul-stompy", "GruulStompy_Q08", "aggro"),
    ("goblin-storm", "GoblinStorm_SLD", "aggro"),
    ("dimir-control", "DimirControl_Q08", "control"),
    ("seize-control", "SeizeControl_C15", "control"),
    ("azorius-spirits", "AzoriusSpirits_Q06", "aggro"),
    ("izzet-phoenix", "IzzetPhoenix_Q08", "aggro"),
    ("lotus-field", "LotusFieldCombo_Q06", "combo"),
    ("orzhov-auras", "OrzhovAuras_Q06", "aggro"),
    ("orzhov-humans", "OrzhovHumans_Q08", "aggro"),
    ("veloci-ramp-tor", "VelociRampTor_LCC", "midrange"),
    ("lands-wrath", "LandSWrath_ZNC", "midrange"),
    ("token-triumph", "TokenTriumph_SCD", "midrange"),
    ("rebellion-rising", "RebellionRising_ONC", "midrange"),
    ("blood-rites", "BloodRites_LCC", "midrange"),
    ("revenant-recon", "RevenantRecon_MKC", "midrange"),
    ("plunder-the-graves", "PlunderTheGraves_C15", "midrange"),
    ("mind-flayarrrs", "MindFlayarrrs_CLB", "midrange"),
    ("sneak-attack", "SneakAttack_ZNC", "aggro"),
    ("virtue-and-valor", "VirtueAndValor_WOC", "midrange"),
    ("aura-of-courage", "AuraOfCourage_AFC", "midrange"),
    ("prismari-performance", "PrismariPerformance_C21", "combo"),
    ("arcane-maelstrom", "ArcaneMaelstrom_C20", "combo"),
]

BASIC_NAMES = {
    "Plains",
    "Island",
    "Swamp",
    "Mountain",
    "Forest",
    "Wastes",
    "Snow-Covered Plains",
    "Snow-Covered Island",
    "Snow-Covered Swamp",
    "Snow-Covered Mountain",
    "Snow-Covered Forest",
}


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=180) as response, tmp.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
    tmp.replace(dest)


def _normal_price(blob: dict | None, vendor: str) -> tuple[float, str] | None:
    if not blob:
        return None
    try:
        retail = blob["paper"][vendor]["retail"].get("normal") or {}
    except (KeyError, TypeError):
        return None
    if not isinstance(retail, dict) or not retail:
        return None
    day = sorted(retail)[-1]
    return float(retail[day]), day


def _load_deck(file_name: str) -> dict:
    # Cache names stay ASCII. The request percent-encodes letters such as ü.
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name)
    dest = DECK_DIR / f"{safe}.json"
    _download(DECK_URL.format(file_name=quote(file_name, safe="")), dest)
    return json.loads(dest.read_text(encoding="utf-8"))["data"]


def is_token_type_line(type_line: str) -> bool:
    """True when any face's type line uses Token as a supertype."""
    for face in type_line.split("//"):
        words = face.replace("—", " ").replace("–", " ").split()
        if "Token" in words:
            return True
    return False


def is_token_entry(entry: dict, oracle: dict[str, dict]) -> bool:
    """A token card from an MTGJSON product list, not a spell that creates tokens."""
    layout = str(entry.get("layout") or "")
    if layout in TOKEN_LAYOUTS:
        return True
    types = entry.get("types")
    if isinstance(types, list) and "Token" in types:
        return True
    name = clean_card_name(str(entry.get("name") or ""))
    info = oracle.get(name) or {}
    if str(info.get("layout") or "") in TOKEN_LAYOUTS:
        return True
    return is_token_type_line(str(info.get("type_line") or ""))


def _entries(raw: list[dict] | None) -> list[dict]:
    totals: dict[str, dict] = {}
    for entry in raw or []:
        name = clean_card_name(str(entry.get("name") or ""))
        count = int(entry.get("count") or 0)
        if not name or count <= 0:
            continue
        current = totals.get(name)
        if current is None:
            totals[name] = {"name": name, "quantity": count, "uuid": entry.get("uuid")}
        else:
            current["quantity"] += count
    return list(totals.values())


def _stream_oracle(names: set[str]) -> dict[str, dict]:
    _download(ORACLE_URL, ORACLE_GZ)
    found: dict[str, dict] = {}
    with gzip.open(ORACLE_GZ, "rt", encoding="utf-8") as handle:
        for line in handle:
            card = json.loads(line)
            name = card.get("name")
            if name not in names or name in found or is_bulk_token(card):
                continue
            found[name] = {
                "name": name,
                "mana_cost": card.get("mana_cost") or "",
                "cmc": card.get("cmc") or 0,
                "type_line": card.get("type_line") or "",
                "oracle_text": card.get("oracle_text") or "",
                "keywords": card.get("keywords") or [],
                "color_identity": card.get("color_identity") or [],
                "produced_mana": card.get("produced_mana"),
                "power": card.get("power"),
                "toughness": card.get("toughness"),
                "legalities": card.get("legalities") or {},
                "layout": card.get("layout") or "",
                "scryfall_uri": card.get("scryfall_uri"),
            }
            if len(found) == len(names):
                break
    return found


def _price_printing(prices: dict, uuid: str | None) -> dict:
    blob = prices.get(uuid or "")
    tcg = _normal_price(blob, "tcgplayer")
    pool = _normal_price(blob, "manapool")
    if tcg:
        usd, day = tcg
        vendor = "tcgplayer"
    elif pool:
        usd, day = pool
        vendor = "manapool"
    else:
        return {"usd": None, "vendor": None, "date": None, "manapool_usd": pool[0] if pool else None}
    return {
        "usd": round(usd, 2),
        "vendor": vendor,
        "date": day,
        "manapool_usd": round(pool[0], 2) if pool else None,
        "uuid": uuid,
    }


def _curve(cards: list[dict], oracle: dict[str, dict]) -> list[dict]:
    buckets = [0] * 8
    for card in cards:
        info = oracle.get(card["name"])
        if info is None or "Land" in (info["type_line"].split("//", 1)[0]):
            continue
        mv = min(7, int(float(info["cmc"])))
        buckets[mv] += card["quantity"]
    return [{"mana_value": mv, "card_count": count} for mv, count in enumerate(buckets)]


def _primary_type(type_line: str) -> str:
    face = type_line.split("//", 1)[0].split("—", 1)[0]
    for label in ("Creature", "Planeswalker", "Instant", "Sorcery", "Artifact", "Enchantment", "Battle"):
        if label in face:
            return label
    return "Other"


def example_format(raw: dict) -> str:
    """Map an MTGJSON product type onto a format the builder can open."""
    deck_type = str(raw.get("type") or "").lower()
    if "commander" in deck_type:
        return "commander"
    if "pioneer" in deck_type:
        return "pioneer"
    # World Championship decks and any other constructed product open as Legacy
    # so a missing format cannot crash ?example= prefill.
    return "legacy"


def worlds_example_id(file_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", file_name.lower()).strip("-")
    return f"wc-{slug}"[:80]


def world_championship_specs(index: dict | list | None = None) -> list[tuple[str, str, str]]:
    """(example id, MTGJSON file name, goldfish policy) for World Championship decks."""
    if index is None:
        dest = CACHE_DIR / "DeckList.json.gz"
        _download(DECKLIST_URL, dest)
        with gzip.open(dest, "rt", encoding="utf-8") as handle:
            index = json.load(handle)
    rows = index.get("data") if isinstance(index, dict) else index
    specs: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict) or row.get("type") != "World Championship Deck":
            continue
        file_name = str(row.get("fileName") or "").strip()
        if not file_name:
            continue
        deck_id = worlds_example_id(file_name)
        if deck_id in seen:
            continue
        seen.add(deck_id)
        specs.append((deck_id, file_name, "midrange"))
    specs.sort()
    return specs


def _goldfish(mainboard: list[dict], oracle: dict[str, dict], *, policy: str, fmt: str) -> dict:
    deck: list[tuple] = []
    unresolved: list[str] = []
    for card in mainboard:
        info = oracle.get(card["name"])
        if info is None:
            unresolved.append(card["name"])
            continue
        try:
            profile = build_card_profile(
                {
                    "name": card["name"],
                    "mana_cost": info.get("mana_cost") or "",
                    "mana_value": info.get("cmc") or 0,
                    "type_line": info.get("type_line") or "",
                    "oracle_text": info.get("oracle_text") or "",
                    "keywords": info.get("keywords") or [],
                    "power": info.get("power"),
                    "toughness": info.get("toughness"),
                    "color_identity": info.get("color_identity") or [],
                }
            )
        except Exception:
            unresolved.append(card["name"])
            continue
        deck.extend([(profile, info.get("type_line") or "")] * card["quantity"])
    life = 40 if fmt == "commander" else 20
    turns = 16 if fmt == "commander" else 12
    games = 120
    if not deck:
        return {
            "games": games,
            "seed": 1729,
            "policy": policy,
            "starting_life": life,
            "max_turns": turns,
            "wins": 0,
            "win_rate": 0.0,
            "avg_kill_turn": None,
            "median_kill_turn": None,
            "unresolved_cards": unresolved,
            "cards_simulated": 0,
            "note": "No resolvable cards, so the goldfish was not run.",
        }
    report = goldfish(
        deck,
        policy=POLICIES[policy],
        config=GoldfishConfig(games=games, max_turns=turns, seed=1729, starting_life=life),
    )
    wins = report.wins
    return {
        "games": games,
        "seed": 1729,
        "policy": policy,
        "starting_life": life,
        "max_turns": turns,
        "wins": wins,
        "win_rate": round(wins / games, 4),
        "avg_kill_turn": None if wins == 0 else round(report.avg_kill_turn, 2),
        "median_kill_turn": None if wins == 0 else round(report.median_kill_turn, 2),
        "unresolved_cards": unresolved,
        "cards_simulated": len(deck),
        "note": (
            "Solitaire goldfish: no opponent interaction. "
            "Basic lands add the mana of their land type. "
            "The commander stays in the command zone and is not in the library."
            if fmt == "commander"
            else "Solitaire goldfish: no opponent interaction. Basic lands add the mana of their land type."
        ),
    }


def build(specs: list[tuple[str, str, str]] | None = None, *, merge: bool = False) -> dict:
    """Price and goldfish ``specs``.

    The default list is the guide catalog. Pass World Championship specs with
    ``merge=True`` to add them without replacing decks that are already priced.
    A deck file that fails to download is skipped. A card the oracle file does
    not know, or whose profile raises, is unresolved rather than fatal.
    """
    chosen = list(EXAMPLE_DECKS) if specs is None else specs
    prices_doc = None
    decks_raw = []
    names: set[str] = set()
    for deck_id, file_name, policy in chosen:
        try:
            raw = _load_deck(file_name)
        except Exception as exc:
            print(f"  skip {file_name}: {exc}")
            continue
        decks_raw.append((deck_id, file_name, policy, raw))
        for entry in (raw.get("mainBoard") or []) + (raw.get("sideBoard") or []) + (raw.get("commander") or []):
            name = clean_card_name(str(entry.get("name") or ""))
            if name:
                names.add(name)
    print(f"loaded {len(decks_raw)} decks, {len(names)} unique names")
    oracle = _stream_oracle(names)
    missing = sorted(names - set(oracle))
    if missing:
        print(f"scryfall miss {len(missing)}: {missing[:8]}")
    _download(PRICES_URL, PRICES_GZ)
    with gzip.open(PRICES_GZ, "rt", encoding="utf-8") as handle:
        prices_doc = json.load(handle)
    prices = prices_doc["data"]
    price_meta = prices_doc.get("meta") or {}

    examples: dict[str, dict] = {}
    cache_cards: dict[str, dict] = {}

    for deck_id, file_name, policy, raw in decks_raw:
        fmt = example_format(raw)

        def playable(entries: list[dict] | None) -> list[dict]:
            kept = []
            for entry in entries or []:
                if is_token_entry(entry, oracle):
                    name = clean_card_name(str(entry.get("name") or ""))
                    if name:
                        print(f"  skip token {deck_id}: {name}")
                    continue
                kept.append(entry)
            return _entries(kept)

        commanders = playable(raw.get("commander"))
        commander_names = {card["name"] for card in commanders}
        mainboard = [card for card in playable(raw.get("mainBoard")) if card["name"] not in commander_names]
        sideboard = playable(raw.get("sideBoard"))
        if not mainboard:
            print(f"  skip empty {deck_id}")
            continue
        identity: list[str] = []
        for commander in commanders:
            info = oracle.get(commander["name"]) or {}
            for color in info.get("color_identity") or []:
                if color not in identity:
                    identity.append(color)
        if not identity:
            for card in mainboard:
                info = oracle.get(card["name"]) or {}
                if "Land" in ((info.get("type_line") or "").split("//", 1)[0]):
                    continue
                for color in info.get("color_identity") or []:
                    if color not in identity:
                        identity.append(color)

        def priced(card: dict) -> dict:
            info = oracle.get(card["name"]) or {}
            quote = _price_printing(prices, card.get("uuid"))
            usd = quote["usd"]
            line = round(usd * card["quantity"], 2) if usd is not None else None
            record = {
                "name": card["name"],
                "quantity": card["quantity"],
                "uuid": card.get("uuid"),
                "usd": usd,
                "line_usd": line,
                "vendor": quote["vendor"],
                "price_date": quote["date"],
                "manapool_usd": quote["manapool_usd"],
                "type_line": info.get("type_line") or "",
                "cmc": info.get("cmc") or 0,
                "primary_type": _primary_type(info.get("type_line") or ""),
                "type": "Land" if "Land" in ((info.get("type_line") or "").split("//", 1)[0]) else "Spell",
                "color_identity": info.get("color_identity") or [],
                "legalities": {key: (info.get("legalities") or {}).get(key) for key in ("pioneer", "commander", "modern", "legacy", "standard")},
                "produced_mana": info.get("produced_mana"),
                "oracle_text": info.get("oracle_text") or "",
            }
            cache_cards[f"{card.get('uuid')}"] = {
                "name": card["name"],
                "set_printing_uuid": card.get("uuid"),
                "price_usd": usd,
                "price_vendor": quote["vendor"],
                "price_date": quote["date"],
                "manapool_normal_usd": quote["manapool_usd"],
                "type_line": record["type_line"],
                "cmc": record["cmc"],
                "legalities": record["legalities"],
                "produced_mana": record["produced_mana"],
            }
            return record

        rows = [priced(card) for card in mainboard + sideboard + commanders]
        cost_rows = [row for row in rows if row["line_usd"] is not None]
        total = round(sum(row["line_usd"] for row in cost_rows), 2)
        basic_cost = round(sum(row["line_usd"] for row in cost_rows if row["name"] in BASIC_NAMES), 2)
        # A pile of basics can outrank a single spell on line cost. The "top cards"
        # figure is the three most expensive nonbasic names.
        top = sorted(
            [row for row in cost_rows if row["name"] not in BASIC_NAMES],
            key=lambda row: row["line_usd"],
            reverse=True,
        )[:3]
        top_cost = round(sum(row["line_usd"] for row in top), 2)
        illegal = [
            row["name"]
            for row in rows
            if row["name"] not in BASIC_NAMES and row["legalities"].get(fmt) not in {None, "legal", "restricted"}
            and row["type"] != "Land"
        ]
        # Lands can be legal with a null-looking check; flag any explicit ban.
        illegal = sorted({row["name"] for row in rows if row["legalities"].get(fmt) in {"banned", "not_legal"}})
        source_cards = [
            {
                "name": card["name"],
                "quantity": card["quantity"],
                "type_line": (oracle.get(card["name"]) or {}).get("type_line") or "",
                "oracle_text": (oracle.get(card["name"]) or {}).get("oracle_text") or "",
                "produced_mana": (oracle.get(card["name"]) or {}).get("produced_mana"),
                "commander_colors": identity,
            }
            for card in mainboard + commanders
        ]
        sources = count_color_sources(source_cards)
        # produced_mana lists every color an "any color" land could add in some deck.
        # In this deck those lands only count for colors the deck is allowed to cast.
        if identity:
            sources = {color: (sources[color] if color in identity else 0) for color in "WUBRG"}
        curve = _curve(mainboard, oracle)
        nonland = sum(point["card_count"] for point in curve)
        lands = sum(card["quantity"] for card in mainboard if (oracle.get(card["name"]) or {}).get("type_line", "").split("//", 1)[0].find("Land") >= 0)
        fish = _goldfish(mainboard, oracle, policy=policy, fmt=fmt)
        examples[deck_id] = {
            "id": deck_id,
            "name": raw.get("name"),
            "format": fmt,
            "type": raw.get("type"),
            "commander": commanders[0]["name"] if commanders else "",
            "commanders": [card["name"] for card in commanders],
            "color_identity": identity,
            "release_date": raw.get("releaseDate"),
            "source_url": raw.get("source") if isinstance(raw.get("source"), str) else None,
            "mtgjson_file": file_name,
            "mtgjson_deck_url": DECK_URL.format(file_name=quote(file_name, safe="")),
            "mainboard": [{"name": card["name"], "quantity": card["quantity"]} for card in mainboard],
            "sideboard": [{"name": card["name"], "quantity": card["quantity"]} for card in sideboard],
            "analysis": {
                "total_cost_usd": total,
                "basic_land_cost_usd": basic_cost,
                "priced_cards": len(cost_rows),
                "unpriced": [row["name"] for row in rows if row["usd"] is None],
                "vendors": sorted({row["vendor"] for row in cost_rows if row["vendor"]}),
                "top_cards": [
                    {"name": row["name"], "quantity": row["quantity"], "usd": row["usd"], "line_usd": row["line_usd"]}
                    for row in top
                ],
                "top3_cost_usd": top_cost,
                "top3_share": round(top_cost / total, 4) if total else None,
                "land_count": lands,
                "nonland_count": nonland,
                "mana_curve": curve,
                "color_sources": sources,
                "illegal_in_format": illegal,
            "goldfish": fish,
        },
        }
        kill = fish["avg_kill_turn"]
        print(f"  {deck_id}: ${total} top3 {examples[deck_id]['analysis']['top3_share']} kill {kill} wins {fish['win_rate']}")

    document = {
        "fetched_at": FETCHED_ON,
        "sources": {
            "decks": {
                "name": "MTGJSON official product decks",
                "url": "https://mtgjson.com/api/v5/decks/{fileName}.json",
                "license": "https://www.mtgjson.com/license/",
                "fetched_at": FETCHED_ON,
            },
            "prices": {
                "name": "MTGJSON AllPricesToday",
                "url": PRICES_URL,
                "license": "https://www.mtgjson.com/license/",
                "version": price_meta.get("version"),
                "date": price_meta.get("date"),
                "field": "paper.tcgplayer.retail.normal, falling back to paper.manapool.retail.normal",
            },
            "cards": {
                "name": "Scryfall oracle_cards bulk",
                "url": ORACLE_URL,
                "terms": "https://scryfall.com/docs/api",
                "updated_at": SCRYFALL_UPDATED,
                "fields": ["legalities", "produced_mana", "oracle_text", "type_line", "mana_cost", "cmc"],
            },
            "simulator": {
                "name": "Deck Lab goldfish",
                "module": "app.sim.goldfish",
                "seed": 1729,
                "games": 120,
            },
        },
        "decks": examples,
    }
    if merge and EXAMPLE_OUT.exists():
        previous = json.loads(EXAMPLE_OUT.read_text(encoding="utf-8"))
        merged = dict(previous.get("decks") or {})
        merged.update(examples)
        # Keep the guide catalog's fetch date and source block. New decks are added.
        document = previous
        document["decks"] = merged
        examples = merged
        if CARD_CACHE.exists():
            previous_cards = json.loads(CARD_CACHE.read_text(encoding="utf-8")).get("cards") or {}
            previous_cards.update(cache_cards)
            cache_cards = previous_cards
    def list_row(deck_id: str, deck: dict) -> dict:
        row = {
            "id": deck["id"],
            "name": deck["name"],
            "format": deck["format"],
            "commander": deck["commander"],
            "mainboard": deck["mainboard"],
            "sideboard": deck["sideboard"],
        }
        if deck_id.startswith("wc-"):
            illegal = list((deck.get("analysis") or {}).get("illegal_in_format") or [])
            if illegal:
                shown = ", ".join(illegal[:6])
                extra = f" and {len(illegal) - 6} more" if len(illegal) > 6 else ""
                row["note"] = (
                    "Vintage/Old School example from a World Championship product, not a current Legacy deck. "
                    f"Not legal in Legacy: {shown}{extra}."
                )
            else:
                row["note"] = (
                    "Vintage/Old School example from a World Championship product, not a current Legacy deck."
                )
        return row

    lists = {deck_id: list_row(deck_id, deck) for deck_id, deck in examples.items()}
    _write_compact(EXAMPLE_OUT, document)
    lists_document = {"fetched_at": document["fetched_at"], "decks": lists}
    _write_compact(EXAMPLE_LISTS_OUT, lists_document)
    _write_compact(
        CARD_CACHE,
        {"fetched_at": document["fetched_at"], "sources": document["sources"], "cards": cache_cards},
    )
    print(f"wrote {EXAMPLE_OUT}, {EXAMPLE_LISTS_OUT}, and {CARD_CACHE}")
    return document


def _write_compact(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Price and goldfish official example decks.")
    parser.add_argument(
        "--worlds",
        action="store_true",
        help="Add MTGJSON World Championship decks to the example catalog without replacing the guide decks",
    )
    args = parser.parse_args()
    if args.worlds:
        build(world_championship_specs(), merge=True)
    else:
        build()
