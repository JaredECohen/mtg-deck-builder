from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db import session_scope
from app.db_models import Archetype, IngestionRun, TournamentDeck
from app.services.card_repository import CardRepository
from app.services.database_bootstrap import create_schema


NON_THEME_TAGS = {"land", "mana", "creature", "commander"}
SIMILARITY_THRESHOLD = 0.58


def slugify(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")


def ref_total(refs: list[dict[str, object]]) -> int:
    return sum(int(ref["quantity"]) for ref in refs)


def parse_event_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def nonland_cards(repository: CardRepository, refs: list[dict[str, object]]) -> list[tuple[str, int]]:
    weighted: list[tuple[str, int]] = []
    for ref in refs:
        name = str(ref["name"])
        card = repository.get_card(name)
        if not card or "Land" in card.type_line:
            continue
        weighted.append((name.lower(), int(ref["quantity"])))
    weighted.sort(key=lambda item: (-item[1], item[0]))
    return weighted


def build_signature(repository: CardRepository, deck: TournamentDeck) -> str:
    if deck.format == "commander" and deck.commander:
        return f"commander::{deck.commander.lower()}"
    top_names = [name for name, _ in nonland_cards(repository, deck.mainboard)[:8]]
    return f"{deck.format}::{'|'.join(top_names)}"


def deck_weight(deck: TournamentDeck) -> float:
    placement_score = 32.0
    if deck.placement is not None:
        placement_score = max(1.0, 32.0 - float(deck.placement))
    record_score = float((deck.wins or 0) * 3 - (deck.losses or 0) + (deck.draws or 0) * 0.5)
    recency_score = 1.0
    event_day = parse_event_date(deck.event_date)
    if event_day:
        days_old = max(0, (date.today() - event_day).days)
        recency_score = max(0.35, 1.0 - min(days_old, 365) / 730)
    return (placement_score + max(0.0, record_score)) * recency_score


def deck_card_vector(repository: CardRepository, deck: TournamentDeck) -> dict[str, float]:
    vector: dict[str, float] = {}
    for name, quantity in nonland_cards(repository, deck.mainboard):
        vector[name] = float(quantity)
    return vector


def similarity_score(left: dict[str, float], right: dict[str, float]) -> float:
    left_names = set(left)
    right_names = set(right)
    if not left_names and not right_names:
        return 1.0
    intersection = left_names & right_names
    union = left_names | right_names
    jaccard = len(intersection) / len(union) if union else 0.0
    quantity_distance = sum(abs(left.get(name, 0.0) - right.get(name, 0.0)) for name in union)
    quantity_penalty = min(0.35, quantity_distance / max(1.0, sum(left.values()) + sum(right.values())))
    return max(0.0, jaccard - quantity_penalty)


def aggregate_tags(decks: list[TournamentDeck]) -> list[str]:
    tags: defaultdict[str, float] = defaultdict(float)
    for deck in decks:
        weight = deck_weight(deck)
        for tag in deck.tags:
            if tag not in NON_THEME_TAGS:
                tags[tag] += weight
    return [tag for tag, _ in sorted(tags.items(), key=lambda item: item[1], reverse=True)[:6]]


def aggregate_colors(decks: list[TournamentDeck]) -> list[str]:
    color_weights: defaultdict[str, float] = defaultdict(float)
    for deck in decks:
        weight = deck_weight(deck)
        for color in deck.colors:
            color_weights[color] += weight
    return [color for color, _ in sorted(color_weights.items(), key=lambda item: item[1], reverse=True)]


def representative_deck(decks: list[TournamentDeck]) -> TournamentDeck:
    return max(decks, key=deck_weight)


def infer_name(deck: TournamentDeck, tags: list[str], colors: list[str]) -> str:
    if deck.commander:
        return f"{deck.commander} {(' '.join(tag.title() for tag in tags[:2])) or 'Commander'}".strip()
    color_name = "".join(colors) if colors else "Colorless"
    theme = " ".join(tag.title() for tag in tags[:2]) or "Midrange"
    return f"{color_name} {theme}".strip()


def infer_strategy(deck: TournamentDeck, tags: list[str]) -> str:
    if deck.commander:
        focus = ", ".join(tags[:3]) or "synergy"
        return f"Built around {deck.commander}, this archetype converts commander identity into a consistent {focus} plan."
    focus = ", ".join(tags[:3]) or "pressure and interaction"
    return f"This tournament-derived shell consistently performs by leaning on {focus} and preserving a coherent curve."


def weighted_card_packages(
    repository: CardRepository,
    decks: list[TournamentDeck],
    board_name: str,
    threshold: float,
) -> list[dict[str, object]]:
    total_weight = sum(deck_weight(deck) for deck in decks) or 1.0
    card_weights: defaultdict[str, float] = defaultdict(float)
    average_quantity: defaultdict[str, float] = defaultdict(float)
    tags_by_card: dict[str, list[str]] = {}

    for deck in decks:
        weight = deck_weight(deck)
        refs = deck.mainboard if board_name == "mainboard" else deck.sideboard
        for ref in refs:
            name = str(ref["name"])
            quantity = int(ref["quantity"])
            card_weights[name] += weight
            average_quantity[name] += weight * quantity
            card = repository.get_card(name)
            if card:
                tags_by_card[name] = card.tags

    packages: list[dict[str, object]] = []
    for name, weight in sorted(card_weights.items(), key=lambda item: item[1], reverse=True):
        inclusion_rate = weight / total_weight
        if inclusion_rate < threshold:
            continue
        packages.append(
            {
                "name": name,
                "inclusion_rate": round(inclusion_rate, 3),
                "average_quantity": round(average_quantity[name] / weight, 2),
                "tags": tags_by_card.get(name, []),
            }
        )
    return packages


def cluster_decks(repository: CardRepository, decks: list[TournamentDeck]) -> list[list[TournamentDeck]]:
    clusters: list[list[TournamentDeck]] = []
    centroids: list[dict[str, float]] = []

    for deck in sorted(decks, key=deck_weight, reverse=True):
        vector = deck_card_vector(repository, deck)
        if deck.format == "commander" and deck.commander:
            matching_index = next(
                (
                    index
                    for index, cluster in enumerate(clusters)
                    if cluster[0].commander == deck.commander and cluster[0].format == deck.format
                ),
                None,
            )
            if matching_index is not None:
                clusters[matching_index].append(deck)
                continue

        best_index = -1
        best_score = -1.0
        for index, centroid in enumerate(centroids):
            if clusters[index][0].format != deck.format:
                continue
            score = similarity_score(vector, centroid)
            if score > best_score:
                best_score = score
                best_index = index

        if best_index >= 0 and best_score >= SIMILARITY_THRESHOLD:
            clusters[best_index].append(deck)
            centroids[best_index] = average_vector(repository, clusters[best_index])
        else:
            clusters.append([deck])
            centroids.append(vector)

    return clusters


def average_vector(repository: CardRepository, decks: list[TournamentDeck]) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    total_weight = 0.0
    for deck in decks:
        weight = deck_weight(deck)
        total_weight += weight
        for name, quantity in nonland_cards(repository, deck.mainboard):
            totals[name] += quantity * weight
    if total_weight == 0:
        return {}
    return {name: quantity / total_weight for name, quantity in totals.items()}


def build_archetype_payload(repository: CardRepository, decks: list[TournamentDeck]) -> dict[str, object]:
    rep = representative_deck(decks)
    tags = aggregate_tags(decks)
    colors = aggregate_colors(decks)
    name = infer_name(rep, tags, colors)
    archetype_id = slugify(f"{rep.format}-{name}")
    placements = [deck.placement for deck in decks if deck.placement is not None]
    core_cards = weighted_card_packages(repository, decks, "mainboard", threshold=0.72)
    flex_cards = weighted_card_packages(repository, decks, "mainboard", threshold=0.35)
    sideboard_cards = weighted_card_packages(repository, decks, "sideboard", threshold=0.25)
    signature_scores = sorted(
        (
            {
                "deck_id": deck.id,
                "weight": round(deck_weight(deck), 2),
                "signature": build_signature(repository, deck),
            }
            for deck in decks
        ),
        key=lambda item: item["weight"],
        reverse=True,
    )[:5]
    return {
        "id": archetype_id,
        "name": name,
        "format": rep.format,
        "colors": colors,
        "tags": tags,
        "strategy": infer_strategy(rep, tags),
        "commander": rep.commander,
        "mainboard": rep.mainboard,
        "sideboard": rep.sideboard,
        "source_count": len(decks),
        "avg_placement": sum(placements) / len(placements) if placements else None,
        "metadata": {
            "signature_sample": build_signature(repository, rep),
            "source_event_names": sorted({deck.event_name for deck in decks}),
            "sample_deck_ids": [deck.id for deck in decks[:5]],
            "core_cards": core_cards[:18],
            "flex_cards": [card for card in flex_cards if card["name"] not in {core["name"] for core in core_cards}][:18],
            "sideboard_packages": sideboard_cards[:15],
            "top_weighted_decks": signature_scores,
            "similarity_threshold": SIMILARITY_THRESHOLD,
        },
    }


def main() -> None:
    create_schema()
    repository = CardRepository()

    with session_scope() as session:
        decks = session.scalars(select(TournamentDeck).order_by(TournamentDeck.format, TournamentDeck.placement)).all()

    grouped_clusters = cluster_decks(repository, decks)

    processed = 0
    with session_scope() as session:
        run = IngestionRun(source="archetype_builder", status="running", records_processed=0)
        session.add(run)
        session.flush()

        for grouped_decks in grouped_clusters:
            payload = build_archetype_payload(repository, grouped_decks)
            stmt = insert(Archetype).values(**payload)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Archetype.id],
                set_={
                    "name": stmt.excluded.name,
                    "format": stmt.excluded.format,
                    "colors": stmt.excluded.colors,
                    "tags": stmt.excluded.tags,
                    "strategy": stmt.excluded.strategy,
                    "commander": stmt.excluded.commander,
                    "mainboard": stmt.excluded.mainboard,
                    "sideboard": stmt.excluded.sideboard,
                    "source_count": stmt.excluded.source_count,
                    "avg_placement": stmt.excluded.avg_placement,
                    "metadata_json": stmt.excluded.metadata_json,
                },
            )
            session.execute(stmt)
            processed += 1

        run.status = "completed"
        run.records_processed = processed
        run.notes = json.dumps({"group_count": len(grouped_clusters), "similarity_threshold": SIMILARITY_THRESHOLD})

    print(json.dumps({"status": "ok", "archetypes_built": processed, "groups": len(grouped_clusters)}))


if __name__ == "__main__":
    main()
