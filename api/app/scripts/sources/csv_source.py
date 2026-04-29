from __future__ import annotations

import csv
from pathlib import Path


def load_csv_decks(path: Path) -> list[dict[str, object]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        return [_normalize_row(row) for row in reader]


def _normalize_row(row: dict[str, str | None]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in row.items():
        if key is None:
            continue
        text = (value or "").strip()
        if key in {"mainboard", "sideboard"}:
            normalized[key] = _parse_board(text)
        elif key in {"event_size", "placement", "wins", "losses", "draws"}:
            normalized[key] = int(text) if text else None
        elif key == "confidence":
            normalized[key] = float(text) if text else None
        else:
            normalized[key] = text or None
    normalized["mainboard"] = normalized.get("mainboard") or []
    normalized["sideboard"] = normalized.get("sideboard") or []
    return normalized


def _parse_board(value: str) -> list[dict[str, object]]:
    if not value:
        return []
    refs: list[dict[str, object]] = []
    for entry in value.split("|"):
        item = entry.strip()
        if not item:
            continue
        quantity_text, name = item.split(" ", 1)
        refs.append({"name": name.strip(), "quantity": int(quantity_text)})
    return refs
