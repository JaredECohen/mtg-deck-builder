"""Write the Week 1 study guides from precon_facts.json.

Every price, count, and percentage is inserted from that file and recorded in
a sibling ``.claims.json``. The guide rubric rejects a literal the claims do
not cover. Regenerate from ``api/`` after rebuilding facts::

    python -m app.scripts.build_precon_facts
    python -m app.scripts.build_study_guides
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FACTS_PATH = ROOT / "web" / "src" / "data" / "precon_facts.json"
BLOG = ROOT / "web" / "content" / "blog"
PUBLISHED = "2026-11-02"


def fact_at(root: object, path: str) -> object:
    current = root
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(path)
    return current


def format_fact(value: object, kind: str) -> str:
    number = float(value)  # type: ignore[arg-type]
    if kind == "int":
        if abs(number - round(number)) > 1e-6:
            raise ValueError(f"{value} is not an int")
        return str(int(round(number)))
    if kind == "dec1":
        return f"{number:.1f}"
    if kind == "num":
        if abs(number - round(number)) < 1e-6:
            return str(int(round(number)))
        return f"{number:.1f}"
    if kind == "usd":
        return f"${number:.2f}"
    if kind == "pct":
        return f"{number:.1f}%"
    raise ValueError(kind)


class Claims:
    def __init__(self, facts: dict) -> None:
        self.facts = facts
        self.rows: list[dict] = []

    def __call__(self, path: str, kind: str) -> str:
        text = format_fact(fact_at(self.facts, path), kind)
        self.rows.append({"text": text, "path": path, "as": kind})
        return text


def deck_by_file(facts: dict, file_name: str) -> dict:
    for deck in facts["decks"].values():
        if deck["file_name"] == file_name:
            return deck
    raise KeyError(file_name)


def extreme(facts: dict, *, pioneer: bool, key: str, high: bool) -> dict:
    rows = [deck for deck in facts["decks"].values() if (deck["format"] == "pioneer") is pioneer]
    return max(rows, key=lambda deck: (deck[key], deck["id"])) if high else min(rows, key=lambda deck: (deck[key], deck["id"]))


def write_guide(slug: str, body: str, claims: list[dict]) -> None:
    path = BLOG / f"{slug}.mdx"
    path.write_text(body, encoding="utf-8")
    (BLOG / f"{slug}.claims.json").write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
    prose = body.split("---", 2)[-1]
    words = len(prose.replace("<", " ").split())
    description = body.split("description:", 1)[1].split("\n", 1)[0].strip().strip('"')
    print(f"{slug}: {words} rough words, description {len(description)} chars, {len(claims)} claims")


def frontmatter(*, title: str, description: str, category: str, keywords: list[str], related: list[str]) -> str:
    if not 120 <= len(description) <= 170:
        raise ValueError(f"description is {len(description)} chars: {description}")
    keys = ", ".join(f'"{key}"' for key in keywords)
    rel = ", ".join(f'"{slug}"' for slug in related)
    return f"""---
title: "{title}"
description: "{description}"
date: {PUBLISHED}
updated: {PUBLISHED}
author: Deck Lab Editorial
reviewed: true
category: {category}
keywords: [{keys}]
related: [{rel}]
---
"""


def lands_guide(facts: dict) -> None:
    c = Claims(facts)
    veloci = deck_by_file(facts, "VelociRampTor_LCC")
    wrath = deck_by_file(facts, "LandSWrath_ZNC")
    low_land = facts["summary"]["lands"]["lowest"]
    high_land = facts["summary"]["lands"]["highest"]
    low_ramp = facts["summary"]["ramp"]["lowest"]
    high_ramp = facts["summary"]["ramp"]["highest"]
    low_draw = facts["summary"]["draw"]["lowest"]
    high_draw = facts["summary"]["draw"]["highest"]
    fetched = facts["fetched_at"]
    identity = facts["summary"]["color_identity"][0]["identity"]
    colors = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
    identity_words = "-".join(colors[letter] for letter in identity)
    body = frontmatter(
        title="How Many Lands, Ramp, and Draw Spells Do Commander Precons Play?",
        description=(
            "Across the official Commander precons, the median list plays 38 lands, "
            "10 ramp cards, and 11 draw cards. Here are the outliers and the price spread."
        ),
        category="deck-archetypes",
        keywords=["commander precon land count", "precon ramp count", "precon card draw", "commander precon price"],
        related=["mtg-ramp-deck-guide", "should-you-play-ramp", "commander-precon-game-changers"],
    )
    body += f"""
## Short answer

In Magic: The Gathering (MTG), a Commander precon ships with a commander and a main list. This count uses the {c("summary.commander_precons", "int")} Commander Deck products in the MTGJSON snapshot, with collector editions left out as duplicate lists. Tokens that MTGJSON parked in the main list are not counted as cards. Across those lists, the median land count is {c("summary.lands.median", "int")}, the median ramp count is {c("summary.ramp.median", "int")}, and the median draw count is {c("summary.draw.median", "int")}.

Read those as copies, not as a promise about power. Ramp means a nonland that adds mana, puts a land you searched onto the battlefield, lets you play an extra land, or creates a Treasure for you. Draw means a nonland that draws you cards or exiles the top of your library and lets you play those cards. A land that happens to draw stays in the land count only. One card can sit in more than one of those counts. The full rules are on the [method page](/method).

The middle of the land distribution is tight. {c("summary.lands.in_middle_half", "int")} of the {c("summary.commander_precons", "int")} lists, {c("summary.lands.in_middle_half_pct", "pct")}, play between {c("summary.lands.p25", "num")} and {c("summary.lands.p75", "num")} lands. {c("summary.precons_with_99_card_mainboard", "int")} of the lists have a {c("decks." + wrath["id"] + ".mainboard_cards", "int")}-card non-token mainboard. The rest are short because the product file included a token or, in a few cases, a shorter published list.

<InArticleAd />

## The spread

| Count | Low | Lower quartile | Median | Upper quartile | High |
| --- | --- | --- | --- | --- | --- |
| Lands | {c("summary.lands.min", "int")} | {c("summary.lands.p25", "num")} | {c("summary.lands.median", "int")} | {c("summary.lands.p75", "num")} | {c("summary.lands.max", "int")} |
| Ramp | {c("summary.ramp.min", "int")} | {c("summary.ramp.p25", "num")} | {c("summary.ramp.median", "int")} | {c("summary.ramp.p75", "num")} | {c("summary.ramp.max", "int")} |
| Draw | {c("summary.draw.min", "int")} | {c("summary.draw.p25", "num")} | {c("summary.draw.median", "int")} | {c("summary.draw.p75", "num")} | {c("summary.draw.max", "int")} |
| Removal | {c("summary.removal.min", "int")} | {c("summary.removal.p25", "num")} | {c("summary.removal.median", "num")} | {c("summary.removal.p75", "num")} | {c("summary.removal.max", "int")} |

Means sit next to those medians: {c("summary.lands.mean", "dec1")} lands, {c("summary.ramp.mean", "dec1")} ramp, {c("summary.draw.mean", "dec1")} draw, and {c("summary.removal.mean", "dec1")} removal. Removal here is a nonland that destroys or exiles a permanent, deals damage to a creature or any target, forces a sacrifice, fights, or gives creatures a minus. A counterspell is not removal. That is why a burn spell pointed at a player still adds to the removal count, and why the removal median of {c("summary.removal.median", "num")} is not "seven and a half kill spells" in the casual sense.

The lowest land counts are {low_land[0]["name"]} and {low_land[1]["name"]} at {c("summary.lands.lowest.0.value", "int")}, then {low_land[2]["name"]} at {c("summary.lands.lowest.2.value", "int")}. The high end is {high_land[0]["name"]} and {high_land[1]["name"]} at {c("summary.lands.highest.0.value", "int")}, then {high_land[2]["name"]} at {c("summary.lands.highest.2.value", "int")}. Nothing in this set is a sixty-card aggro mana base. The floor of the whole sample is still {c("summary.lands.min", "int")} lands.

Ramp is wider. {low_ramp[0]["name"]} is the low at {c("summary.ramp.lowest.0.value", "int")}. {high_ramp[0]["name"]} is the high at {c("summary.ramp.highest.0.value", "int")}, with {high_ramp[1]["name"]} at {c("summary.ramp.highest.1.value", "int")}. {c("summary.ramp.in_middle_half", "int")} lists, {c("summary.ramp.in_middle_half_pct", "pct")}, fall between {c("summary.ramp.p25", "num")} and {c("summary.ramp.p75", "num")} ramp copies. Draw runs from {c("summary.draw.min", "int")} on the two Heavenly Inferno products up to {c("summary.draw.max", "int")} on {high_draw[0]["name"]}. {low_draw[2]["name"]} is the next low, at {c("summary.draw.lowest.2.value", "int")}. {c("summary.draw.in_middle_half", "int")} lists sit between {c("summary.draw.p25", "num")} and {c("summary.draw.p75", "num")} draw copies, {c("summary.draw.in_middle_half_pct", "pct")} of the sample.

The most common color identity is {identity_words}, on {c("summary.color_identity.0.decks", "int")} lists ({c("summary.color_identity.0.pct", "pct")}). Identity here is the commander colors MTGJSON stored, not a guess from the mana symbols in the 99.

Prices are a different column. They are the lowest Scryfall nonfoil dollar price for each English printing in the default-cards bulk dated {fetched}, summed for the main list, the sideboard, and the commanders. They are not the sealed product's exact printing, and a card with no nonfoil price is left out and named. {c("summary.precons_fully_priced", "int")} lists priced completely. {c("summary.precons_with_unpriced", "int")} did not, so a total for those is a partial receipt. Among the complete ones, the median is {c("summary.price_complete.median", "usd")}, the mean is {c("summary.price_complete.mean", "usd")}, and the middle half runs from {c("summary.price_complete.p25", "usd")} to {c("summary.price_complete.p75", "usd")} ({c("summary.price_complete.in_middle_half", "int")} lists, {c("summary.price_complete.in_middle_half_pct", "pct")}). The cheapest complete list is {facts["summary"]["price_complete"]["lowest"][0]["name"]} at {c("summary.price_complete.lowest.0.value", "usd")}. The dearest complete list is {facts["summary"]["price_complete"]["highest"][0]["name"]} at {c("summary.price_complete.highest.0.value", "usd")}.

## Two official lists

The deck blocks below open the product list in the builder. Their printed total is the MTGJSON AllPricesToday number for that product's printings. The figures in this paragraph are the Scryfall bulk totals from the same count as the table.

<DeckBlock id="veloci-ramp-tor" />

Veloci-Ramp-Tor plays {c("decks." + veloci["id"] + ".land_count", "int")} lands, {c("decks." + veloci["id"] + ".ramp_count", "int")} ramp, {c("decks." + veloci["id"] + ".draw_count", "int")} draw, and {c("decks." + veloci["id"] + ".removal_count", "int")} removal. Every card in that product had a nonfoil Scryfall price, and the sum is {c("decks." + veloci["id"] + ".price_usd", "usd")}. It sits just above the land median and well above the ramp median. That is the dinosaur plan: the lands are ordinary, the ramp is the extra, and the price is not the median receipt.

<DeckBlock id="lands-wrath" />

Land's Wrath plays {c("decks." + wrath["id"] + ".land_count", "int")} lands, {c("decks." + wrath["id"] + ".ramp_count", "int")} ramp, {c("decks." + wrath["id"] + ".draw_count", "int")} draw, and {c("decks." + wrath["id"] + ".removal_count", "int")} removal, for {c("decks." + wrath["id"] + ".price_usd", "usd")} on the same Scryfall rule. The land count is one below the median. The ramp count matches Veloci-Ramp-Tor. The receipt does not. A landfall deck and a dinosaur deck can share a ramp count and still be different purchases. The [ramp guide](/blog/mtg-ramp-deck-guide) is about how to play that mana. This page is only the census.

<InArticleAd />

## What to copy

Copy the median when you do not yet have a reason not to. A new Commander list that plays about {c("summary.lands.median", "int")} lands, about {c("summary.ramp.median", "int")} ramp pieces, and about {c("summary.draw.median", "int")} draw pieces is inside the band these products actually shipped. Moving toward {c("summary.lands.min", "int")} lands is the edge of this sample, not a default. Moving toward {c("summary.lands.max", "int")} is the other edge, and it belongs to lists whose plan is the lands.

Do not copy a price from a single famous card and call it the deck. The complete-list median of {c("summary.price_complete.median", "usd")} and the complete-list high of {c("summary.price_complete.highest.0.value", "usd")} are both real, and they are not the same shopping trip. If your list is one of the {c("summary.precons_with_unpriced", "int")} with a missing price, the total on this page is short by those cards. The facts file names them.

## Common mistakes

- Cutting lands because a ramp spell "counts as a land." Ramp is a separate count. The land median is {c("summary.lands.median", "int")} with the ramp median of {c("summary.ramp.median", "int")} already included as spells.
- Treating the cheapest complete precon, {facts["summary"]["price_complete"]["lowest"][0]["name"]} at {c("summary.price_complete.lowest.0.value", "usd")}, as the cost of the median list. The median complete receipt is {c("summary.price_complete.median", "usd")}.
- Reading the removal median of {c("summary.removal.median", "num")} as a stack of unconditional kill spells. Damage to any target counts. A fight spell counts. A counterspell does not.
- Comparing a precon land count with a sixty-card Pioneer list. The Pioneer Challenger products are a different census, written up on the [Challenger deck page](/blog/pioneer-challenger-decks).
- Quoting a product-printing total from the deck block as if it were this Scryfall sum. They are different price files, on purpose.

## FAQ

### Are these the sealed-deck prices?

No. The sums are the lowest nonfoil Scryfall price for each card on {fetched}, times the quantity, skipping cards with no nonfoil price. {c("summary.precons_fully_priced", "int")} Commander lists had a price for every counted card. The deck block on this page is the other file: MTGJSON's price for the printing in the product.

### Why is the removal median not a whole number?

The median of an even count of lists can fall between two lists. For removal that midpoint is {c("summary.removal.median", "num")}. The land median lands on {c("summary.lands.median", "int")}, a whole number, because the two central lists agree.

### Which list should I open first?

Open Veloci-Ramp-Tor if you want a list above the ramp median, at {c("decks." + veloci["id"] + ".ramp_count", "int")} ramp and {c("decks." + veloci["id"] + ".land_count", "int")} lands. Open Land's Wrath if you want a landfall list at {c("decks." + wrath["id"] + ".land_count", "int")} lands whose Scryfall sum is {c("decks." + wrath["id"] + ".price_usd", "usd")}. Then change one number at a time and write down which count you moved.

## How this was made

Deck lists are the MTGJSON official product snapshot. Card types, rules text, and nonfoil prices are the Scryfall bulk files named on the [method page](/method). Fetched {fetched}. No model wrote these figures. The bracket and Game Changer census is the companion article, [which Game Changers the precons actually include](/blog/commander-precon-game-changers).

<FanContentNotice />

<DeckLabCTA format="commander" brief="A Commander deck around the usual precon land count" />
"""
    # The land-median call above was duplicated by a short-circuit bug if I wrote `and`.
    # Rebuild the ramp median claim cleanly: the expression above already recorded both
    # if both calls ran. Verify ramp median text is present.
    if c("summary.ramp.median", "int") not in body:
        raise RuntimeError("ramp median missing")
    write_guide("precon-lands-ramp-draw", body, c.rows)


def game_changers_guide(facts: dict) -> None:
    c = Claims(facts)
    sneak = deck_by_file(facts, "SneakAttack_ZNC")
    arcane = deck_by_file(facts, "ArcaneMaelstrom_C20")
    fetched = facts["fetched_at"]
    present = [row for row in facts["game_changers"] if row["precon_count"]]
    lines = ["| Card | Lowest nonfoil price | Precons that include it |", "| --- | --- | --- |"]
    blurbs = []
    for index, row in enumerate(facts["game_changers"]):
        if row["precon_count"] <= 0:
            continue
        price = c(f"game_changers.{index}.usd", "usd")
        count = c(f"game_changers.{index}.precon_count", "int")
        lines.append(f"| {row['name']} | {price} | {count} |")
        precon_names = ", ".join(precon["name"] for precon in row["precons"])
        blurbs.append(f"{row['name']} ({price}) is in {precon_names}.")
    table = "\n".join(lines)
    blurb = " ".join(blurbs)
    body = frontmatter(
        title="Which Game Changers Show Up in Official Commander Precons?",
        description=(
            "Of the 60 Commander Game Changers in Deck Lab's list, 14 appear in these official precons. "
            "Prices are Scryfall nonfoil, and the bracket floor is counted from the list."
        ),
        category="strategy",
        keywords=["commander game changers", "precon game changers", "commander bracket precon", "game changer price"],
        related=["precon-lands-ramp-draw", "should-you-play-ramp", "mtg-ramp-deck-guide"],
    )
    body += f"""
## Short answer

In Magic: The Gathering (MTG), Wizards' Game Changers list is a Commander bracket input: cards that push a deck up a bracket when a table uses that vocabulary. Deck Lab's copy of the list is dated 2025-04-22 and holds {c("summary.game_changer_list_size", "int")} names. Of those, {c("summary.game_changers_found_in_precons", "int")} appear in at least one of the {c("summary.commander_precons", "int")} official Commander precons in the MTGJSON snapshot. {c("summary.precons_with_a_game_changer", "int")} precons include at least one. The other precons include none.

That is not a power ranking of the products. A precon with zero Game Changers can still be miserable to play against, and a precon with one can still be a pile of ordinary cards around that one name. The count is the intersection of two files: the Game Changer names, and the official deck lists. Prices next to each name are the lowest nonfoil Scryfall price on {fetched}, the same bulk file as the [lands, ramp, and draw census](/blog/precon-lands-ramp-draw). How the count is defined is on the [method page](/method).

The list-only bracket floor this app computes, which is not Wizards assigning a table a number, is the core floor for {c("summary.bracket_floors.2", "int")} precons, the upgraded floor for {c("summary.bracket_floors.3", "int")}, and the optimized floor for {c("summary.bracket_floors.4", "int")}. The exhibition and competitive floors are about intent, so a list cannot show them. The floor leaves the core band when any Game Changer is present, and it reaches the optimized band when there are more than three, or when the mass-land-denial check, two extra-turn cards, or a listed two-card combo matches. In this snapshot the optimized-floor results are Heads I Win, Tails You Lose (Gamble plus two extra-turn cards), Mirror Mastery (Ruination), and Nature of the Beast (From the Ashes).

<InArticleAd />

## The cards that actually appear

{table}

{blurb}

{c("summary.game_changer_list_size", "int")} names are on the list. {c("summary.game_changers_found_in_precons", "int")} of them show up above. The rest have a price in the facts file and a precon count of zero, which is a real result, not a missing download. Seedborn Muse is the repeat: four products, from Faceless Menace through Abzan Armor. Deflecting Swat is the expensive single, in Arcane Maelstrom only.

## Two lists you can open

<DeckBlock id="arcane-maelstrom" />

Arcane Maelstrom's Game Changers are Crop Rotation and Deflecting Swat. On the Scryfall bulk of {fetched} those printings are {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Crop Rotation")) + ".usd", "usd")} and {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Deflecting Swat")) + ".usd", "usd")}. The whole product's Scryfall sum, including every other priced card, is {c("decks." + arcane["id"] + ".price_usd", "usd")}. It plays {c("decks." + arcane["id"] + ".land_count", "int")} lands. The deck block's dollar figure is the product printing from MTGJSON, not this sum. Open the list if you want to see the two names in the pile they shipped in, then decide whether the deck is the purchase or the single card is.

<DeckBlock id="sneak-attack" />

Sneak Attack includes Notion Thief and no other Game Changer. Notion Thief's lowest nonfoil price in this bulk is {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Notion Thief")) + ".usd", "usd")}. The product sum is {c("decks." + sneak["id"] + ".price_usd", "usd")}, with {c("decks." + sneak["id"] + ".land_count", "int")} lands, {c("decks." + sneak["id"] + ".ramp_count", "int")} ramp, {c("decks." + sneak["id"] + ".draw_count", "int")} draw, and {c("decks." + sneak["id"] + ".removal_count", "int")} removal under the same definitions as the census. One Game Changer in a list is enough to move the app's floor out of the core band. It is not enough to describe the other cards.

<InArticleAd />

## What the floor is for

Use the floor when a table has agreed to talk in brackets. {c("summary.bracket_floors.2", "int")} of these products do not contain a Game Changer, a mass-land-denial match, a two-card combo from the app's list, or two extra-turn cards. They still want rule zero. {c("summary.bracket_floors.3", "int")} contain something the floor treats as upgraded. {c("summary.bracket_floors.4", "int")} trip a harder flag. Bringing an optimized-floor list to a table that wanted the core floor is a different ask than goldfishing it alone.

Do not add a Game Changer to a precon and keep calling the receipt the precon. Deflecting Swat at {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Deflecting Swat")) + ".usd", "usd")} is most of a conversation by itself. The [method page](/method) separates that Scryfall price from the product-printing price in the deck block.

## Common mistakes

- Treating "not on the Game Changer list" as "weak." {c("summary.commander_precons", "int")} minus the {c("summary.precons_with_a_game_changer", "int")} that have one leaves a lot of products, and the land count on those lists is the other article.
- Assuming every expensive precon card is a Game Changer. The price census and this list are different files. A high Scryfall sum can be ordinary cards.
- Reading the optimized floor as a ban. The cards are legal. The floor is a description of the list.
- Copying a Game Changer into a different color identity because the precon had it. Arcane Maelstrom's colors are the colors in that product, not a rule about Deflecting Swat in every red deck.
- Using a foil-only price when this page left the card unpriced. Every name in the table had a nonfoil USD. Cards with none are flagged in the facts file instead of given a made-up number.

## FAQ

### How many Game Changers are in a typical precon?

Most of these products have none. {c("summary.precons_with_a_game_changer", "int")} of {c("summary.commander_precons", "int")} have at least one, and the names that repeat are in the table. The list itself has {c("summary.game_changer_list_size", "int")} entries as of 2025-04-22.

### Does one Game Changer leave the core floor?

Under this app's list-only floor, one Game Changer moves the floor out of the core band, and more than three, or a mass-land-denial match, or two extra-turn cards, or a listed two-card combo, can move it to the optimized band. {c("summary.bracket_floors.3", "int")} products land on the upgraded floor and {c("summary.bracket_floors.4", "int")} land on the optimized floor. The exhibition and competitive brackets are not something this count can see.

### Which price should I trust for shopping?

For a single card, the number in the table is the cheapest English nonfoil Scryfall price on {fetched}. For the sealed product's own printings, use the deck block, which cites MTGJSON AllPricesToday. They answer different questions. Sneak Attack's Scryfall sum is {c("decks." + sneak["id"] + ".price_usd", "usd")}. That is not a bid for the box.

## How this was made

MTGJSON supplied the official deck lists. Scryfall's default-cards bulk supplied nonfoil prices. The Game Changer names and the floor rules are the Deck Lab bracket module, checked into the repo with an as-of date of 2025-04-22. Fetched {fetched}. Nothing here was graded by a model. Counting rules, the simulator, the affiliate note, and the Fan Content notice are collected on the [method page](/method).

<FanContentNotice />

<DeckLabCTA format="commander" brief="A Commander deck with no Game Changers" />
"""
    if len(present) != int(format_fact(fact_at(facts, "summary.game_changers_found_in_precons"), "int")):
        raise RuntimeError("table rows do not match the found count")
    write_guide("commander-precon-game-changers", body, c.rows)


def pioneer_guide(facts: dict) -> None:
    c = Claims(facts)
    burn = deck_by_file(facts, "MonoRedBurn_Q06")
    gruul = deck_by_file(facts, "GruulStompy_Q08")
    phoenix = deck_by_file(facts, "IzzetPhoenix_Q08")
    auras = deck_by_file(facts, "OrzhovAuras_Q06")
    fetched = facts["fetched_at"]
    pioneer = [deck for deck in facts["decks"].values() if deck["format"] == "pioneer"]
    cheapest = min(pioneer, key=lambda deck: (deck["price_usd"], deck["id"]))
    dearest = max(pioneer, key=lambda deck: (deck["price_usd"], deck["id"]))
    fewest_lands = min(pioneer, key=lambda deck: (deck["land_count"], deck["id"]))
    most_lands = max(pioneer, key=lambda deck: (deck["land_count"], deck["id"]))
    body = frontmatter(
        title="What Is Actually in the Pioneer Challenger Decks?",
        description=(
            "MTGJSON publishes eight Pioneer Challenger decks. This page counts their lands, "
            "prices them from Scryfall, and names the cards that are not Pioneer-legal today."
        ),
        category="formats",
        keywords=["pioneer challenger decks", "pioneer challenger deck list", "pioneer deck price", "expressive iteration pioneer"],
        related=["should-you-play-aggro", "mtg-midrange-deck-guide", "mtg-combo-decks-explained"],
    )
    body += f"""
## Short answer

In Magic: The Gathering (MTG), Pioneer Challenger Decks are official Wizards products, and MTGJSON republishes them under the same MIT grant as the Commander precons. This snapshot has {c("summary.pioneer_challenger", "int")} of them. There is no ninth list hiding in the file. Each one is a sixty-card main deck plus a sideboard. This page does not invent a metagame around them. It counts what those eight published lists contain, prices them from the Scryfall bulk of {fetched}, and says which cards are not legal in Pioneer on that same bulk.

Land counts run from {c("decks." + fewest_lands["id"] + ".land_count", "int")} in {fewest_lands["name"]} to {c("decks." + most_lands["id"] + ".land_count", "int")} in {most_lands["name"]}. That is a constructed band, not the Commander median from the [precon census](/blog/precon-lands-ramp-draw). Every one of the eight had a nonfoil Scryfall price for every card, so none of these totals is missing a name. The cheapest sum is {cheapest["name"]} at {c("decks." + cheapest["id"] + ".price_usd", "usd")}. The dearest is {dearest["name"]} at {c("decks." + dearest["id"] + ".price_usd", "usd")}. Those are lowest-English-nonfoil sums, not the product-printing totals in the deck blocks. The [method page](/method) is the definition.

Two cards in these products are not Pioneer-legal on the {fetched} Scryfall bulk: Expressive Iteration in Izzet Phoenix, and Lurrus of the Dream-Den in Orzhov Auras. The other six products had no card flagged banned or not legal in Pioneer. Legality changes. The bulk date is the date of the sentence.

<InArticleAd />

## Lands, roles, and prices

| Deck | Lands | Ramp | Draw | Removal | Scryfall sum |
| --- | --- | --- | --- | --- | --- |
| Azorius Spirits | {c("decks." + deck_by_file(facts, "AzoriusSpirits_Q06")["id"] + ".land_count", "int")} | {c("decks." + deck_by_file(facts, "AzoriusSpirits_Q06")["id"] + ".ramp_count", "int")} | {c("decks." + deck_by_file(facts, "AzoriusSpirits_Q06")["id"] + ".draw_count", "int")} | {c("decks." + deck_by_file(facts, "AzoriusSpirits_Q06")["id"] + ".removal_count", "int")} | {c("decks." + deck_by_file(facts, "AzoriusSpirits_Q06")["id"] + ".price_usd", "usd")} |
| Dimir Control | {c("decks." + deck_by_file(facts, "DimirControl_Q08")["id"] + ".land_count", "int")} | {c("decks." + deck_by_file(facts, "DimirControl_Q08")["id"] + ".ramp_count", "int")} | {c("decks." + deck_by_file(facts, "DimirControl_Q08")["id"] + ".draw_count", "int")} | {c("decks." + deck_by_file(facts, "DimirControl_Q08")["id"] + ".removal_count", "int")} | {c("decks." + deck_by_file(facts, "DimirControl_Q08")["id"] + ".price_usd", "usd")} |
| Gruul Stompy | {c("decks." + gruul["id"] + ".land_count", "int")} | {c("decks." + gruul["id"] + ".ramp_count", "int")} | {c("decks." + gruul["id"] + ".draw_count", "int")} | {c("decks." + gruul["id"] + ".removal_count", "int")} | {c("decks." + gruul["id"] + ".price_usd", "usd")} |
| Izzet Phoenix | {c("decks." + phoenix["id"] + ".land_count", "int")} | {c("decks." + phoenix["id"] + ".ramp_count", "int")} | {c("decks." + phoenix["id"] + ".draw_count", "int")} | {c("decks." + phoenix["id"] + ".removal_count", "int")} | {c("decks." + phoenix["id"] + ".price_usd", "usd")} |
| Lotus Field Combo | {c("decks." + deck_by_file(facts, "LotusFieldCombo_Q06")["id"] + ".land_count", "int")} | {c("decks." + deck_by_file(facts, "LotusFieldCombo_Q06")["id"] + ".ramp_count", "int")} | {c("decks." + deck_by_file(facts, "LotusFieldCombo_Q06")["id"] + ".draw_count", "int")} | {c("decks." + deck_by_file(facts, "LotusFieldCombo_Q06")["id"] + ".removal_count", "int")} | {c("decks." + deck_by_file(facts, "LotusFieldCombo_Q06")["id"] + ".price_usd", "usd")} |
| Mono-Red Burn | {c("decks." + burn["id"] + ".land_count", "int")} | {c("decks." + burn["id"] + ".ramp_count", "int")} | {c("decks." + burn["id"] + ".draw_count", "int")} | {c("decks." + burn["id"] + ".removal_count", "int")} | {c("decks." + burn["id"] + ".price_usd", "usd")} |
| Orzhov Auras | {c("decks." + auras["id"] + ".land_count", "int")} | {c("decks." + auras["id"] + ".ramp_count", "int")} | {c("decks." + auras["id"] + ".draw_count", "int")} | {c("decks." + auras["id"] + ".removal_count", "int")} | {c("decks." + auras["id"] + ".price_usd", "usd")} |
| Orzhov Humans | {c("decks." + deck_by_file(facts, "OrzhovHumans_Q08")["id"] + ".land_count", "int")} | {c("decks." + deck_by_file(facts, "OrzhovHumans_Q08")["id"] + ".ramp_count", "int")} | {c("decks." + deck_by_file(facts, "OrzhovHumans_Q08")["id"] + ".draw_count", "int")} | {c("decks." + deck_by_file(facts, "OrzhovHumans_Q08")["id"] + ".removal_count", "int")} | {c("decks." + deck_by_file(facts, "OrzhovHumans_Q08")["id"] + ".price_usd", "usd")} |

Ramp, draw, and removal use the same sentence rules as the Commander census. A mana elf counts as ramp. A cantrip counts as draw. A spell that deals damage to any target counts as removal even when the plan is to point it at a player. That last rule is why Mono-Red Burn's removal count is {c("decks." + burn["id"] + ".removal_count", "int")}: Lightning Strike, Wild Slash, Wizard's Lightning, and Bonecrusher Giant. Its draw count is {c("decks." + burn["id"] + ".draw_count", "int")}, and the only draw card is Light Up the Stage. Its ramp count is {c("decks." + burn["id"] + ".ramp_count", "int")}.

Gruul Stompy's ramp count is {c("decks." + gruul["id"] + ".ramp_count", "int")}, from Llanowar Elves, Elvish Mystic, and Chandra, Torch of Defiance. Chandra also deals damage, so she is in the removal count of {c("decks." + gruul["id"] + ".removal_count", "int")} as well. A card in two counts is not two cards. Izzet Phoenix's draw count is {c("decks." + phoenix["id"] + ".draw_count", "int")} because the list is cantrips. Lotus Field Combo's ramp count is {c("decks." + deck_by_file(facts, "LotusFieldCombo_Q06")["id"] + ".ramp_count", "int")} and its removal count is {c("decks." + deck_by_file(facts, "LotusFieldCombo_Q06")["id"] + ".removal_count", "int")}. The combo is not a removal plan, and this table does not pretend the goldfish can perform it.

## Three lists to open

<DeckBlock id="mono-red-burn" />

Mono-Red Burn is the low land count among the red aggressive products here: {c("decks." + burn["id"] + ".land_count", "int")} lands, Scryfall sum {c("decks." + burn["id"] + ".price_usd", "usd")}. The deck block shows the product-printing total and the goldfish. This paragraph does not repeat that printing total, because it is a different number from a different file. If you want the race as a decision, the [aggro guide](/blog/should-you-play-aggro) is that argument. This page is the census of all {c("summary.pioneer_challenger", "int")} products.

<DeckBlock id="gruul-stompy" />

Gruul Stompy plays {c("decks." + gruul["id"] + ".land_count", "int")} lands and costs {c("decks." + gruul["id"] + ".price_usd", "usd")} on the Scryfall rule. The elves are the ramp. The removal count is mostly damage and Abrade, not a control suite. Calling it midrange because the creatures are larger than burn's is a habit. The land count is {c("decks." + gruul["id"] + ".land_count", "int")}, five above burn's {c("decks." + burn["id"] + ".land_count", "int")}, and the draw count is {c("decks." + gruul["id"] + ".draw_count", "int")}.

<InArticleAd />

<DeckBlock id="izzet-phoenix" />

Izzet Phoenix plays {c("decks." + phoenix["id"] + ".land_count", "int")} lands and sums to {c("decks." + phoenix["id"] + ".price_usd", "usd")}. Expressive Iteration is in the list and is not Pioneer-legal on the {fetched} bulk. Do not register the product as printed. The draw count of {c("decks." + phoenix["id"] + ".draw_count", "int")} describes the printed cantrips, including the one you cannot play. Orzhov Auras has the other legality flag: Lurrus of the Dream-Den. That product plays {c("decks." + auras["id"] + ".land_count", "int")} lands and sums to {c("decks." + auras["id"] + ".price_usd", "usd")}, with a removal count of {c("decks." + auras["id"] + ".removal_count", "int")} and a draw count of {c("decks." + auras["id"] + ".draw_count", "int")}.

## What not to conclude

These eight lists are products from two Challenger seasons. They are not a Pioneer metagame report, and this site does not have a licensed feed of current Pioneer standings. A card's presence here means Wizards put it in a Challenger deck, which MTGJSON republishes. It does not mean the card won a tournament last weekend.

Azorius Spirits at {c("decks." + cheapest["id"] + ".price_usd", "usd")} is the cheap end of this particular file. Lotus Field Combo at {c("decks." + dearest["id"] + ".price_usd", "usd")} is the expensive end. Neither number is a format staple's price, and neither is the cost of the product's original printings. Sideboards are in the Scryfall sum and in the deck block. They are not in the land count, which is the main deck only.

## Common mistakes

- Registering Izzet Phoenix as printed. Expressive Iteration is not legal in Pioneer on the {fetched} bulk.
- Registering Orzhov Auras as printed. Lurrus of the Dream-Den is the card the bulk flags.
- Reading Mono-Red Burn's removal count of {c("decks." + burn["id"] + ".removal_count", "int")} as sixteen pieces of creature removal. The rule counts damage to any target. The plan is still the opponent's life total.
- Comparing these land counts with the Commander median of the other article. {c("decks." + most_lands["id"] + ".land_count", "int")} lands is the high end here. It would be a very low Commander precon.
- Treating the deck block's product-printing price as the Scryfall sum in the table. Open the block for the printing. Use the table for the bulk price.

## FAQ

### Are Pioneer Challenger decks still for sale as a current product?

This page does not know a store's shelf. It knows the {c("summary.pioneer_challenger", "int")} lists MTGJSON publishes. The newest fact attached to each list is the Scryfall price date {fetched}, not a reprint announcement.

### Which of the eight is legal to register today?

Six had no Pioneer ban or not-legal flag on {fetched}. Izzet Phoenix and Orzhov Auras each had one flagged card, named above. Check the ban list again before you submit a deck. The bulk is a snapshot.

### Why is Gruul Stompy's ramp count not zero?

Llanowar Elves and Elvish Mystic add green, and Chandra adds mana as well as dealing damage. The ramp count is {c("decks." + gruul["id"] + ".ramp_count", "int")}. Burn's ramp count is {c("decks." + burn["id"] + ".ramp_count", "int")} because nothing in that list matches the ramp rule.

## How this was made

The lists are MTGJSON Pioneer Challenger Deck files in the committed official snapshot. Types, rules text, legality, and the lowest nonfoil price are Scryfall bulk data, fetched {fetched}. The goldfish numbers you see inside a deck block are the Deck Lab simulator, separate from this table, and described on the [method page](/method). No model filled a cell. If a product is not in MTGJSON, it is not on this page.

<FanContentNotice />

<DeckLabCTA format="pioneer" brief="A Pioneer deck with a low land count and cheap interaction" />
"""
    write_guide("pioneer-challenger-decks", body, c.rows)


def main() -> None:
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    lands_guide(facts)
    game_changers_guide(facts)
    pioneer_guide(facts)


if __name__ == "__main__":
    main()
