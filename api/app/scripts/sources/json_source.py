from __future__ import annotations

import json
from pathlib import Path


def load_json_decks(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    if isinstance(payload, dict) and isinstance(payload.get("decks"), list):
        return [dict(item) for item in payload["decks"]]
    raise ValueError(f"Unsupported JSON deck source shape in {path}")
