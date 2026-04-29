from __future__ import annotations

from collections import Counter
from hashlib import sha1
from pathlib import Path

from app.models import CardRef, NormalizedTournamentDeckRecord, TournamentDeckIngestMetadata
from app.services.card_repository import CardRepository


def merge_refs(refs: list[dict[str, object]]) -> list[CardRef]:
    counts = Counter[str]()
    for ref in refs:
        counts[str(ref["name"])] += int(ref["quantity"])
    return [CardRef(name=name, quantity=quantity) for name, quantity in counts.items()]


def infer_colors_and_tags(
    repository: CardRepository,
    refs: list[CardRef],
    commander: str | None,
) -> tuple[list[str], list[str]]:
    colors: set[str] = set()
    tags: Counter[str] = Counter()
    names = [ref.name for ref in refs]
    if commander:
        names.append(commander)
    for card in repository.get_cards(names):
        colors.update(card.color_identity or card.colors)
        for tag in card.tags:
            if tag != "land":
                tags[tag] += 1
    top_tags = [tag for tag, _ in tags.most_common(6)]
    return sorted(colors), top_tags


def normalize_raw_deck(
    repository: CardRepository,
    raw_deck: dict[str, object],
    *,
    source_name: str,
    ingested_from: Path,
) -> NormalizedTournamentDeckRecord:
    mainboard = merge_refs(list(raw_deck.get("mainboard", [])))
    sideboard = merge_refs(list(raw_deck.get("sideboard", [])))
    commander = raw_deck.get("commander")
    commander_name = commander if isinstance(commander, str) else None
    colors, tags = infer_colors_and_tags(repository, mainboard, commander_name)

    metadata = TournamentDeckIngestMetadata(
        raw_source=str(raw_deck.get("source", source_name)),
        ingested_from=str(ingested_from),
        source_url=_optional_str(raw_deck.get("source_url")),
        format_season=_optional_str(raw_deck.get("format_season")),
        event_tier=_optional_str(raw_deck.get("event_tier")),
        event_size=_optional_int(raw_deck.get("event_size")),
        finish_label=_optional_str(raw_deck.get("finish_label")),
        confidence=_optional_float(raw_deck.get("confidence")),
    )
    dedupe_key = build_dedupe_key(
        raw_deck,
        source_name=source_name,
        event_name=str(raw_deck["event_name"]),
        format_name=str(raw_deck["format"]),
        commander_name=commander_name,
        mainboard=mainboard,
        sideboard=sideboard,
    )

    return NormalizedTournamentDeckRecord(
        id=str(raw_deck["id"]),
        source=str(raw_deck.get("source", source_name)),
        dedupe_key=dedupe_key,
        source_url=metadata.source_url,
        event_name=str(raw_deck["event_name"]),
        event_date=_optional_str(raw_deck.get("event_date")),
        format=str(raw_deck["format"]),
        format_season=metadata.format_season,
        event_tier=metadata.event_tier,
        event_size=metadata.event_size,
        finish_label=metadata.finish_label,
        confidence=metadata.confidence,
        player_name=_optional_str(raw_deck.get("player_name")),
        placement=_optional_int(raw_deck.get("placement")),
        wins=_optional_int(raw_deck.get("wins")),
        losses=_optional_int(raw_deck.get("losses")),
        draws=_optional_int(raw_deck.get("draws")),
        colors=colors,
        tags=tags,
        commander=commander_name,
        mainboard=mainboard,
        sideboard=sideboard,
        metadata=metadata,
    )


def normalized_record_payload(record: NormalizedTournamentDeckRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "source": record.source,
        "dedupe_key": record.dedupe_key,
        "source_url": record.source_url,
        "event_name": record.event_name,
        "event_date": record.event_date,
        "format": record.format,
        "format_season": record.format_season,
        "event_tier": record.event_tier,
        "event_size": record.event_size,
        "finish_label": record.finish_label,
        "confidence": record.confidence,
        "player_name": record.player_name,
        "placement": record.placement,
        "wins": record.wins,
        "losses": record.losses,
        "draws": record.draws,
        "colors": record.colors,
        "tags": record.tags,
        "commander": record.commander,
        "mainboard": [ref.model_dump() for ref in record.mainboard],
        "sideboard": [ref.model_dump() for ref in record.sideboard],
        "metadata_json": record.metadata.model_dump(),
    }


def build_dedupe_key(
    raw_deck: dict[str, object],
    *,
    source_name: str,
    event_name: str,
    format_name: str,
    commander_name: str | None,
    mainboard: list[CardRef],
    sideboard: list[CardRef],
) -> str:
    source_url = _optional_str(raw_deck.get("source_url"))
    if source_url:
        return f"url::{source_url}"

    fingerprint = {
        "source": str(raw_deck.get("source", source_name)),
        "event_name": event_name,
        "event_date": _optional_str(raw_deck.get("event_date")),
        "format": format_name,
        "player_name": _optional_str(raw_deck.get("player_name")),
        "commander": commander_name,
        "mainboard": sorted((ref.name, ref.quantity) for ref in mainboard),
        "sideboard": sorted((ref.name, ref.quantity) for ref in sideboard),
    }
    return f"deck::{sha1(repr(fingerprint).encode('utf-8')).hexdigest()}"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
