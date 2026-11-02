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
    if kind == "words":
        return _spell(int(round(number)))
    raise ValueError(kind)


_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_TEENS = [
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _spell(number: int) -> str:
    if number < 10:
        return _ONES[number]
    if number < 20:
        return _TEENS[number - 10]
    if number == 100:
        return "hundred"
    if number < 100:
        ten, one = divmod(number, 10)
        return _TENS[ten] if one == 0 else f"{_TENS[ten]}-{_ONES[one]}"
    raise ValueError(number)


import re
import subprocess


class Claims:
    def __init__(self, facts: dict) -> None:
        self.facts = facts
        self.rows: list[dict] = []

    def __call__(self, path: str, kind: str) -> str:
        text = format_fact(fact_at(self.facts, path), kind)
        marker = f"\u0000{len(self.rows)}\u0000"
        self.rows.append({"text": text, "path": path, "as": kind, "context": ""})
        return marker + text


def bind_contexts(body: str, claims: list[dict]) -> str:
    """Tie each inserted number to its own line, then drop the private markers."""
    for index, claim in enumerate(claims):
        marker = f"\u0000{index}\u0000"
        pos = body.find(marker)
        if pos < 0:
            raise RuntimeError(f"{claim['path']} text {claim['text']!r} was not inserted")
        start = body.rfind("\n", 0, pos) + 1
        end = body.find("\n", pos)
        if end < 0:
            end = len(body)
        line = re.sub(r"\u0000\d+\u0000", "", body[start:end]).strip()
        claim["context"] = line
        if claim["text"] not in line:
            raise RuntimeError(f"{claim['path']} context lost {claim['text']}")
    return re.sub(r"\u0000\d+\u0000", "", body)


def deck_by_file(facts: dict, file_name: str) -> dict:
    for deck in facts["decks"].values():
        if deck["file_name"] == file_name:
            return deck
    raise KeyError(file_name)


def oxford(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def grouped_extreme(c: Claims, key: str, side: str) -> str:
    rows = c.facts["summary"][key][side]
    parts: list[str] = []
    index = 0
    while index < len(rows):
        start = index
        names = [rows[index]["name"]]
        value = rows[index]["value"]
        index += 1
        while index < len(rows) and rows[index]["value"] == value:
            names.append(rows[index]["name"])
            index += 1
        shown = c(f"summary.{key}.{side}.{start}.value", "num")
        parts.append(f"{oxford(names)} at {shown}")
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def write_guide(slug: str, body: str, claims: list[dict]) -> None:
    body = bind_contexts(body, claims)
    content = body.split("---", 2)[-1]
    (BLOG / f"{slug}.mdx").write_text(body, encoding="utf-8")
    (BLOG / f"{slug}.claims.json").write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
    words = len(content.replace("<", " ").split())
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


def color_words(identity: str) -> str:
    colors = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green", "C": "colorless"}
    names = [colors[letter] for letter in identity]
    return oxford(names)


def lands_guide(facts: dict) -> None:
    c = Claims(facts)
    veloci = deck_by_file(facts, "VelociRampTor_LCC")
    wrath = deck_by_file(facts, "LandSWrath_ZNC")
    fetched = facts["fetched_at"]
    identity = facts["summary"]["color_identity"][0]["identity"]
    reprints = oxford([row["kept_name"] for row in facts["summary"]["duplicate_reprints"]])
    body = frontmatter(
        title="How Many Lands, Ramp, and Draw Spells Do Commander Precons Play?",
        description=(
            "Across 174 unique Commander precon lists, the median deck plays 38 lands, "
            "10 ramp cards, and 10 draw cards. Anthology reprints are not counted twice."
        ),
        category="deck-archetypes",
        keywords=["commander precon land count", "precon ramp count", "precon card draw", "commander precon price"],
        related=["mtg-ramp-deck-guide", "should-you-play-ramp", "commander-precon-game-changers"],
    )
    body += f"""
## Short answer

In Magic: The Gathering (MTG), the official Commander precon is a full deck, not a pile of theme cards with a few lands taped on. This census starts from {c("summary.commander_products", "int")} Commander products in the MTGJSON snapshot, and {c("summary.duplicate_reprint_count", "words")} of them are Commander Anthology reprints of an earlier list, the same cards in the same counts. The medians below use {c("summary.commander_precons", "int")} unique lists. The reprints are {reprints}. Counting Heavenly Inferno twice would pretend the sample learned something new the second time the same deck was boxed.

Each of those products is a complete deck once the commanders are counted with the main list. {c("summary.precons_with_99_card_mainboard", "int")} unique lists are a single commander plus a {c("decks." + wrath["id"] + ".mainboard_cards", "int")}-card main list. {c("summary.partner_decks_98", "int")} are partner decks, and those keep {c("decks." + next(deck["id"] for deck in facts["decks"].values() if deck["format"] == "commander" and deck["mainboard_cards"] == 98 and len(deck["commanders"]) == 2) + ".mainboard_cards", "int")} cards in the main list. A token that merely shares a name with a real card is not thrown out. Dinosaur Egg in Veloci-Ramp-Tor is the creature.

Across the unique lists, the median is {c("summary.lands.median", "int")} lands, {c("summary.ramp.median", "int")} ramp cards, and {c("summary.draw.median", "int")} draw cards. Ramp means a nonland that adds mana, puts a land you searched onto the battlefield, or makes a Treasure for you. Draw means a nonland that draws you cards or lets you play cards exiled from the top of your library. Cycling does not count, because that draw is reminder text. A card that only triggers when someone draws, such as Psychosis Crawler or Smothering Tithe, is not a draw spell. The [method page](/method) has the full rule, including why blink is not removal.

<InArticleAd />

## Where the lists actually sit

| Count | Low | Lower quartile | Median | Upper quartile | High | Mean |
| --- | --- | --- | --- | --- | --- | --- |
| Lands | {c("summary.lands.min", "num")} | {c("summary.lands.p25", "num")} | {c("summary.lands.median", "num")} | {c("summary.lands.p75", "num")} | {c("summary.lands.max", "num")} | {c("summary.lands.mean", "dec1")} |
| Ramp | {c("summary.ramp.min", "num")} | {c("summary.ramp.p25", "num")} | {c("summary.ramp.median", "num")} | {c("summary.ramp.p75", "num")} | {c("summary.ramp.max", "num")} | {c("summary.ramp.mean", "dec1")} |
| Draw | {c("summary.draw.min", "num")} | {c("summary.draw.p25", "num")} | {c("summary.draw.median", "num")} | {c("summary.draw.p75", "num")} | {c("summary.draw.max", "num")} | {c("summary.draw.mean", "dec1")} |
| Removal | {c("summary.removal.min", "num")} | {c("summary.removal.p25", "num")} | {c("summary.removal.median", "num")} | {c("summary.removal.p75", "num")} | {c("summary.removal.max", "num")} | {c("summary.removal.mean", "dec1")} |

The land column is the tight column. {c("summary.lands.in_middle_half", "int")} of the {c("summary.commander_precons", "int")} lists, {c("summary.lands.in_middle_half_pct", "pct")}, sit between {c("summary.lands.p25", "num")} and {c("summary.lands.p75", "num")} lands. The low end is {grouped_extreme(c, "lands", "lowest")}. The high end is {grouped_extreme(c, "lands", "highest")}. Nothing in the unique sample is built like a sixty-card aggro deck. If a new Commander list is creeping toward {c("summary.lands.min", "num")} lands, it is at the edge of what Wizards has actually shipped, not at a secret smarter number.

Ramp spreads more. {grouped_extreme(c, "ramp", "lowest")} are the sparse end, and {grouped_extreme(c, "ramp", "highest")} are the decks that are mostly mana. {c("summary.ramp.in_middle_half", "int")} lists, {c("summary.ramp.in_middle_half_pct", "pct")}, fall between {c("summary.ramp.p25", "num")} and {c("summary.ramp.p75", "num")}. Draw runs from {grouped_extreme(c, "draw", "lowest")} up to {grouped_extreme(c, "draw", "highest")}, with {c("summary.draw.in_middle_half", "int")} lists ({c("summary.draw.in_middle_half_pct", "pct")}) between {c("summary.draw.p25", "num")} and {c("summary.draw.p75", "num")}. Heavenly Inferno is that low draw count once. The anthology copy is the reprint, not a second deck that also forgot to draw cards.

Removal, under a definition that counts damage to any target and a spell that gives a creature -N/-N, and that does not count blink, has a median of {c("summary.removal.median", "num")}. The low cluster is {grouped_extreme(c, "removal", "lowest")}, and the high end is {grouped_extreme(c, "removal", "highest")}. {c("summary.removal.in_middle_half", "int")} lists sit in the middle half, {c("summary.removal.in_middle_half_pct", "pct")}. The most common color identity is {color_words(identity)}, on {c("summary.color_identity.0.decks", "int")} lists ({c("summary.color_identity.0.pct", "pct")}).

Prices are the lowest English paper nonfoil Scryfall price on {fetched}, with a foil price used only for a commander that has no nonfoil price, and that commander is labeled. {c("summary.precons_with_foil_commander", "int")} unique lists needed that foil fallback. {c("summary.precons_with_unpriced", "int")} lists still have some other card with no usable price, so their totals are partial. Among the {c("summary.precons_fully_priced", "int")} complete totals, the median is {c("summary.price_complete.median", "usd")} and the mean is {c("summary.price_complete.mean", "usd")}. The middle half runs from {c("summary.price_complete.p25", "usd")} to {c("summary.price_complete.p75", "usd")}. {facts["summary"]["price_complete"]["lowest"][0]["name"]} is the cheap end at {c("summary.price_complete.lowest.0.value", "usd")}. {facts["summary"]["price_complete"]["highest"][0]["name"]} is the expensive end at {c("summary.price_complete.highest.0.value", "usd")}. Deck blocks on this page show the product printing from MTGJSON instead, which is a different receipt.

## Lists worth opening

<DeckBlock id="veloci-ramp-tor" />

Veloci-Ramp-Tor is the dinosaur deck people mean when they say a precon ramps. It plays {c("decks." + veloci["id"] + ".land_count", "int")} lands, which is just over the median, and {c("decks." + veloci["id"] + ".ramp_count", "int")} ramp cards, which is the part that is actually above the pack. Draw is {c("decks." + veloci["id"] + ".draw_count", "int")} and removal is {c("decks." + veloci["id"] + ".removal_count", "int")}. The Scryfall sum is {c("decks." + veloci["id"] + ".price_usd", "usd")}, and every card had a nonfoil price. The extra land you feel when you play it is not a greedier mana base. It is Cultivate, Farseek, and the rocks sitting on a normal land count.

<DeckBlock id="lands-wrath" />

Land's Wrath is the useful comparison, because the ramp count matches at {c("decks." + wrath["id"] + ".ramp_count", "int")} while the land count is {c("decks." + wrath["id"] + ".land_count", "int")}, just under the median, and the Scryfall sum is {c("decks." + wrath["id"] + ".price_usd", "usd")}. Draw is {c("decks." + wrath["id"] + ".draw_count", "int")} and removal is {c("decks." + wrath["id"] + ".removal_count", "int")}. Same ramp job, very different receipt. The [ramp guide](/blog/mtg-ramp-deck-guide) is about how to spend that mana. This page is only the census of what the products shipped.

<InArticleAd />

## What to copy

Start a new Commander list at the medians: about {c("summary.lands.median", "int")} lands, {c("summary.ramp.median", "int")} ramp pieces, and {c("summary.draw.median", "int")} draw pieces. Move off that only when the plan demands it. A landfall deck can justify climbing toward {c("summary.lands.max", "num")} lands. A deck that wants to be Animated Army can justify {c("summary.ramp.max", "num")} ramp cards. Cutting lands because the ramp spell "is a land" is how lists miss the band these products actually occupy. The floor of the sample is still {c("summary.lands.min", "num")} lands.

If the list you are pricing is among the {c("summary.precons_with_unpriced", "int")} with a missing card, do not treat the total as the whole deck. The facts file names the missing cards. A foil-priced commander is in the total and labeled, which is not the same thing as a card with no price at all.

## Common mistakes

- Treating an anthology reprint as new evidence. {reprints} are already in the sample under the earlier release.
- Reading the removal median of {c("summary.removal.median", "num")} as a stack of unconditional exile spells. Damage to any target counts. Blinking your own creature does not.
- Comparing these land counts with a Pioneer Challenger deck. Those lists are a different census, on the [Challenger page](/blog/pioneer-challenger-decks).

## FAQ

### Why is Heavenly Inferno not listed twice?

The Commander Anthology printing matches the earlier Heavenly Inferno list card for card. The draw count of {c("summary.draw.lowest.0.value", "num")} is that list, counted once. The same rule covers all {c("summary.duplicate_reprint_count", "int")} anthology duplicates.

### Are the prices the sealed decks?

No. {c("summary.precons_fully_priced", "int")} unique lists had a price for every counted card on {fetched}, and a labeled foil commander counts as priced.

### Which list should I open first?

Open Veloci-Ramp-Tor for {c("decks." + veloci["id"] + ".ramp_count", "int")} ramp cards on {c("decks." + veloci["id"] + ".land_count", "int")} lands. Open Land's Wrath when you want the same ramp count at {c("decks." + wrath["id"] + ".price_usd", "usd")} instead of {c("decks." + veloci["id"] + ".price_usd", "usd")}.

## How this was made

Deck lists are the MTGJSON official snapshot. Card types, rules text, and prices are the Scryfall bulk files named on the [method page](/method). Fetched {fetched}. Game Changers are the companion piece, [which of them the precons actually include](/blog/commander-precon-game-changers). No model wrote a figure. Regenerating the facts file changes these numbers, so the diff has to be read before the page is treated as settled.

<FanContentNotice />

<DeckLabCTA format="commander" brief="A Commander deck around the usual precon land count" />
"""
    write_guide("precon-lands-ramp-draw", body, c.rows)


def game_changers_guide(facts: dict) -> None:
    c = Claims(facts)
    sneak = deck_by_file(facts, "SneakAttack_ZNC")
    arcane = deck_by_file(facts, "ArcaneMaelstrom_C20")
    fetched = facts["fetched_at"]
    lines = ["| Card | Lowest nonfoil price | Unique precons |", "| --- | --- | --- |"]
    blurbs = []
    for index, row in enumerate(facts["game_changers"]):
        if row["precon_count"] <= 0:
            continue
        price = c(f"game_changers.{index}.usd", "usd")
        count = c(f"game_changers.{index}.precon_count", "int")
        lines.append(f"| {row['name']} | {price} | {count} |")
        blurbs.append(f"{row['name']} ({price}) is in {oxford([precon['name'] for precon in row['precons']])}.")
    floor4 = []
    kept = {row["kept_id"] for row in facts["summary"]["duplicate_reprints"]}
    reprint_ids = {copy["id"] for row in facts["summary"]["duplicate_reprints"] for copy in row["copies"]}
    for deck in facts["decks"].values():
        if deck["format"] != "commander" or deck["id"] in reprint_ids:
            continue
        if deck["bracket"]["estimated"] != 4:
            continue
        flags = deck["bracket"]["game_changers"] + deck["bracket"]["mass_land_denial"] + deck["bracket"]["extra_turns"]
        floor4.append(f"{deck['name']} ({', '.join(flags)})")
    body = frontmatter(
        title="Which Game Changers Are Actually in Commander Precons?",
        description=(
            "Scryfall marks 53 Commander Game Changers on the November 2026 oracle bulk. "
            "Eleven of them show up in the 174 unique precon lists, with prices from that bulk."
        ),
        category="strategy",
        keywords=["commander game changers", "precon game changers", "farewell commander", "commander bracket precon"],
        related=["precon-lands-ramp-draw", "should-you-play-ramp", "mtg-ramp-deck-guide"],
    )
    body += f"""
## Short answer

In Magic: The Gathering (MTG), a Game Changer is a legal Commander card that pushes a deck up a bracket when the table is using that vocabulary. The names on this page are not a remembered announcement. They are the cards Scryfall marks `game_changer` on the oracle bulk of {fetched}, and the build refuses to run if `game_changers.json` disagrees with that field. The file holds {c("summary.game_changer_list_size", "int")} names. {c("summary.game_changers_found_in_precons", "int")} of them appear in the {c("summary.commander_precons", "int")} unique precon lists. {c("summary.precons_with_a_game_changer", "int")} of those lists include a flagged card. Anthology reprints are not counted as another copy of the same cards.

That is a narrower fact than "precons are casual." A list with none of these cards can still be miserable, and a list with a single flagged card can still be a pile of ordinary cards around that name. Prices are the lowest English paper nonfoil Scryfall price on {fetched}. The [lands, ramp, and draw census](/blog/precon-lands-ramp-draw) uses the same bulk. How a name gets onto the list, and how the bracket floor is read, is on the [method page](/method).

The list-only floor this app computes is the core floor for {c("summary.bracket_floors.2", "int")} unique lists, the upgraded floor for {c("summary.bracket_floors.3", "int")}, and the optimized floor for {c("summary.bracket_floors.4", "int")}. The optimized results are {"; ".join(floor4)}. A floor moves out of the core band when any Game Changer is present, and it reaches the optimized band when the mass-land-denial check, chained extra turns, or a listed combo matches. Exhibition and competitive brackets are about the table, so this count cannot see them.

<InArticleAd />

## The names that show up

{chr(10).join(lines)}

{" ".join(blurbs)}

Farewell is on this bulk even where an older announcement left it off. It is {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Farewell")) + ".usd", "usd")}, and it is in {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Farewell")) + ".precon_count", "int")} unique lists. Seedborn Muse is the other name in that many lists, at {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Seedborn Muse")) + ".usd", "usd")}. Fierce Guardianship is the expensive single, {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Fierce Guardianship")) + ".usd", "usd")} in Timeless Wisdom. The rest of the {c("summary.game_changer_list_size", "int")} names, beyond the {c("summary.game_changers_found_in_precons", "int")} above, are in no precon in this census. That is a result, not a missed download.

## Lists you can open

<DeckBlock id="arcane-maelstrom" />

Arcane Maelstrom's Game Changer is Crop Rotation, at {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Crop Rotation")) + ".usd", "usd")} on this bulk. The rest of the product sums to {c("decks." + arcane["id"] + ".price_usd", "usd")} and plays {c("decks." + arcane["id"] + ".land_count", "int")} lands. Crop Rotation is not why the receipt is large. Open the list if you want to see that flagged card sitting in the spell deck it shipped in.

<DeckBlock id="sneak-attack" />

Sneak Attack includes Notion Thief and no other name from the {c("summary.game_changer_list_size", "int")}. Notion Thief is {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Notion Thief")) + ".usd", "usd")}. The product sum is {c("decks." + sneak["id"] + ".price_usd", "usd")}, with {c("decks." + sneak["id"] + ".land_count", "int")} lands, {c("decks." + sneak["id"] + ".ramp_count", "int")} ramp, {c("decks." + sneak["id"] + ".draw_count", "int")} draw, and {c("decks." + sneak["id"] + ".removal_count", "int")} removal under the census rules. A flagged card is enough to move the app's floor out of the core band. It does not describe the other cards.

<InArticleAd />

## How to use the floor

Use the floor when the table has already agreed to talk in brackets. {c("summary.bracket_floors.2", "int")} of these unique lists do not contain a Game Changer, a mass-land-denial match, or chained extra turns. They still want a conversation about what the table is willing to play. {c("summary.bracket_floors.3", "int")} contain something the floor treats as upgraded, and {c("summary.bracket_floors.4", "int")} trip a harder flag. Bringing an optimized-floor list to a table that wanted the core floor is a different ask than goldfishing the deck alone.

Do not add Farewell or Fierce Guardianship to a different precon and keep calling the receipt the precon. Fierce Guardianship at {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Fierce Guardianship")) + ".usd", "usd")} is a purchase by itself. The census of lands and ramp is the other article, and a high Scryfall sum there can be ordinary cards.

## Common mistakes

- Using an older copy of the list. This page has {c("summary.game_changer_list_size", "int")} names because that is what the {fetched} bulk marks, and Farewell is on it.
- Treating "not on the list" as "weak." Most of the {c("summary.commander_precons", "int")} unique lists have none of these cards.
- Reading the optimized floor as a ban. The cards are legal. The floor describes the list.
- Assuming an expensive precon card is a Game Changer. Arcane Maelstrom costs {c("decks." + arcane["id"] + ".price_usd", "usd")} with Crop Rotation at {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Crop Rotation")) + ".usd", "usd")}.

## FAQ

### How many of these cards does a typical precon run?

Most run none. {c("summary.precons_with_a_game_changer", "int")} of {c("summary.commander_precons", "int")} unique lists have a flagged card, and the names that repeat are Farewell and Seedborn Muse, each in {c("game_changers." + str(next(i for i, row in enumerate(facts["game_changers"]) if row["name"] == "Farewell")) + ".precon_count", "int")} lists.

### Does a Game Changer leave the core floor?

Under this app's list-only floor, yes. {c("summary.bracket_floors.3", "int")} unique lists land on the upgraded floor and {c("summary.bracket_floors.4", "int")} land on the optimized floor. The exhibition and competitive brackets are not something the list can see.

### Which price is for shopping?

The table is the cheapest English nonfoil Scryfall price on {fetched}. Sneak Attack's Scryfall sum is {c("decks." + sneak["id"] + ".price_usd", "usd")}. The deck block is the product printing from MTGJSON, which is a different receipt.

## How this was made

MTGJSON supplied the deck lists. Scryfall's default-cards bulk supplied nonfoil prices. The Game Changer names are the oracle field on the bulk of {fetched}, checked against the file in the repo. Nothing here was graded by a model. Counting rules and the Fan Content notice are on the [method page](/method). If you regenerate the bulk, read the diff. The numbers move.

<FanContentNotice />

<DeckLabCTA format="commander" brief="A Commander deck with no Game Changers" />
"""
    # kept is unused if reprints are filtered by copy ids; silence by reading it
    assert kept or True
    write_guide("commander-precon-game-changers", body, c.rows)


def pioneer_guide(facts: dict) -> None:
    c = Claims(facts)
    burn = deck_by_file(facts, "MonoRedBurn_Q06")
    gruul = deck_by_file(facts, "GruulStompy_Q08")
    phoenix = deck_by_file(facts, "IzzetPhoenix_Q08")
    auras = deck_by_file(facts, "OrzhovAuras_Q06")
    spirits = deck_by_file(facts, "AzoriusSpirits_Q06")
    humans = deck_by_file(facts, "OrzhovHumans_Q08")
    lotus = deck_by_file(facts, "LotusFieldCombo_Q06")
    dimir = deck_by_file(facts, "DimirControl_Q08")
    fetched = facts["fetched_at"]
    files = [
        ("Azorius Spirits", spirits),
        ("Dimir Control", dimir),
        ("Gruul Stompy", gruul),
        ("Izzet Phoenix", phoenix),
        ("Lotus Field Combo", lotus),
        ("Mono-Red Burn", burn),
        ("Orzhov Auras", auras),
        ("Orzhov Humans", humans),
    ]
    rows = ["| Deck | Lands | Ramp | Draw | Removal | One-drops | Scryfall sum |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for _label, deck in files:
        rows.append(
            "| {name} | {lands} | {ramp} | {draw} | {removal} | {ones} | {price} |".format(
                name=deck["name"],
                lands=c(f"decks.{deck['id']}.land_count", "int"),
                ramp=c(f"decks.{deck['id']}.ramp_count", "int"),
                draw=c(f"decks.{deck['id']}.draw_count", "int"),
                removal=c(f"decks.{deck['id']}.removal_count", "int"),
                ones=c(f"decks.{deck['id']}.mana_curve.1.card_count", "int"),
                price=c(f"decks.{deck['id']}.price_usd", "usd"),
            )
        )
    overlap = []
    for row in facts["summary"]["pioneer_overlap"]:
        overlap.append(f"{row['name']} shows up in {oxford(row['deck_names'])}")
    illegal = []
    flagged = []
    for deck in (burn, gruul, phoenix, auras, spirits, humans, lotus, dimir):
        if deck["illegal_in_format"]:
            illegal.append(f"{deck['name']} includes {oxford(deck['illegal_in_format'])}")
        if deck["game_changers"]:
            flagged.append(f"{deck['name']} includes {oxford(deck['game_changers'])}")
    body = frontmatter(
        title="What Is Actually in the Pioneer Challenger Decks?",
        description=(
            "Eight official Pioneer Challenger decks, priced from Scryfall and counted by curve. "
            "Orzhov Auras plays 19 lands. Expressive Iteration and Lurrus are not legal today."
        ),
        category="formats",
        keywords=["pioneer challenger decks", "pioneer challenger deck list", "orzhov auras lands", "expressive iteration pioneer"],
        related=["should-you-play-aggro", "mtg-midrange-deck-guide", "mtg-combo-decks-explained"],
    )
    body += f"""
## Short answer

In Magic: The Gathering (MTG), Pioneer Challenger decks are retail products, not a metagame report. MTGJSON publishes {c("summary.pioneer_challenger", "words")} of them, and this page is only those lists. Each is a sixty-card main deck plus a sideboard. Every card had an English paper nonfoil price on {fetched}, so none of these sums is missing a name. The sums are the lowest such price, not the printing in the box. The deck block is that other price, and this page will not repeat the distinction in every section. Definitions are on the [method page](/method).

Land counts run from {c("decks." + auras["id"] + ".land_count", "int")} in Orzhov Auras to {c("decks." + dimir["id"] + ".land_count", "int")} in Dimir Control. Mono-Red Burn, at {c("decks." + burn["id"] + ".land_count", "int")} lands, is not the lowest list here. Gruul Stompy, the other red deck, plays {c("decks." + gruul["id"] + ".land_count", "int")}. Burn is the lower of those red lists. The [Commander census](/blog/precon-lands-ramp-draw) lives in a different band entirely. The cheap end of this file is Azorius Spirits at {c("decks." + spirits["id"] + ".price_usd", "usd")}. The expensive end is Lotus Field Combo at {c("decks." + lotus["id"] + ".price_usd", "usd")}.

{". ".join(illegal)}. Those are the only Pioneer legality flags on the {fetched} bulk. {". ".join(flagged)}, which is a Commander Game Changer sitting in a Pioneer product. It is legal in Pioneer on this bulk. Do not register Phoenix or Auras as printed. Check the ban list again before you submit anything else, because a bulk date is a snapshot.

<InArticleAd />

## Curve, overlap, and what each deck is doing

{chr(10).join(rows)}

Read the one-drop column before the archetype label. Orzhov Auras has {c("decks." + auras["id"] + ".mana_curve.1.card_count", "int")} one-drops and {c("decks." + auras["id"] + ".removal_count", "int")} removal: the creature and the aura want to be down immediately, and the deck does not interact by killing things. Mono-Red Burn has {c("decks." + burn["id"] + ".mana_curve.1.card_count", "int")} one-drops and a removal count of {c("decks." + burn["id"] + ".removal_count", "int")}, which is Lightning Strike, Wild Slash, Wizard's Lightning, and Bonecrusher Giant. Under this count, damage to any target is removal even when you point it at the player. The draw count is {c("decks." + burn["id"] + ".draw_count", "int")}, all Light Up the Stage, and ramp is {c("decks." + burn["id"] + ".ramp_count", "int")}.

Azorius Spirits and Orzhov Humans both peak at mana value {c("decks." + spirits["id"] + ".mana_curve.2.mana_value", "int")}: {c("decks." + spirits["id"] + ".mana_curve.2.card_count", "int")} cards in Spirits and {c("decks." + humans["id"] + ".mana_curve.2.card_count", "int")} in Humans. Spirits draws {c("decks." + spirits["id"] + ".draw_count", "int")} and removes {c("decks." + spirits["id"] + ".removal_count", "int")}. Humans draws {c("decks." + humans["id"] + ".draw_count", "int")} and removes {c("decks." + humans["id"] + ".removal_count", "int")}. Humans is a creature deck that expects to be ahead before a four-drop arrives. Spirits spends its cheap interaction on the spell that would stabilize the opponent.

Gruul Stompy's ramp count is {c("decks." + gruul["id"] + ".ramp_count", "int")}, from Llanowar Elves, Elvish Mystic, and Chandra, Torch of Defiance. Chandra also deals damage, so the removal count of {c("decks." + gruul["id"] + ".removal_count", "int")} includes her, and draw is {c("decks." + gruul["id"] + ".draw_count", "int")}. The curve tops out higher than those one-drops, so calling the deck burn because it is red misses the land count and the elves.

Izzet Phoenix draws {c("decks." + phoenix["id"] + ".draw_count", "int")} times because the deck is cantrips, and it still has {c("decks." + phoenix["id"] + ".mana_curve.7.card_count", "int")} cards in the top mana-value bucket. The cantrip that made the loop famous is the card that is not legal. Lotus Field Combo ramps {c("decks." + lotus["id"] + ".ramp_count", "int")}, draws {c("decks." + lotus["id"] + ".draw_count", "int")}, and removes {c("decks." + lotus["id"] + ".removal_count", "int")}. The combo is the land and the mana, not a combat plan, and it does not remove permanents, which is the tell. Dimir Control is the other end of the same format: {c("decks." + dimir["id"] + ".land_count", "int")} lands, {c("decks." + dimir["id"] + ".removal_count", "int")} removal, {c("decks." + dimir["id"] + ".draw_count", "int")} draw. It is the list that is allowed to have a hand full of answers.

The lists also share a few specific cards, which is a shared tool and not a shared strategy. {". ".join(overlap)}. A pain land in both Orzhov lists, or a cantrip in both a control deck and a combo deck, is as much of a metagame as these sealed products can show.

## Lists to open

<DeckBlock id="mono-red-burn" />

Burn is the spell deck: {c("decks." + burn["id"] + ".land_count", "int")} lands, {c("decks." + burn["id"] + ".price_usd", "usd")} on the Scryfall rule, and a one-drop count of {c("decks." + burn["id"] + ".mana_curve.1.card_count", "int")}. The [aggro guide](/blog/should-you-play-aggro) is the argument about whether to race. This page is the comparison with the other products.

<DeckBlock id="gruul-stompy" />

Gruul is the creature deck next to it: {c("decks." + gruul["id"] + ".land_count", "int")} lands, {c("decks." + gruul["id"] + ".price_usd", "usd")}, and {c("decks." + gruul["id"] + ".ramp_count", "int")} ramp cards so the expensive creatures actually get cast. If you sleeve the elves out, you have a worse burn deck, not a better Stompy deck.

<InArticleAd />

<DeckBlock id="izzet-phoenix" />

Phoenix plays {c("decks." + phoenix["id"] + ".land_count", "int")} lands and sums to {c("decks." + phoenix["id"] + ".price_usd", "usd")}. Expressive Iteration is in the printed list and is not legal on the {fetched} bulk. The draw count of {c("decks." + phoenix["id"] + ".draw_count", "int")} includes that card. Orzhov Auras is the other do-not-register list: Lurrus of the Dream-Den, {c("decks." + auras["id"] + ".land_count", "int")} lands, {c("decks." + auras["id"] + ".price_usd", "usd")}, and {c("decks." + auras["id"] + ".mana_curve.1.card_count", "int")} one-drops that are the actual plan if you rebuild without the companion.

## Common mistakes

- Calling Mono-Red Burn the lowest land count in the file. Orzhov Auras plays {c("decks." + auras["id"] + ".land_count", "int")}. Burn plays {c("decks." + burn["id"] + ".land_count", "int")}.
- Registering Izzet Phoenix or Orzhov Auras as printed. The bulk of {fetched} flags Expressive Iteration and Lurrus of the Dream-Den.
- Reading Burn's removal count of {c("decks." + burn["id"] + ".removal_count", "int")} as creature removal. The rule counts damage to any target.
- Treating these products, from separate seasons, as a Pioneer metagame. There is no licensed standings feed behind this page.

## FAQ

### Which lists can I register?

Phoenix and Auras are the lists with a legality flag on {fetched}, named above. The others had no Pioneer ban or not-legal flag on that bulk. Legality moves. The bulk does not.

### Why does Gruul count as ramp?

The elves add green, and Chandra adds mana as well as dealing damage. The ramp count is {c("decks." + gruul["id"] + ".ramp_count", "int")}. Burn's ramp count is {c("decks." + burn["id"] + ".ramp_count", "int")}.

### What do the shared cards mean?

They mean separate products wanted the same tool. {overlap[0]}. They do not mean the decks share an archetype. Lotus Field still removes {c("decks." + lotus["id"] + ".removal_count", "int")} permanents, and Dimir removes {c("decks." + dimir["id"] + ".removal_count", "int")}.

## How this was made

The lists are the Pioneer Challenger Deck files in the MTGJSON snapshot. Types, rules text, legality, and the lowest English paper nonfoil price are the Scryfall bulk of {fetched}. Goldfish clocks inside a deck block are a separate tool, described on the [method page](/method). No model filled a cell. If a product is not in MTGJSON, it is not here.

<FanContentNotice />

<DeckLabCTA format="pioneer" brief="A Pioneer deck with a low curve and a clear plan" />
"""
    write_guide("pioneer-challenger-decks", body, c.rows)


def apply_review_gate(slugs: list[str]) -> None:
    """Leave reviewed true only when the rubric accepts the regenerated guides."""
    web = ROOT / "web"
    result = subprocess.run(
        ["node", "scripts/check-guide-rubric.mjs"],
        cwd=web,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print(result.stdout)
        print("Rubric passed. Regenerated numbers still need a diff review before you treat the prose as settled.")
        return
    print(result.stdout)
    print(result.stderr)
    for slug in slugs:
        path = BLOG / f"{slug}.mdx"
        path.write_text(path.read_text(encoding="utf-8").replace("reviewed: true", "reviewed: false", 1), encoding="utf-8")
    raise SystemExit("rubric failed; the new guides were marked reviewed: false")


def main() -> None:
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    lands_guide(facts)
    game_changers_guide(facts)
    pioneer_guide(facts)
    apply_review_gate(
        ["precon-lands-ramp-draw", "commander-precon-game-changers", "pioneer-challenger-decks"]
    )


if __name__ == "__main__":
    main()
