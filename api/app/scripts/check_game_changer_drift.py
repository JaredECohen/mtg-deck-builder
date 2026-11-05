"""Compare committed Game Changers with the Scryfall oracle bulk.

Weekly CI runs this. It only reads the bulk and the committed file. It does
not rewrite game_changers.json and it does not need an API key.

    python -m app.scripts.check_game_changer_drift
"""

from __future__ import annotations

import gzip
import json
import urllib.request
from pathlib import Path

USER_AGENT = "mtg-deck-lab/1.0"
BULK_INDEX = "https://api.scryfall.com/bulk-data"
TOKEN_LAYOUTS = {"token", "double_faced_token", "emblem", "art_series"}
ROOT = Path(__file__).resolve().parents[3]
GAME_CHANGERS = ROOT / "api" / "app" / "data" / "game_changers.json"


def is_token_row(card: dict) -> bool:
    if str(card.get("layout") or "") in TOKEN_LAYOUTS:
        return True
    return card.get("set_type") == "token"


def names_in_oracle(lines: list[str]) -> list[str]:
    names: set[str] = set()
    for line in lines:
        if not line.strip():
            continue
        card = json.loads(line)
        if not card.get("game_changer") or is_token_row(card):
            continue
        name = card.get("name")
        if name:
            names.add(str(name))
    return sorted(names)


def drift(committed: list[str], bulk: list[str]) -> tuple[list[str], list[str]]:
    return sorted(set(bulk) - set(committed)), sorted(set(committed) - set(bulk))


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def main() -> None:
    index = json.loads(_download(BULK_INDEX))
    oracle_url = next(item["jsonl_download_uri"] for item in index["data"] if item.get("type") == "oracle_cards")
    raw = gzip.decompress(_download(oracle_url)).decode("utf-8")
    bulk = names_in_oracle(raw.splitlines())
    committed = sorted(json.loads(GAME_CHANGERS.read_text(encoding="utf-8"))["game_changers"])
    missing, extra = drift(committed, bulk)
    print(f"committed {len(committed)} names, oracle bulk {len(bulk)} names")
    if not missing and not extra:
        print("game_changers.json matches the oracle game_changer field")
        return
    print(f"missing from the repo: {missing}")
    print(f"extra in the repo: {extra}")
    # 2 is a real list drift. A download or parse error stays on the default exit 1.
    raise SystemExit(2)


if __name__ == "__main__":
    main()
