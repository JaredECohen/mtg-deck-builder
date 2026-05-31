from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime

from sqlalchemy import select

from app.db import session_scope
from app.db_models import Archetype, IngestionRun, TournamentDeck
from app.services.card_repository import CardRepository
from app.services.database_bootstrap import create_schema


NON_THEME_TAGS = {"land", "mana", "creature", "commander"}
SIMILARITY_THRESHOLD = 0.58
EVENT_TIER_WEIGHTS = {
    "championship": 1.35,
    "showcase": 1.3,
    "challenge": 1.25,
    "rcq": 1.18,
    "league": 1.08,
    "local": 1.0,
}
ROLE_TAGS = {
    "interaction": "interaction",
    "removal": "interaction",
    "draw": "draw",
    "ramp": "ramp",
    "creature": "threat",
    "pressure": "threat",
    "prowess": "payoff",
    "tokens": "payoff",
    "lifegain": "payoff",
    "graveyard": "engine",
    "spells": "engine",
    "tribal": "engine",
}


def slugify(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")


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


def land_cards(repository: CardRepository, refs: list[dict[str, object]]) -> list[tuple[str, int]]:
    weighted: list[tuple[str, int]] = []
    for ref in refs:
        name = str(ref["name"])
        card = repository.get_card(name)
        if not card or "Land" not in card.type_line:
            continue
        weighted.append((name, int(ref["quantity"])))
    weighted.sort(key=lambda item: (-item[1], item[0]))
    return weighted


def build_signature(repository: CardRepository, deck: TournamentDeck) -> str:
    if deck.format == "commander" and deck.commander:
        return f"commander::{deck.commander.lower()}"
    color_part = "".join(sorted(deck.colors))
    top_names = [name for name, _ in nonland_cards(repository, deck.mainboard)[:8]]
    return f"{deck.format}::{color_part}::{'|'.join(top_names)}"


def deck_weight(deck: TournamentDeck) -> float:
    placement_score = 24.0
    if deck.placement is not None:
        placement_score = max(2.0, 40.0 - float(deck.placement))
    record_score = float((deck.wins or 0) * 3 - (deck.losses or 0) + (deck.draws or 0) * 0.5)
    recency_score = 1.0
    event_day = parse_event_date(deck.event_date)
    if event_day:
        days_old = max(0, (date.today() - event_day).days)
        recency_score = max(0.30, 1.0 - min(days_old, 540) / 900)
    tier_weight = EVENT_TIER_WEIGHTS.get((deck.event_tier or "local").lower(), 1.0)
    size_weight = 1.0 + min(0.25, (float(deck.event_size or 0) / 512.0))
    confidence_weight = 0.7 + (deck.confidence or 0.5)
    return (placement_score + max(0.0, record_score)) * recency_score * tier_weight * size_weight * confidence_weight


def deck_card_vector(repository: CardRepository, deck: TournamentDeck) -> dict[str, float]:
    return {name: float(quantity) for name, quantity in nonland_cards(repository, deck.mainboard)}


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
        return f"Built around {deck.commander}, this commander archetype converts commander identity into a consistent {focus} plan."
    focus = ", ".join(tags[:3]) or "pressure and interaction"
    return f"This tournament-derived shell consistently performs by leaning on {focus} and preserving a coherent curve."


def weighted_card_packages(
    repository: CardRepository,
    decks: list[TournamentDeck],
    board_name: str,
    threshold: float,
    *,
    lands_only: bool = False,
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
            card = repository.get_card(name)
            if not card:
                continue
            is_land = "Land" in card.type_line
            if lands_only != is_land:
                continue
            card_weights[name] += weight
            average_quantity[name] += weight * quantity
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


def weighted_profile(items: defaultdict[str, float], total_weight: float, *, avg_quantities: dict[str, float] | None = None, roles: dict[str, str] | None = None) -> list[dict[str, object]]:
    ordered = sorted(items.items(), key=lambda item: item[1], reverse=True)
    result: list[dict[str, object]] = []
    for name, weight in ordered:
        entry: dict[str, object] = {"name": name, "weight": round(weight / total_weight, 3)}
        if avg_quantities and name in avg_quantities:
            entry["average_quantity"] = round(avg_quantities[name] / weight, 2) if weight else 0.0
        if roles and name in roles:
            entry["role"] = roles[name]
        result.append(entry)
    return result


def mana_curve_profile(repository: CardRepository, decks: list[TournamentDeck]) -> list[dict[str, int | float]]:
    totals: defaultdict[int, float] = defaultdict(float)
    total_weight = sum(deck_weight(deck) for deck in decks) or 1.0
    for deck in decks:
        weight = deck_weight(deck)
        for ref in deck.mainboard:
            card = repository.get_card(str(ref["name"]))
            if not card or "Land" in card.type_line:
                continue
            bucket = min(6, int(card.mana_value))
            totals[bucket] += int(ref["quantity"]) * weight
    return [{"mana_value": bucket, "weight": round(totals[bucket] / total_weight, 2)} for bucket in sorted(totals)]


def role_profile(repository: CardRepository, decks: list[TournamentDeck]) -> list[dict[str, object]]:
    totals: defaultdict[str, float] = defaultdict(float)
    total_weight = sum(deck_weight(deck) for deck in decks) or 1.0
    for deck in decks:
        weight = deck_weight(deck)
        for ref in deck.mainboard:
            card = repository.get_card(str(ref["name"]))
            if not card or "Land" in card.type_line:
                continue
            role = primary_role(card)
            totals[role] += int(ref["quantity"]) * weight
    return [{"role": role, "weight": round(weight / total_weight, 2)} for role, weight in sorted(totals.items(), key=lambda item: item[1], reverse=True)]


def primary_role(card) -> str:
    for tag in card.tags:
        role = ROLE_TAGS.get(tag)
        if role:
            return role
    if "Creature" in card.type_line:
        return "threat"
    return "flex"


def normalized_card_vector(repository: CardRepository, decks: list[TournamentDeck]) -> list[dict[str, object]]:
    totals: defaultdict[str, float] = defaultdict(float)
    avg_quantities: defaultdict[str, float] = defaultdict(float)
    roles: dict[str, str] = {}
    total_weight = sum(deck_weight(deck) for deck in decks) or 1.0
    for deck in decks:
        weight = deck_weight(deck)
        for name, quantity in nonland_cards(repository, deck.mainboard):
            totals[name] += weight
            avg_quantities[name] += quantity * weight
            card = repository.get_card(name)
            if card:
                roles[name] = primary_role(card)
    return weighted_profile(totals, total_weight, avg_quantities=avg_quantities, roles=roles)[:24]


def tag_vector(repository: CardRepository, decks: list[TournamentDeck]) -> list[dict[str, object]]:
    totals: defaultdict[str, float] = defaultdict(float)
    total_weight = sum(deck_weight(deck) for deck in decks) or 1.0
    for deck in decks:
        weight = deck_weight(deck)
        for ref in deck.mainboard:
            card = repository.get_card(str(ref["name"]))
            if not card:
                continue
            for tag in card.tags:
                if tag not in NON_THEME_TAGS:
                    totals[tag] += weight
    return weighted_profile(totals, total_weight)[:12]


def commander_package_summary(repository: CardRepository, decks: list[TournamentDeck], commander_name: str) -> dict[str, object]:
    source_count = len(decks)
    lands = [sum(quantity for _, quantity in land_cards(repository, deck.mainboard)) for deck in decks]
    ramp = []
    draw = []
    interaction = []
    for deck in decks:
        ramp.append(count_role_cards(repository, deck, "ramp"))
        draw.append(count_role_cards(repository, deck, "draw"))
        interaction.append(count_role_cards(repository, deck, "interaction"))
    return {
        "commander_name": commander_name,
        "popularity": round(float(source_count), 2),
        "support_depth": source_count,
        "average_lands": round(sum(lands) / len(lands), 2) if lands else None,
        "average_ramp": round(sum(ramp) / len(ramp), 2) if ramp else None,
        "average_draw": round(sum(draw) / len(draw), 2) if draw else None,
        "average_interaction": round(sum(interaction) / len(interaction), 2) if interaction else None,
        "signature_cards": weighted_card_packages(repository, decks, "mainboard", threshold=0.55)[:12],
        "synergy_packages": weighted_card_packages(repository, decks, "mainboard", threshold=0.35)[:18],
        "ramp_package": role_package(repository, decks, "ramp"),
        "draw_package": role_package(repository, decks, "draw"),
        "interaction_package": role_package(repository, decks, "interaction"),
        "land_package": weighted_card_packages(repository, decks, "mainboard", threshold=0.25, lands_only=True)[:18],
    }


def role_package(repository: CardRepository, decks: list[TournamentDeck], role: str) -> list[dict[str, object]]:
    totals: defaultdict[str, float] = defaultdict(float)
    quantities: defaultdict[str, float] = defaultdict(float)
    total_weight = sum(deck_weight(deck) for deck in decks) or 1.0
    for deck in decks:
        weight = deck_weight(deck)
        for ref in deck.mainboard:
            name = str(ref["name"])
            card = repository.get_card(name)
            if not card or primary_role(card) != role:
                continue
            totals[name] += weight
            quantities[name] += int(ref["quantity"]) * weight
    packages = weighted_profile(totals, total_weight, avg_quantities=quantities)
    return [
        {
            "name": item["name"],
            "inclusion_rate": item["weight"],
            "average_quantity": item.get("average_quantity"),
            "tags": repository.get_card(item["name"]).tags if repository.get_card(item["name"]) else [],
        }
        for item in packages[:10]
    ]


def count_role_cards(repository: CardRepository, deck: TournamentDeck, role: str) -> int:
    total = 0
    for ref in deck.mainboard:
        card = repository.get_card(str(ref["name"]))
        if not card:
            continue
        if primary_role(card) == role:
            total += int(ref["quantity"])
    return total


def cluster_key(deck: TournamentDeck) -> tuple[str, str, tuple[str, ...], str]:
    archetype_type = "commander" if deck.commander else "constructed"
    commander_key = deck.commander or ""
    return (deck.format, archetype_type, tuple(sorted(deck.colors)), commander_key)


def cluster_decks(repository: CardRepository, decks: list[TournamentDeck]) -> list[list[TournamentDeck]]:
    grouped: defaultdict[tuple[str, str, tuple[str, ...], str], list[TournamentDeck]] = defaultdict(list)
    for deck in decks:
        grouped[cluster_key(deck)].append(deck)

    all_clusters: list[list[TournamentDeck]] = []
    for group_key, grouped_decks in grouped.items():
        _, archetype_type, _, commander_key = group_key
        if archetype_type == "commander" and commander_key:
            all_clusters.append(sorted(grouped_decks, key=deck_weight, reverse=True))
            continue

        clusters: list[list[TournamentDeck]] = []
        centroids: list[dict[str, float]] = []
        for deck in sorted(grouped_decks, key=deck_weight, reverse=True):
            vector = deck_card_vector(repository, deck)
            best_index = -1
            best_score = -1.0
            for index, centroid in enumerate(centroids):
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
        all_clusters.extend(clusters)
    return all_clusters


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
    # Prefer the canonical builtin display name when synthesize_tournament_corpus
    # embedded one in the deck's metadata. Falls back to the auto-generated
    # name from tags + colors when no builtin label is attached.
    canonical_labels: list[str] = []
    for deck in decks:
        try:
            label = (deck.metadata_json or {}).get("archetype_label")  # type: ignore[union-attr]
        except Exception:
            label = None
        if isinstance(label, str) and label.strip():
            canonical_labels.append(label.strip())
    if canonical_labels:
        # If multiple builtins clustered together, take the most common one.
        from collections import Counter as _Counter
        name = _Counter(canonical_labels).most_common(1)[0][0]
    else:
        name = infer_name(rep, tags, colors)
    archetype_id = slugify(f"{rep.format}-{name}")
    placements = [deck.placement for deck in decks if deck.placement is not None]
    core_cards = weighted_card_packages(repository, decks, "mainboard", threshold=0.72)
    flex_cards = weighted_card_packages(repository, decks, "mainboard", threshold=0.35)
    land_packages = weighted_card_packages(repository, decks, "mainboard", threshold=0.3, lands_only=True)
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
    archetype_type = "commander" if rep.commander else "constructed"
    metadata_json: dict[str, object] = {
        "signature_sample": build_signature(repository, rep),
        "source_event_names": sorted({deck.event_name for deck in decks}),
        "sample_deck_ids": [deck.id for deck in decks[:5]],
        "core_cards": core_cards[:18],
        "flex_cards": [card for card in flex_cards if card["name"] not in {core["name"] for core in core_cards}][:18],
        "land_packages": land_packages[:12],
        "sideboard_packages": sideboard_cards[:15],
        "matchup_tech_packages": sideboard_cards[:10],
        "top_weighted_decks": signature_scores,
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "archetype_type": archetype_type,
        "color_profile": colors,
        "tag_vector": tag_vector(repository, decks),
        "signature_cards": normalized_card_vector(repository, [rep])[:12],
        "normalized_card_vector": normalized_card_vector(repository, decks),
        "mana_curve_profile": mana_curve_profile(repository, decks),
        "role_profile": role_profile(repository, decks),
    }
    if rep.commander:
        metadata_json["commander_package"] = commander_package_summary(repository, decks, rep.commander)
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
        "metadata_json": metadata_json,
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

        seen_ids: set[str] = set()
        for grouped_decks in grouped_clusters:
            payload = build_archetype_payload(repository, grouped_decks)
            # Skip clusters whose slugified ID would collide with an
            # earlier cluster from the same run — the slugifier collapses
            # variant names ("Modern Mono-Red Burn" + "Modern Mono-R Burn"
            # share the same slug). Take whichever came first.
            archetype_id = str(payload.get("id") or "")
            if archetype_id in seen_ids:
                continue
            seen_ids.add(archetype_id)
            session.merge(Archetype(**payload))
            session.flush()
            processed += 1

        run.status = "completed"
        run.records_processed = processed
        run.notes = json.dumps({"group_count": len(grouped_clusters), "similarity_threshold": SIMILARITY_THRESHOLD})

    print(json.dumps({"status": "ok", "archetypes_built": processed, "groups": len(grouped_clusters)}))


if __name__ == "__main__":
    main()
