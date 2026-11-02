"""Write the reviewed guides from cached deck facts.

Reads web/src/data/example-decks.json (produced by build_guide_facts) and
overwrites the pilot and archetype articles. Numbers are interpolated from
that file so the prose cannot drift from the fetch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FACTS = ROOT / "web" / "src" / "data" / "example-decks.json"
BLOG = ROOT / "web" / "content" / "blog"

COLORS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:.2f}"


def pct(share: float | None) -> str:
    if share is None:
        return "n/a"
    return f"{share * 100:.1f}%"


def words_of(body: str) -> int:
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"[#>*_`|-]", " ", text)
    return len([part for part in text.split() if part])


def deck_line(deck: dict) -> str:
    who = deck["name"]
    if deck["commander"]:
        who += f", commanded by {deck['commander']}"
    return who


# Reviewed guides publish together on merge. The old drip ran through 2027-01-20.
PUBLISH_ON = "2026-11-01"


def price_scope(deck: dict) -> str:
    """What a product total is allowed to claim.

    An unpriced printing is missing from the sum. Do not describe that sum as
    the main deck, sideboard, and commander.
    """
    unpriced = list(deck["analysis"]["unpriced"])
    if not unpriced:
        return "main deck, sideboard, and commander"
    names = ", ".join(unpriced)
    label = "card" if len(unpriced) == 1 else "cards"
    return f"priced cards only, {len(unpriced)} unpriced {label} ({names})"


def sources_sentence(deck: dict) -> str:
    sources = deck["analysis"]["color_sources"]
    parts = [f"{sources[color]} {COLORS[color]}" for color in "WUBRG" if sources.get(color)]
    if not parts:
        return f"{deck['name']} showed no colored mana sources."
    lands = deck["analysis"]["land_count"]
    listed = ", ".join(parts)
    # produced_mana counts every permanent that can add a color, including creatures.
    if any(sources.get(color, 0) > lands for color in "WUBRG"):
        joined = " and ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + f", and {parts[-1]}"
        return (
            f"{deck['name']} plays {lands} lands. "
            f"It can produce mana with {joined} sources, because some creatures also add mana."
        )
    return f"{deck['name']} has {listed} mana sources and {lands} land cards."


def curve_sentence(deck: dict) -> str:
    points = [point for point in deck["analysis"]["mana_curve"] if point["card_count"]]
    bits = []
    for point in points:
        label = "7+" if point["mana_value"] == 7 else str(point["mana_value"])
        bits.append(f"{point['card_count']} at {label}")
    zone = "the 99" if deck["commander"] else "the main deck"
    return f"{deck['name']}'s nonland curve is {', '.join(bits)}, and it plays {deck['analysis']['land_count']} lands in {zone}."


def cost_sentence(deck: dict, fetched_at: str) -> str:
    analysis = deck["analysis"]
    top = ", ".join(
        f"{card['quantity']} {card['name']} ({money(card['line_usd'])})" for card in analysis["top_cards"]
    )
    return (
        f"On the {fetched_at} AllPricesToday nonfoil printings, {deck['name']} is "
        f"{money(analysis['total_cost_usd'])} for {price_scope(deck)}. "
        f"The three most expensive nonbasic names are {top}, {pct(analysis['top3_share'])} of that priced total."
    )


def fish_sentence(deck: dict) -> str:
    fish = deck["analysis"]["goldfish"]
    if fish["wins"] == 0:
        return (
            f"{deck['name']} won 0 of {fish['games']} goldfish games "
            f"(seed {fish['seed']}, {fish['policy']} policy, opponent at {fish['starting_life']} life, "
            f"{fish['max_turns']} turns)."
        )
    return (
        f"{deck['name']} won {pct(fish['win_rate'])} of {fish['games']} goldfish games, "
        f"average winning turn {fish['avg_kill_turn']} (median {fish['median_kill_turn']}, seed {fish['seed']}, "
        f"{fish['policy']} policy, opponent at {fish['starting_life']} life)."
    )


def illegal_sentence(deck: dict, fetched_at: str) -> str:
    names = deck["analysis"]["illegal_in_format"]
    if not names:
        return (
            f"Every card in {deck['name']} is legal in {deck['format']} today per the Scryfall bulk of {fetched_at}."
        )
    joined = ", ".join(names)
    verb = "is" if len(names) == 1 else "are"
    return f"{joined} {verb} not legal today per the Scryfall bulk of {fetched_at}."


# Deck-specific play, one home per list. These are not shared across the
# should-you-play page and the how-to page.
PLAY_NOTES: dict[str, str] = {
    "mono-red-burn": (
        "Keep a hand that can cast two spells before turn four, and point the one-mana spells at the opponent "
        "unless a blocker would deal more damage than the spell. A hand of three lands and two four-drops is not "
        "this deck: the race is the one-drops. If the opponent plays a creature that does not race you, ignore it. "
        "The sideboard is where you answer a creature deck that is faster than the goldfish assumed, not where you "
        "add a five-drop because it looks powerful."
    ),
    "gruul-stompy": (
        "Trade the two-drops. Save the four- and five-drops for a turn they can attack more than once. "
        "Chandra is one of the three names that dominate the receipt, so she has to stay in play and win the "
        "middle turns, not trade for the first creature you see. A sweeper that kills your two-drops is why this "
        "list is a turn slower than burn, and that turn is the plan, not a mistake. Do not shave a land to fit "
        "another two-drop; the curve reaches five."
    ),
    "dimir-control": (
        "Decide which threat you are allowed to answer, and take the others on the life total. Spending the "
        "two-mana answer on a one-drop that was not going to kill you is how this deck loses with cards still "
        "in hand. Make the land drop before you tap out for the finisher. The early turns look empty because "
        "the deck is waiting, and the goldfish records that wait as a loss."
    ),
    "seize-control": (
        "Cast Mizzix, then cast the four- and five-mana spells the curve is full of. The experience counters "
        "are the discount; holding up one blue mana the way a Pioneer permission deck does wastes the commander. "
        "A hand of counters and no spell you actually want to resolve cheaper is a mulligan. The product name "
        "says control. The turns you play are a spell deck that happens to be slow."
    ),
    "veloci-ramp-tor": (
        "Spend the early turns on land drops and the three-mana ramp, not on attacks. Pantlaza discovers into "
        "a curve that still has seven-drops, so a hand of two lands and three of those seven-drops is a mulligan "
        "even though every card is a dinosaur you want. Do not cut lands to sleeve another dinosaur. The extra "
        "land is the ramp plan's floor. Akroma's Will is the expensive card because it saves the turn you finally attack, "
        "not because it ramps."
    ),
    "lands-wrath": (
        "Obuun wants a land entering the battlefield, not a mana rock that dies to a two-drop. A spell that puts "
        "a land into play is the ramp. A creature that taps for mana is a different deck and a different clock. "
        "If you add another landfall payoff, take it from a creature slot. Taking it from the land count strands "
        "the payoff the deck is named for. Count the lands by hand before you call the list greedy."
    ),
    "orzhov-humans": (
        "This curve stops at two mana. There is no five-drop to take over the midgame, so you have to be ahead "
        "on creatures before the opponent's four-drop arrives, and the expensive cards are the lands that let "
        "you cast both colors on time. A hand with the shock land and no two-drop is not a keep just because "
        "the land was pricey. Play the creatures. The mana base is the receipt, not the threat."
    ),
    "lotus-field": (
        "Name the pile before you sleeve it: Lotus Field, the mana it makes, and the payoff that spends that mana. "
        "If you cannot point at those cards in the list below, you do not have the combo, you have a pile of "
        "spells. Practice the line by hand. Adding creatures so a combat simulator has something to attack with "
        "turns the deck into a bad midrange list. The land is the combo. A cheaper land from another product is not a stand-in."
    ),
    "azorius-spirits": (
        "Attack with the two-drop fliers and spend the cheap interaction on the spell that would stabilize the "
        "opponent, not on the first spell they cast. If the game reaches a board of five-drops, the two-drops "
        "are no longer ahead. That is the trade this deck makes on purpose. Cutting the interaction to add more "
        "creatures makes a worse aggro deck, not a better tempo deck."
    ),
    "izzet-phoenix": (
        "Do not register this list. The cantrip the deck was built around is not legal in Pioneer on the current "
        "bulk, and the combat clock without that cantrip is not a tempo clock. Steam Vents is the expensive card. "
        "Paying for the land and then being unable to cast the banned spell is the trap. Rebuild the shell only "
        "after you have a legal way to put Phoenix in the graveyard and bring it back on the turn you wanted."
    ),
    "token-triumph": (
        "Emmara makes a body when she becomes tapped, so the turn you tap her is the turn you get the token, "
        "and a sweeper after that deletes the body without giving you a card back. Make the tokens again, or "
        "do not attack into the sweeper. This is the cheap version of the plan: the priced total is the whole "
        "precon we could price, and the commander itself had no nonfoil retail on that printing. The combat "
        "clock is a lot of small bodies, not one protected attack."
    ),
    "rebellion-rising": (
        "Neyali's expensive cards are the protection spells, not the token makers. Flawless Maneuver and "
        "Clever Concealment are there so the attack step survives. If you buy the makers and skip those two "
        "instants, you bought the half of the deck one sweeper deletes. Cast the protection on the turn you "
        "attack, not on the turn you are afraid. A token deck with no way to save the turn is a different, worse deck."
    ),
    "blood-rites": (
        "You need a body, a payoff that cares that the body died, and a way to sacrifice it on your timing. "
        "Two of the three is a vampire deck that sometimes throws cards away. Exquisite Blood is the line item "
        "that makes this product expensive, and it is a life-gain card. If you are not assembling that combo, "
        "the sacrifice plan can exist without it and the receipt changes by that one line. Do not sacrifice "
        "your only attacker for a one-point drain unless the drain wins."
    ),
    "revenant-recon": (
        "Necromancy and Animate Dead are enchantments. Reanimate is a sorcery. You need a creature already in "
        "the graveyard on the turn you cast any of them, which is what the one-drops are for. Reanimate on an "
        "empty yard is a blank card. The unfair line is the one you count by hand: enablers in the first four "
        "turns, then one of those three spells. The combat goldfish is the fair plan, the one you fall back to "
        "when the graveyard is hated."
    ),
    "plunder-the-graves": (
        "Meren is the reanimation spell. She has to stay on the battlefield and collect experience, which is a "
        "different failure than Mirko's product, where the famous spells are the cards you paid for. If Meren "
        "dies and stays dead, you are hard-casting the creatures, and the receipt on this printing is those "
        "creatures plus Skullclamp, not Reanimate. Do not buy the one-mana sorcery and pretend you are still "
        "playing the 2015 list."
    ),
    "mind-flayarrrs": (
        "Mindcrank mills when life is lost, so this deck can mill on a turn it did not attack. The goldfish "
        "cannot see that. It attacks, and the winning turn it reports is the creature backup, not the mill clock. "
        "Count cards milled per turn yourself. One Mindcrank does not empty three 99-card libraries. Several "
        "cards in the box had no nonfoil price, so the dollar figure is the priced cards only."
    ),
    "sneak-attack": (
        "Anowon mills when rogues deal combat damage. The attack step and the mill plan are the same turn, "
        "which is why a combat clock is closer to the real plan here than it is for a Mindcrank deck. If you "
        "cannot attack, you are not milling. Do not describe a turn you spent casting a rogue as a mill turn "
        "unless that rogue connected. The commander had no nonfoil retail on the printing in the box."
    ),
    "orzhov-auras": (
        "The creature has to be on the battlefield before the auras do anything. A hand of auras and no creature "
        "is a mulligan even though the curve is full of one-drops. Lurrus, the companion that used to replay "
        "the auras after the creature died, is not a card you can register in Pioneer today. Thoughtseize has "
        "to take the removal spell, not a random card, because the life you pay is the race."
    ),
    "virtue-and-valor": (
        "Ellivere's recursion is the Commander answer to auras in the graveyard. Retether and Hall of Heliod's "
        "Generosity do nothing if you have not put auras in the yard, and they are a large piece of the receipt. "
        "One removal spell on the enchanted creature is the game you built the deck to survive. A second creature, "
        "or a way to get the auras back, is the actual count. Six auras that already kill are enough. Twenty auras "
        "and one creature is a hand that does nothing the turn the creature dies."
    ),
    "arcane-maelstrom": (
        "Deflecting Swat is about half the priced receipt and it is a free counter, not the copy engine. "
        "Twinning Staff is the card that cares that you cast spells. If you wanted Swat, say so and price that "
        "card. If you wanted Kalamax, look at the list without Swat and see whether you still cast two spells "
        "on the turn the commander can copy one. The combat goldfish won nothing here because copying a spell "
        "is not an attack."
    ),
    "prismari-performance": (
        "Zaffai wants a large spell, and the curve already has a pile of them at seven or more. Seething Song "
        "is in the list because those spells cost what they cost. Adding another seven-drop without a ritual "
        "or a land is how the spell stays in your hand. The commander and Veyran had no nonfoil price on these "
        "printings, so the total is the priced cards only. Cast one large spell on the turn you have the mana, "
        "not two small ones, unless you changed commanders."
    ),
}


def narrate(deck: dict, fetched_at: str) -> str:
    note = PLAY_NOTES.get(deck["id"])
    if not note:
        raise SystemExit(f"no play note for {deck['id']}")
    source = deck["source_url"] or "the Wizards product page stored by MTGJSON"
    who = deck_line(deck)
    return "\n\n".join(
        [
            f"### {deck['name']}",
            (
                f"{who} is the {deck['release_date']} {deck['type']} stored as MTGJSON file {deck['mtgjson_file']}. "
                f"Wizards source: {source}."
            ),
            note,
            curve_sentence(deck),
            sources_sentence(deck),
            cost_sentence(deck, fetched_at),
            fish_sentence(deck),
            illegal_sentence(deck, fetched_at),
        ]
    )


GUIDES: list[dict] = [
    {
        "slug": "should-you-play-aggro",
        "title": "Should You Play an Aggro Deck in MTG?",
        "description": "Should you play aggro in Magic: The Gathering? A Pioneer burn list goldfishes turn 5.96 for $31.38, and the curve shows when that race is the wrong plan.",
        "date": "2026-11-01",
        "keywords": ["should I play aggro mtg", "aggro deck guide", "pioneer burn deck cost", "mtg goldfish clock"],
        "related": ["mtg-midrange-deck-guide", "should-you-play-control", "mtg-burn-deck-guide", "mtg-deck-archetypes-explained"],
        "decks": ["mono-red-burn"],
        "lens": "aggro",
        "cta_format": "pioneer",
        "cta_brief": "Mono-red burn",
        "thesis": [
            "Play aggro when you want the game decided by your mana curve instead of by a late-game engine you have not drawn yet. In Magic: The Gathering (MTG), that means spending the early turns turning cheap cards into damage, and accepting that the opponent's best cards arrive too late to matter. The decision on this page is the burn race: one official Pioneer list, one clock, one price. A creature deck that still wants to be attacking once four-drops are on the table is a different yes-or-no, and it lives on the [midrange page](/blog/mtg-midrange-deck-guide).",
            "The useful test is the goldfish clock next to the price of this product, not a tier list. The 2021 Challenger burn list is a turn-six race in a vacuum at a product-printing total around the price of one format staple. If you cannot stand losing to a sweeper, or you want the game to keep going after turn eight, this is the wrong tool even when that clock looks impressive. Do not borrow a slower creature deck's land count and call the result burn.",
            "Aggro fails in a specific way. It runs out of cards. Every burn spell pointed at a creature is a burn spell that did not reduce the opponent's life total. The sideboard and the mulligan are part of the deck: a hand with one land is not a hand, and a hand with five lands is not a race. The [burn deck guide](/blog/mtg-burn-deck-guide) covers the play patterns. This page is the decision to race at all.",
        ],
        "table": [
            ["You want the game over by turn six or seven", "The burn product's goldfish clock is the measurement below", "A ramp or control list that has not cast its payoff yet"],
            ["Your budget is around thirty dollars for a 75", "The 2021 Challenger burn list is priced on its own printings in the deck block", "A deck whose lands are the expensive cards"],
            ["You hate losing to one sweeper", "Spell damage does not die to the sweeper", "A creature deck, which the midrange page measures"],
            ["You want to play the long game on purpose", "This is the wrong plan", "Control, which is trying not to race"],
        ],
        "mistakes": [
            "Treating every red deck as burn. A creature deck with a four- and five-mana top end is a different clock and a different receipt. That comparison is the midrange guide, not a second copy of this list.",
            "Pointing every burn spell at a creature. The goldfish assumes the spells hit the opponent. A real game where half the bolts kill creatures is a different, slower deck.",
            "Ignoring the land count. This burn list plays 20 lands under a curve of one-drops. Adding a five-drop because it is powerful pulls the curve off the clock you just measured.",
            "Buying the most expensive printing of a basic and treating that number as the only way to build the deck. The total below is the product's printings.",
            "Reading a perfect goldfish record as a match win rate. Nothing in these games cast a counterspell or a board sweeper.",
        ],
        "faq": [
            ("Is aggro the same as burn?", "Burn is the aggro deck that deals most of its damage with spells. A red creature deck that deals most of its damage by attacking is a different plan, with its own land count, and it is written up on the midrange page so this page can stay about the race."),
            ("How many lands does this burn list play?", "Twenty, under a curve that is mostly one-drops. Copy that curve, then the land count. A deck that curves to five needs a different number, and it is not this deck."),
            ("Can I play this burn list in Pioneer today?", "The Scryfall bulk used for this page lists the burn cards as Pioneer-legal on the fetch date in the deck block. Legality changes. Check the ban list before you register the deck."),
            ("Why is the goldfish slower than the turn-four burn I have heard about?", "This is the 2021 Challenger product, not a tuned Modern list with Lightning Bolt. The measured average winning turn is on the deck block: 120 games, seed 1729."),
        ],
    },
    {
        "slug": "should-you-play-control",
        "title": "Should You Play a Control Deck in MTG?",
        "description": "Should you play control in Magic: The Gathering? The Pioneer Dimir Challenger deck costs $43.07 and won 0 of 120 goldfish games, which is the point.",
        "date": "2026-11-01",
        "keywords": ["should I play control mtg", "dimir control pioneer", "control deck goldfish", "mtg permission deck"],
        "related": ["mtg-control-deck-guide", "should-you-play-aggro", "mtg-deck-archetypes-explained", "sideboarding-101"],
        "decks": ["dimir-control"],
        "lens": "control",
        "cta_format": "pioneer",
        "cta_brief": "Dimir control",
        "thesis": [
            "Play control when you are willing to lose the early turns on purpose and win the game that happens after your opponent is out of gas. In Magic: The Gathering (MTG), a permission deck trades cards and life total now for a later turn where your answers have cleared the board and your card draw has replaced your hand. If that sentence sounds miserable, do not play this deck. The official Dimir Challenger list is the cleanest way to see the choice: it does not kill a goldfish, because a deck of counters and removal is not trying to.",
            "Say yes only if you want that wait. The 2022 product is a 60-card permission deck whose top end starts at six mana, and a large share of the receipt is a shock land plus two other cards rather than a pile of finishers. If your budget is the finishers and your mana is a stack of basics, you do not have this list. A commander product with the word control on the box can be a spell-discount deck instead. That is a different question, answered on the [how-to-play page](/blog/mtg-control-deck-guide), and it should not talk you into sleeving permission.",
            "This page is the yes-or-no. The [deck archetypes overview](/blog/mtg-deck-archetypes-explained) is the map of the other plans. If you already know you want the long game, the measurement below is what the official permission list actually costs and how empty the early turns are.",
        ],
        "table": [
            ["You enjoy the game after turn eight", "The Dimir list's goldfish is a loss, because the kill is not the early plan", "Burn, which is over on turn six if you stumble"],
            ["You want to attack with two-drops", "This is the wrong deck", "Spirits or Humans, which are built to attack"],
            ["A shock land is an acceptable chunk of the budget", "Watery Grave leads the Dimir receipt", "A mono-color aggro list whose lands are basics"],
            ["You wanted a commander that makes spells cheaper", "That is not this list", "The Mizzix how-to, which is a different deck"],
        ],
        "mistakes": [
            "Judging this permission list by its goldfish win rate. A zero is the measurement working. The deck is not trying to race.",
            "Buying it because a commander precon used the word control. Spell discount and permission are different jobs. The how-to page is the other one.",
            "Cutting lands so you can add more counterspells. The six-drops are why the early turns exist, and they need the land count printed under them.",
            "Spending the answer on the first creature. You lose when you are down a card and still facing a board. The early life total is a resource.",
            "Treating the 2022 product as this weekend's Pioneer metagame. It is an official list with a fetch date. It shows the shape, not the current tournament.",
        ],
        "faq": [
            ("Why did this list never win a goldfish game?", "The simulator deals damage with creatures and direct-damage spells. A permission deck that plans to win with a late finisher after answering everything does not do that inside the goldfish's turn limit. The deck block has the game count and the seed."),
            ("Is every blue deck this kind of control?", "No. Permission answers the opponent's spell. A cost reducer wants your own spell to resolve for less. If the commander is the discount, you are on the how-to page, not this one."),
            ("How much of the price is the mana?", "Watery Grave is the largest line, and the top three nonbasic names are the share printed in the deck block. The rest is comparatively cheap answers."),
            ("Does failing the goldfish mean the deck is bad?", "It means the deck does not win a solitaire race. Judge it by whether you want the long game, not by that clock."),
        ],
    },
    {
        "slug": "should-you-play-ramp",
        "title": "Should You Play a Ramp Deck in MTG?",
        "description": "Should you play ramp in Magic: The Gathering? Pantlaza's precon costs $135.24 with 39 lands and goldfishes turn 11.1. Here is when that mana is worth it.",
        "date": "2026-11-01",
        "keywords": ["should I play ramp mtg", "pantlaza precon cost", "commander ramp land count", "mtg ramp deck"],
        "related": ["mtg-ramp-deck-guide", "should-you-play-aggro", "how-to-build-your-first-commander-deck", "mtg-deck-archetypes-explained"],
        "decks": ["veloci-ramp-tor"],
        "lens": "ramp",
        "cta_format": "commander",
        "cta_brief": "Dinosaur ramp",
        "thesis": [
            "Play ramp when the cards you actually want to cast cost more than the turn you want to cast them on, and you are willing to spend the early turns finding mana instead of dealing damage. In Magic: The Gathering (MTG), ramp is not a win condition. It is how you reach a win condition a fair curve cannot cast on time. If your payoff costs three, you do not need this plan. You need a cheaper curve.",
            "The decision on this page is Pantlaza's dinosaur precon, Veloci-Ramp-Tor. The receipt is a handful of nonbasic spells, led by Akroma's Will, not a pile of basics. You are buying the turn the dinosaurs attack, and the protection spell that keeps that turn. A landfall deck that treats the lands themselves as the ramp is a different purchase. How many of those lands to play is the [count guide](/blog/mtg-ramp-deck-guide). This page is whether you want the dinosaur plan at all.",
            "The goldfish wins by attacking with the creatures the mana eventually casts. It is not evidence that you will have seven mana on turn four every game. If your version of this list plays far fewer lands than the product, you are playing a dinosaur deck that misses its land drops. If you would rather end the game before the big spell, the [aggro decision](/blog/should-you-play-aggro) is the other side, and the [deck archetypes overview](/blog/mtg-deck-archetypes-explained) is the map.",
        ],
        "table": [
            ["Your payoff costs six or more", "Pantlaza's curve still has cards at 7 or more", "An aggro deck, whose curve ends at three"],
            ["You want to attack on turn two", "The early turns are mana, not damage", "Burn or Spirits"],
            ["One instant is a large share of the budget", "Akroma's Will leads the nonbasic receipt", "A deck whose money is the lands, which is the other guide"],
            ["You are about to cut lands to add more dinosaurs", "The printed land count is the floor", "A short-land list that cannot cast the top end"],
        ],
        "mistakes": [
            "Adding ramp spells and cutting lands in the same edit. The land count is the floor under the dinosaurs. The product is already in the high 30s for a 99-card deck.",
            "Judging the plan by a turn-four kill. The mana is for a large creature. The clock on the deck block is a creature race against one 40-life opponent, and it is not turn four.",
            "Treating every green deck as ramp. A curve of two-drops is an aggro or midrange deck that happens to be green.",
            "Pricing the deck off a single average. The top three nonbasics are the share in the deck block. The fourth card is a different conversation.",
            "Sleeving a token that came in the box as if it were one of the 99. The list below is the cards. A token card in the product is not a Commander-legal spell you copy into a new deck.",
        ],
        "faq": [
            ("How many lands does Pantlaza's deck play?", "The land count is in the deck block, in the 99, with the commander separate. That is the published floor for this payoff curve, not a suggestion to cut lands."),
            ("Is this a ramp deck or a dinosaur deck?", "It is both. The top of the curve is the dinosaurs. The lands and the three-mana ramp are how you cast them. If you cut the mana, you kept the creatures and lost the plan."),
            ("Why does one spell cost so much of the product?", "Akroma's Will is the protection for the turn you attack. It is not a ramp spell. Swapping it for a cheaper instant does not keep that turn."),
            ("Does the goldfish mean I win on that turn at a real table?", "It means the average winning solitaire game against one 40-life opponent ended then. A four-player table is a different game. The number is a speed ceiling for the creature plan."),
        ],
    },
    {
        "slug": "mtg-control-deck-guide",
        "title": "How Do You Pilot Mizzix, the Deck Named Control?",
        "description": "How do you pilot Mizzix of the Izmagnus in Magic: The Gathering? The Seize Control precon discounts your spells. Cast the four-drop; do not hold up a counter.",
        "date": "2026-11-01",
        "keywords": ["how to play mizzix mtg", "seize control precon", "spell discount commander", "mizzix experience counters"],
        "related": ["should-you-play-control", "spellslinger-deck-guide", "sideboarding-101", "card-advantage-explained"],
        "decks": ["seize-control"],
        "lens": "control",
        "cta_format": "commander",
        "cta_brief": "Mizzix spells",
        "thesis": [
            "You pilot Mizzix by getting the experience counters onto the commander and then casting the spell those counters make cheaper. In Magic: The Gathering (MTG), Seize Control was printed with the word control on the box. The turns you play are not the turns of a permission deck. The [yes-or-no for permission](/blog/should-you-play-control) is a Pioneer list that answers threats. This page is the Commander list that wants your own spell to resolve.",
            "The curve peaks at four and five mana because the commander is the discount. The turn Mizzix comes down, you are not holding up one blue mana and passing. You cast the spell the counters just made castable. A hand of interaction and no spell you actually want to resolve cheaper is a mulligan, even when every card says instant. The 99 has the land count of a commander deck, not of a 60-card list. Importing a small-deck mana base strands the five-drop the discount was for.",
            "Practice is which spell you cast once the counters are on, not how fast you can kill a goldfish. The solitaire games lose because nothing is attacking. That loss is a check that you are looking at the right scoreboard. The [sideboarding guide](/blog/sideboarding-101) is for the 60-card permission deck between games. Mizzix does not sideboard. You sequence.",
            "A concrete turn: you have Mizzix and two experience counters, six lands, and a five-mana spell in hand. The spell now costs three. Cast it. If an opponent has mana open, you decide whether the counter in your hand protects that spell or answers theirs, and you make that choice before you tap out. Waiting for a perfect seven-card lock is how the discount expires with the commander dead. The list below is the spell pile Wizards printed for that sequence. Read the curve, then name the spell you are excited to cast cheaper. If you cannot name it, you wanted permission instead, and that deck is the other page.",
        ],
        "table": [
            ["The commander is in play with counters", "Cast the four- or five-mana spell the curve is full of", "Holding up a one-mana answer and passing"],
            ["Your hand is counters and no payoff", "Mulligan", "A permission hand, which is a different deck"],
            ["You imported a 60-card land count", "Put the lands back", "The 99 needs the commander-deck count printed below"],
            ["You wanted to say no for twelve turns", "Wrong product", "The Pioneer permission decision"],
        ],
        "mistakes": [
            "Playing Mizzix like a draw-go permission deck. The discount does nothing if you never cast the spell it cheapens.",
            "Cutting lands because the spells cost less once the commander is online. They do not cost less before that, and a missed land drop is a turn without counters.",
            "Adding creatures so the goldfish has something to attack with. You have stopped playing the spell deck.",
            "Treating every counter in the list as an answer to the opponent. Some of them protect the spell you are trying to resolve cheaper.",
            "Reading the product name as a format ruling. The list below is what Wizards printed. The permission shape is the other guide.",
        ],
        "faq": [
            ("What do I do the turn Mizzix resolves?", "Put the experience counter to work. Cast a spell that the new cost makes reasonable. Passing with the discount unused is the turn the deck failed."),
            ("Why does the goldfish lose?", "It attacks. This list wins by casting spells for less than printed. A combat record of zero is the tool refusing to pretend otherwise. The deck block has the game count."),
            ("How many lands does this commander deck play?", "The count is in the deck block, and it is a 99-card number. Do not copy a 60-card permission deck's land count into this list."),
            ("Is this the same deck as Dimir control?", "No. Dimir answers an opponent's spell and wins later. Mizzix wants your spell to resolve. They share a marketing word and nothing you do on the turn."),
        ],
    },
    {
        "slug": "mtg-midrange-deck-guide",
        "title": "Is Midrange the Right MTG Deck for You?",
        "description": "Is midrange right for you in Magic: The Gathering? Gruul Stompy goldfishes turn 7.02 for $53.38. Orzhov Humans is turn 8.27 and half its price is three cards.",
        "date": "2026-11-11",
        "keywords": ["midrange deck mtg", "gruul stompy challenger", "orzhov humans pioneer", "midrange vs aggro"],
        "related": ["should-you-play-aggro", "mtg-control-deck-guide", "mtg-burn-deck-guide", "mtg-deck-archetypes-explained"],
        "decks": ["gruul-stompy", "orzhov-humans"],
        "lens": "midrange",
        "cta_format": "pioneer",
        "cta_brief": "Gruul midrange",
        "thesis": [
            "Midrange is the right deck when you want your cards to be better than theirs if the game reaches the middle turns, and you accept that a true aggro deck will be ahead before you get there. In Magic: The Gathering (MTG), midrange wins by having the larger creature, the two-for-one, or the planeswalker that an aggro deck cannot afford to play. It loses when the game ends before that card matters, or when a control deck answers the one threat you tapped out for.",
            "The two Pioneer Challenger products here show the spread inside the word. Gruul Stompy's nonland curve runs from one mana out to five, it plays 25 lands, and the goldfish's average win is turn 7.02. That is a turn slower than the burn list on the aggro page, which is exactly the turn the bigger creatures are buying. Orzhov Humans is 16 one-drops and 22 two-drops and nothing higher in the nonland curve. Its goldfish win is turn 8.27, and it wins fewer of the solitaire games. A deck of two-drops that does not kill quickly is not midrange. It is a small deck that ran out of threats. Call Humans what the curve says it is: a low-curve creature deck whose expensive cards are lands.",
            "Price is the other half of the decision. Gruul's $53.38 product total has its top three nonbasics, two lands and Chandra, at 43.1%. Humans puts 49.6% of $47.38 into three lands: a shock, a man-land, and a fast land. If you came for midrange creatures and your money went into the mana base, that is the real purchase. The [aggro decision](/blog/should-you-play-aggro) is the comparison when the clock is the thing you care about.",
        ],
        "table": [
            ["You want a threat that costs four or five", "Gruul's curve includes both", "Humans, which stops at two mana"],
            ["You want the cheapest possible manabase", "Neither of these products. Their top costs are lands", "A mono-red basic-land burn list"],
            ["The game often ends on turn five in your group", "You will not cast the five-drop", "Aggro, which the aggro page measures on the burn product"],
            ["You want to answer a creature and then play a bigger one", "That is the midrange turn", "Control, which would rather not play the bigger creature yet"],
        ],
        "mistakes": [
            "Calling a deck midrange because it is not aggro and not control. Humans' curve is 38 nonlands at one and two mana. That is a low curve with an expensive mana base.",
            "Adding a six-drop to Gruul because midrange means big. The product's curve already reaches five, on 25 lands. A six-drop needs a land count you have not added.",
            "Spending Chandra on a one-drop in the goldfish sense of wasting the expensive card. Chandra is one of the three cards that are 43% of the Gruul budget. She has to win the midgame, not trade for a two-drop.",
            "Assuming 25 lands is greedy. The curve goes to five. Burn plays 20 lands because its curve does not.",
            "Copying the 2022 list into a tournament without a ban-list check. The Scryfall bulk said these cards were Pioneer-legal on 2026-11-01. Confirm the day you play.",
        ],
        "faq": [
            ("What is the difference between midrange and aggro?", "About a turn and a land count. Gruul goldfishes turn 7.02 on 25 lands with cards up to five mana. Burn is the aggro page, and it is a shorter race."),
            ("Why are the expensive cards lands?", "Because the creatures in a Challenger product are often reprints, and the shock lands are not. Humans' top three line items are all lands, 49.6% of the product price."),
            ("How do I play the midgame?", "Trade when your card is the worse creature, and stop trading when your card is the one that will win the next three turns. Gruul's four- and five-drops are those cards. Humans does not have them."),
            ("Is Chandra worth the price on this list?", "She is $7.36 of the Gruul product as a line cost in the file, one of the three names that make up 43.1%. A cheaper planeswalker from another product does not do her job. Pay for her only if the midgame plan is the plan you want."),
        ],
    },
    {
        "slug": "mtg-combo-decks-explained",
        "title": "How Do You Know a Combo Deck Is Worth Building?",
        "description": "Is a combo deck worth building in Magic: The Gathering? Lotus Field, a $55.97 Pioneer product, won 0 of 120 goldfish games. Here is what that measurement means.",
        "date": "2026-11-19",
        "keywords": ["combo deck mtg", "lotus field combo pioneer", "how combo decks win", "mtg combo goldfish"],
        "related": ["should-you-play-control", "mtg-tempo-decks-explained", "card-advantage-explained", "mtg-deck-archetypes-explained"],
        "decks": ["lotus-field"],
        "lens": "combo",
        "cta_format": "pioneer",
        "cta_brief": "Lotus Field combo",
        "thesis": [
            "A combo deck is worth building when you can name the cards that win the game and you would rather lose to disruption than win a combat race. In Magic: The Gathering (MTG), a combo is a small set of cards that ends the game, or comes close, when they resolve together. Everything else in the deck finds those cards or keeps the opponent from stopping them. If you cannot point at the pile, you do not have a combo deck. You have a pile of cards that are good in the abstract.",
            "Lotus Field Combo, the 2021 Pioneer Challenger product, is a named combo deck with a public list. Its goldfish record is the teaching tool: zero wins in 120 games. The simulator never put Lotus Field, a payoff, and the mana together as a plan. It attacked with whatever creatures existed and then the game ended. That is the right failure. A combo deck that goldfishes like burn is usually just burn. Use the zero as a check that you understand the deck does not win by combat, then practice the actual line, which this simulator will not play for you.",
            "The money tells you what the combo costs as cardboard. The product total is $55.97 on its printings. The top three nonbasic names are 46.8% of that, led by Lotus Field itself. You are buying the land the deck is named for, plus two expensive spells, and a pile of cheaper pieces around them. If Lotus Field is the card you cannot afford, you cannot play this list's mana. A cheaper same-type spell from another official product is not a replacement for the land. The [control decision](/blog/should-you-play-control) is the other non-race plan, and it fails the goldfish for a different reason: answers, not a combo.",
        ],
        "table": [
            ["You can name the winning cards", "Lotus Field plus the payoffs in the product list", "A good-stuff deck with no named pile"],
            ["You want a turn-six combat kill", "This list won none of 120 goldfish games", "The burn product on the aggro page"],
            ["Half the budget can sit in three cards", "46.8% of $55.97 is the top three nonbasics", "A deck whose price is spread across twenty cheap spells"],
            ["You need the simulator to play the combo", "It will not. The zero is the evidence", "Practice the line by hand or in the builder"],
        ],
        "mistakes": [
            "Treating a 0% goldfish win rate as a broken deck. The metric does not assemble Lotus Field. It was not built to.",
            "Replacing Lotus Field with a cheaper land because some other land in another product is cheap. The deck is named after the land. The mana is the combo.",
            "Adding creatures so the goldfish has something to attack with. You have turned a combo deck into a bad midrange deck.",
            "Forgetting the deck is several colors. The source count is not a mono-color basic count. The expensive lands are doing a job.",
            "Registering the 2021 product at a tournament without checking bans. The bulk file's legality is dated 2026-11-01.",
        ],
        "faq": [
            ("What is the combo in the Lotus Field product?", "The deck is built to make large amounts of mana with Lotus Field and then cast a payoff that ends the game, including Approach of the Second Sun in the published list. Read the list in the deck block rather than a paraphrase of the line."),
            ("Why can't the goldfish win with it?", "The goldfish casts spells and attacks. It does not sequence a mana engine into a two-card kill. 0 wins in 120 games, seed 1729, is that limitation measured on this exact list."),
            ("Is combo the same as control?", "No. Control's zero comes from answering threats and never attacking. Combo's zero comes from winning with a pile the attacker-simulator does not play. The decks feel different in a real game: one says no, the other tries to go off."),
            ("How much of the price is Lotus Field?", "It is the top line item on the product printing. Together with the next two nonbasic names it is 46.8% of the $55.97 total. The rest of the deck is the cheaper shell around that core."),
        ],
    },
    {
        "slug": "mtg-tempo-decks-explained",
        "title": "What Does a Tempo Deck Trade Away in MTG?",
        "description": "What does a tempo deck give up in Magic: The Gathering? Spirits goldfishes turn 6.62 for $22.40. Phoenix is turn 9.78, and Expressive Iteration is not Pioneer-legal.",
        "date": "2026-11-27",
        "keywords": ["tempo deck mtg", "azorius spirits pioneer", "izzet phoenix ban", "tempo vs aggro"],
        "related": ["should-you-play-aggro", "mtg-combo-decks-explained", "mtg-burn-deck-guide", "sideboarding-101"],
        "decks": ["azorius-spirits", "izzet-phoenix"],
        "lens": "tempo",
        "cta_format": "pioneer",
        "cta_brief": "Azorius spirits",
        "thesis": [
            "A tempo deck trades raw damage for the right to decide what resolves. In Magic: The Gathering (MTG), tempo means spending your mana and your cards so that the opponent's expensive spell resolves a turn too late, or not at all, while your small creatures are already attacking. You give up the ability to win a long game of card advantage. If the game reaches the point where both players have seven lands and full hands, the tempo deck is usually the one that is behind.",
            "Azorius Spirits, the 2021 Challenger product, is the clean version of that trade. Twenty-two of its nonlands cost two mana. The goldfish average win is turn 6.62, close to burn, on a $22.40 product total that is the cheapest list in this set of guides. The expensive cards are the creatures, not a shock land. You can see the whole plan: small fliers, a little disruption, a clock that does not need a six-drop.",
            "Izzet Phoenix is the cautionary official list. Its goldfish win rate is only 56.7%, and the average winning game is turn 9.78, which is not a tempo clock. Expressive Iteration is not legal today per the Scryfall bulk of 2026-11-01. The product was a real Challenger deck in 2022. It is not a list you can copy into a tournament now. Tempo decks also rot when a key cantrip is banned, because the deck was the cantrip plus the threat, not the threat alone. The [aggro page](/blog/should-you-play-aggro) is the comparison when you want damage instead of disruption.",
        ],
        "table": [
            ["Small creatures plus cheap interaction", "Spirits: 22 two-drops, turn 6.62, $22.40", "A control list that does not attack"],
            ["A cantrip the format later banned", "Do not register Phoenix as printed", "Expressive Iteration is not Pioneer-legal on the 2026-11-01 bulk"],
            ["You want the long game", "Tempo gives that up on purpose", "Control or a real midrange top end"],
            ["The mana base is the budget", "Spirits spends its money on creatures", "Phoenix's top cost is Steam Vents"],
        ],
        "mistakes": [
            "Calling Phoenix a current Pioneer deck. The ban is in the Scryfall bulk. The goldfish was run on the printed list anyway, bans included, so the clock is a historical measurement.",
            "Playing tempo into a board stall. The two-drops do not win a game of five-drops. You needed the game to end while they were still large enough.",
            "Cutting the interaction to add more creatures, then wondering why the deck became a worse aggro deck. The disruption is the reason the small creatures get to attack.",
            "Paying Phoenix prices for a banned cantrip shell. Steam Vents is the top line item. The card you cannot cast is not worth the land.",
            "Expecting every goldfish game to win. Spirits won 96.7%. Phoenix won 56.7%. The second number is a deck that does not reliably turn sideways.",
        ],
        "faq": [
            ("What does tempo mean if it is not just aggro?", "Aggro spends every card on damage. Tempo spends some cards to slow the opponent's expensive plays so the small creatures stay ahead. Spirits' curve is the creature half of that. The disruption is the other half."),
            ("Can I play the Phoenix Challenger deck in Pioneer?", "Not as printed. Expressive Iteration is not legal today per the Scryfall bulk of 2026-11-01. Check the current ban list before you rebuild the shell."),
            ("Why is Spirits so much cheaper?", "The product-printing total is $22.40, and the top costs are creatures at a few dollars, not one expensive land. Phoenix is $35.25 with Steam Vents alone at $10.77."),
            ("Is a turn-9 goldfish still tempo?", "No. Turn 9.78 for Phoenix says the printed list does not present a fast combat clock once the simulator is just attacking. Spirits at 6.62 does."),
        ],
    },
    {
        "slug": "mtg-ramp-deck-guide",
        "title": "How Many Lands Does a Landfall Deck Actually Need?",
        "description": "How many lands does a landfall deck need in Magic: The Gathering? Obuun's official list plays 37 lands in the 99, because the land drop is the ramp spell.",
        "date": "2026-11-01",
        "keywords": ["how many lands commander", "obuun lands wrath", "landfall ramp count", "mana creature vs land"],
        "related": ["should-you-play-ramp", "should-you-play-aggro", "how-to-build-your-first-commander-deck", "mtg-deck-archetypes-explained"],
        "decks": ["lands-wrath"],
        "lens": "ramp",
        "cta_format": "commander",
        "cta_brief": "Landfall ramp",
        "thesis": [
            "Count lands before you count ramp spells. In Magic: The Gathering (MTG), the usual failure is a hand of three-mana land searchers and two lands: the searchers never resolve, and the six-drop was never the card that was stuck. A landfall deck makes this stricter. The land entering the battlefield is the effect, so a mana creature that dies to a two-drop is not a substitute for the land.",
            "Land's Wrath, Obuun, Mul Daya Ancestor, is the official list for that count. The curve is thick at three and four, which is where the land search lives, and the land total in the 99 is the plan rather than a support package under a dinosaur. Whether you want a big-mana creature deck at all, dinosaurs included, is the [yes-or-no page](/blog/should-you-play-ramp). This page is how you count.",
            "Say the number out loud before you cut anything. If the payoff triggers when a land enters, cutting a land to add another payoff removes the trigger. If the payoff only needed colored mana, a creature that taps for mana might belong, and you still do not cut the land that casts it. The goldfish on this list is a creature clock against one opponent. It will not tell you how often you missed the land drop. Count that by hand.",
        ],
        "table": [
            ["The payoff triggers on a land drop", "Keep the lands printed in the 99", "A mana dork that dies before it taps"],
            ["The payoff costs three and does not care about lands", "You may not need a ramp package", "Cutting lands anyway, out of habit"],
            ["You want another landfall creature", "Take it from a nonland slot", "Taking it from the land count"],
            ["You are pricing the product's basics", "That receipt is the printing in the box", "The price of a random basic at the shop"],
        ],
        "mistakes": [
            "Cutting lands to add ramp. The ramp is in addition to lands. This product is already in the high 30s, and those lands are the triggers.",
            "Calling a mana creature a land when you check your colors. The source count can be higher than the land count because creatures that tap for mana are included. Say sources when that is what you counted.",
            "Treating a mana rock and a land search as the same card. One taps for mana after you have already spent mana. The other puts a land onto the battlefield, which is what Obuun wants.",
            "Expecting the solitaire clock to prove you ramped. It reports when creatures dealt enough damage. It does not report your mana on turn five.",
            "Blaming the whole color for the receipt. Look at which names are the top three nonbasics in the deck block. The land-search creatures under them are not that line.",
        ],
        "faq": [
            ("Is 37 lands too many for Obuun?", "Not when the land drop is the trigger. Cut lands only if you also cut the payoffs that wanted the land to enter. The deck block has the printed count."),
            ("What counts as ramp here?", "A card that leaves a land on the battlefield, or that adds mana beyond your land drop. A card that draws you a land is smoother. It does not put you ahead, and it does not trigger landfall until you play the land."),
            ("Why is the commander missing from the dollar total?", "Obuun had no nonfoil retail price on the printing in the product file. The total is priced cards only. The deck block names every unpriced card."),
            ("Can I copy Pantlaza's land count into this deck?", "You can compare the two after you have counted this one. The dinosaur list is a different payoff on the decision page. Do not average the two numbers and call it a rule."),
        ],
    },
    {
        "slug": "mtg-tokens-deck-guide",
        "title": "When Do MTG Token Decks Fall Apart?",
        "description": "When do token decks fall apart in Magic: The Gathering? Emmara's precon is $36.09 and turn 10.90. Neyali's is $131.72, and two protection spells are $32.76 of it.",
        "date": "2026-12-11",
        "keywords": ["token deck mtg", "emmara precon price", "neyali tokens", "when token decks fail"],
        "related": ["should-you-play-aggro", "mtg-ramp-deck-guide", "mtg-tribal-decks-guide", "mtg-deck-archetypes-explained"],
        "decks": ["token-triumph", "rebellion-rising"],
        "lens": "tokens",
        "cta_format": "commander",
        "cta_brief": "Token deck",
        "thesis": [
            "A token deck falls apart when the card that turns bodies into damage is answered and the tokens were never cards you can replay. In Magic: The Gathering (MTG), tokens are permanents the game created. They did not come from your hand, so a sweeper does not just kill creatures, it deletes mana you spent on cards that are now gone and bodies you cannot recast. The deck works when it can make the tokens again, or when it can protect the turn it attacks. It does not work when every token-maker costs four mana and you have one of them.",
            "The two official Commander decks show the budget split inside one archetype. Token Triumph, Emmara, Soul of the Accord, prices at $36.09 on the printings we could price, and it goldfishes an average win on turn 10.90 with a 95.8% solitaire win rate. That is a combat clock from a lot of small bodies. Rebellion Rising, Neyali, costs $131.72. Flawless Maneuver and Clever Concealment alone are $21.13 and $11.63. The expensive cards are not the token-makers. They are the spells that keep the tokens alive for one attack. If you buy the token-makers and skip the protection, you bought the half of the deck a sweeper deletes.",
            "Both lists play 39 and 38 lands. A token deck still needs to cast the makers on curve. The [tribal guide](/blog/mtg-tribal-decks-guide) covers overlapping creature types. Tokens are not a tribe. They are a way of getting more bodies than you drew, and they die all at once.",
        ],
        "table": [
            ["You expect a sweeper most games", "Neyali spends real money on protection spells", "A token deck with no way to save the turn"],
            ["You want the cheap version of the plan", "Emmara's priced total is $36.09", "Neyali at $131.72, driven by two instants"],
            ["You want one giant creature", "Tokens win by having many bodies", "Voltron, which bets on one creature"],
            ["The maker costs more than the attack step is worth", "Stop adding makers and add a way to use the ones you have", "An anthem or a protection spell, which is what the expensive Neyali cards are"],
        ],
        "mistakes": [
            "Building tokens with no anthem and no protection, then losing to one sweeper and calling the archetype weak. Neyali's receipt is the protection.",
            "Counting tokens as card advantage without a way to make more. The first wave dying is a loss of mana, not a loss of cards, and you still need the next maker.",
            "Cutting lands because the tokens are free. The makers are not free. These products play 38 and 39 lands.",
            "Comparing the two precons as the same purchase. One is a $36 combat deck. The other is a $132 deck whose top costs are instants.",
            "Reading the goldfish as the token plan's resilience. The sim never casts a sweeper. The 96% win rate is a solitaire attack step.",
        ],
        "faq": [
            ("Are tokens card advantage?", "Only if you spent less card-for-card than the opponent spends answering them, or if one card keeps making tokens. A single 1/1 that dies to a shock was not advantage."),
            ("Why is the Neyali deck so much more expensive?", "Flawless Maneuver is $21.13 and Clever Concealment is $11.63 on the product printings, inside a $131.72 total. Emmara's whole priced list is $36.09. The archetype is not the price. The specific cards are."),
            ("How fast do these decks kill a goldfish?", "Turn 10.90 for Emmara and turn 10.17 for Neyali, over 120 games against one opponent at 40 life, seed 1729. That is combat damage, not an infinite token combo."),
            ("Do I need a sacrifice outlet?", "Not for these two lists to function as combat decks. A sacrifice outlet is a different plan: you want the tokens to die. That is the aristocrats page, not this one."),
        ],
    },
    {
        "slug": "aristocrats-sacrifice-deck-guide",
        "title": "What Has to Be True for a Sacrifice Deck to Work?",
        "description": "What has to be true for a sacrifice deck in Magic: The Gathering? Clavileno's precon is $157.27, and Exquisite Blood alone is $41.93 of that receipt.",
        "date": "2026-12-19",
        "keywords": ["aristocrats mtg", "sacrifice deck guide", "clavileño precon price", "exquisite blood commander"],
        "related": ["mtg-tokens-deck-guide", "reanimator-deck-guide", "mtg-deck-archetypes-explained", "card-advantage-explained"],
        "decks": ["blood-rites"],
        "lens": "sacrifice",
        "cta_format": "commander",
        "cta_brief": "Vampire aristocrats",
        "thesis": [
            "A sacrifice deck works only when three jobs are in the list at once: something that creates a body, something that wants that body to die, and something you can sacrifice at instant speed so the death is your idea. In Magic: The Gathering (MTG), aristocrats is the name for that loop. Miss one of the three and you have a normal creature deck that sometimes throws its own cards away. The payoff is not the sacrifice. The payoff is the trigger that fires because you sacrificed.",
            "Blood Rites, the Clavileno vampire precon from Lost Caverns of Ixalan, is the official list on the table. It prices at $157.27 on the printings with a TCGplayer nonfoil number. Exquisite Blood is $41.93 of that by itself. Charismatic Conqueror is another $25.75. The top three nonbasic names are 47.7% of the product. This is not a deck whose price is a smooth average of vampires. It is a deck whose price is two cards and a pile of cheaper vampires around them. If you came for the sacrifice plan and your budget is Exquisite Blood, you are buying a life-gain combo piece that the rest of the deck may not be built to assemble every game. Read the card, then decide if that is the plan.",
            "The goldfish does win, on turn 10.70 on average, 91.7% of 120 games, by attacking. It does not sacrifice creatures for value. A combat clock on a sacrifice deck means the creatures are large enough to win without the loop. That is a backup plan, not proof the aristocrats engine is fast. The [token guide](/blog/mtg-tokens-deck-guide) is what the bodies look like before you start sacrificing them.",
        ],
        "table": [
            ["You have makers, payoffs, and a sacrifice outlet", "The deck can function when one creature dies", "Blood Rites is the published vampire version"],
            ["One card is a quarter of the budget", "Exquisite Blood is $41.93 of $157.27", "Decide if that card is the plan or an add-on"],
            ["You only have the payoff", "You will have nothing to sacrifice", "Add bodies before you add a second payoff"],
            ["You want the loop to show up in a goldfish clock", "It will not. The clock is combat", "Turn 10.70 is creatures attacking, not a drain loop"],
        ],
        "mistakes": [
            "Playing four payoffs and four creatures. The bodies run out and the payoffs sit on the table doing nothing.",
            "Sacrificing your only attacker because a trigger said to. The combat clock on this product is real. Do not delete it for a one-point drain unless the drain wins.",
            "Treating Exquisite Blood as a required aristocrats card. It is the price center of this product. It is a life-gain card with a combo reputation. The sacrifice plan can exist without it, and the receipt changes completely.",
            "Forgetting the deck is white and black. The source count has to support both colors. A mono-black sacrifice package inside a white-black deck still needs white mana for the white vampires.",
            "Expecting the goldfish to demonstrate the engine. 120 games of attacking do not fire a sacrifice trigger on purpose.",
        ],
        "faq": [
            ("What are the three pieces again?", "A way to make or replay a creature, a permanent that gets better when a creature dies, and a way to sacrifice a creature when you choose. Two out of three is a different deck."),
            ("Why is this precon so expensive?", "Exquisite Blood at $41.93 and Charismatic Conqueror at $25.75, inside a $157.27 product-printing total on 2026-11-01. The top three nonbasics are 47.7%."),
            ("Is a vampire deck automatically aristocrats?", "No. Vampires attack. Aristocrats wants them to die. Clavileno's product leans on both, which is why the combat goldfish still wins."),
            ("What is a reasonable budget version?", "Cut Exquisite Blood if you are not playing the life combo, and the receipt drops by that line cost. A cheaper creature from another precon does not keep the sacrifice trigger."),
        ],
    },
    {
        "slug": "reanimator-deck-guide",
        "title": "Is Reanimator Faster Than Casting Your Threats?",
        "description": "Is reanimator faster than hard-casting in Magic: The Gathering? Mirko's precon is $136.88 with Necromancy at $17.89. Meren goldfishes turn 11.34 by attacking.",
        "date": "2026-12-27",
        "keywords": ["reanimator deck mtg", "mirko precon", "meren of clan nel toth", "reanimate vs hard cast"],
        "related": ["aristocrats-sacrifice-deck-guide", "mill-deck-guide", "mtg-combo-decks-explained", "mtg-deck-archetypes-explained"],
        "decks": ["revenant-recon", "plunder-the-graves"],
        "lens": "reanimate",
        "cta_format": "commander",
        "cta_brief": "Reanimator",
        "thesis": [
            "Reanimator is faster than hard-casting only on the turns you have both a creature in the graveyard and a reanimation spell in hand. In Magic: The Gathering (MTG), the rest of the time you are a deck with expensive creatures and a hand full of setup. The comparison is not reanimate versus a six-drop on turn six. It is reanimate on turn three or four versus doing nothing until turn six, and only in the games where the graveyard actually has the creature.",
            "Two official Commander decks show different eras of the same idea. Revenant Recon, Mirko, is a $136.88 product whose top nonbasics are Necromancy at $17.89, Reanimate at $9.71, and Animate Dead at $7.82. Necromancy and Animate Dead are enchantments. Reanimate is a sorcery. Together those three are 25.9% of the product. The curve has one-drops. Those are the enablers that fill the graveyard, not the monsters. Plunder the Graves, the original Meren precon, is $97.26 and its top costs are a big creature, an anthem, and Skullclamp, not the reanimation spells. Meren reanimates by being on the battlefield and collecting experience. Mirko's product reanimates by casting the famous spells. They are not interchangeable just because both touch the graveyard.",
            "The goldfish clocks, turn 11.50 and turn 11.34, are combat again. The simulator will cast a creature if it can pay for it. It will not Entomb a creature and Reanimate it as a plan. A turn-11 combat win does not prove reanimator is slow, and it does not prove it is fast. It proves the creature plan, played fairly, takes that long. The speed you built the deck for is the unfair line, which you have to count by hand: how many cards put a creature in the yard, how many bring one back, and how many of those you need in the first four turns. The [combo page](/blog/mtg-combo-decks-explained) is the other place a goldfish zero or a goldfish combat clock hides the real line.",
        ],
        "table": [
            ["The reanimation spells are the expensive cards", "Mirko's top three are Necromancy, Reanimate, and Animate Dead", "You are buying the unfair line"],
            ["The commander is the reanimation", "Meren, and the receipt is creatures and Skullclamp instead", "A different failure mode: the commander dies and stays dead"],
            ["You want a measured unfair clock", "The goldfish will not give it to you", "Count enablers and reanimation spells yourself"],
            ["You have the big creatures and not the enablers", "You are hard-casting", "Add the one-drops before you add another seven-drop"],
        ],
        "mistakes": [
            "Adding a reanimation spell without a way to fill the graveyard. Reanimate on an empty yard is a blank card.",
            "Judging the deck by the turn-11 combat goldfish. That number is the fair plan. The deck's reason to exist is the unfair one.",
            "Treating Meren and Mirko as the same build. One cares about the commander staying alive. The other cares about resolving a one- or two-mana spell.",
            "Paying for Necromancy, Reanimate, and Animate Dead and then cutting the one-drops that make them castable on time. The curve on Mirko's list has those one-drops for a reason.",
            "Ignoring graveyard hate because the goldfish never brought any. A real table will have it. The backup plan is the combat clock you just measured, and it is turn 11.",
        ],
        "faq": [
            ("Is reanimator a combo?", "Sometimes. A two-card pile that wins on the spot is a combo. A deck that reanimates a good creature and then plays a normal game is a cheat-on-mana deck. Mirko's product includes the famous spells. It does not, by itself, tell you the creature ends the game alone."),
            ("Why are the reanimation spells so expensive on Mirko's list?", "Necromancy $17.89, Reanimate $9.71, Animate Dead $7.82, together 25.9% of the $136.88 product-printing total. Those are old, heavily played cards printed into a precon."),
            ("Does Meren need those same spells?", "The 2015 product's top costs are Pathbreaker Ibex, Eldrazi Monument, and Skullclamp. The commander is the engine. Buying Reanimate for Meren is a different deck from the one Wizards printed."),
            ("How many creatures do I need in the yard?", "At least one you are happy to bring back, on the turn you have the spell. If your list has two reanimation spells and no discard or mill, you will not have that creature."),
        ],
    },
    {
        "slug": "mill-deck-guide",
        "title": "Can a Mill Deck Win Before Combat Does?",
        "description": "Can a mill deck win before combat in Magic: The Gathering? Captain N'ghathrod's precon goldfishes turn 10.69 by attacking. The sim does not mill the opponent.",
        "date": "2027-01-04",
        "keywords": ["mill deck mtg", "captain nghathrod precon", "anowon mill", "does mill win"],
        "related": ["reanimator-deck-guide", "mtg-combo-decks-explained", "mtg-control-deck-guide", "mtg-deck-archetypes-explained"],
        "decks": ["mind-flayarrrs", "sneak-attack"],
        "lens": "mill",
        "cta_format": "commander",
        "cta_brief": "Mill deck",
        "thesis": [
            "A mill deck wins before combat only if it puts cards from the opponent's library into the graveyard faster than combat would reduce their life total, and this simulator will not tell you that. In Magic: The Gathering (MTG), mill is an effect that moves cards from a library to a graveyard. The player loses when they try to draw from an empty library. The Deck Lab goldfish does not mill the opponent. It attacks. So the clocks below are combat clocks on decks that were printed to mill. Read them as the backup plan, then go count mill cards yourself.",
            "Mind Flayarrrs, Captain N'ghathrod, prices at $135.80 where a TCGplayer nonfoil price existed. Several cards in the product had no such price, so the total undercounts, and the top priced names are Mindcrank, Brainstealer Dragon, and Spellskite. Mindcrank is an actual mill engine. The dragon is a creature the combat goldfish can use. The average winning combat game is turn 10.69. That does not mean the mill plan wins on turn 10. It means the creatures do. Sneak Attack, Anowon, the Ruin Thief, is the other official mill-leaning precon, at $69.98, and a visible slice of that receipt is the basic lands in the product. Anowon's mill is tied to rogue combat damage. The combat clock and the mill plan are the same attacks. That is a different design from a Mindcrank deck, which can mill without attacking.",
            "If your group is four players with 40 life and 99-card libraries, one Mindcrank does not end the table. Count how many cards you mill per turn and how many turns you expect to live. The combat number, roughly turn 11, is how long the creature backup takes against one player who never interacts. A table full of interaction is shorter. The [reanimator guide](/blog/reanimator-deck-guide) is what to do with the graveyard you just filled, if the cards were yours. Mill fills theirs.",
        ],
        "table": [
            ["The mill happens even when you do not attack", "Mindcrank is the expensive engine on the N'ghathrod list", "Do not describe the turn-10 combat clock as the mill clock"],
            ["The mill happens because you attacked with rogues", "Anowon, and the combat goldfish is closer to the real plan", "A pure mill deck that folds when it cannot attack"],
            ["You need a number for the library", "Count mill per turn by hand. The sim will not", "120 games of attacking will not empty a library"],
            ["Basics are a large line cost", "Anowon's product prices the lands in the box", "A cheap Swamp is not the number in this total"],
        ],
        "mistakes": [
            "Quoting the goldfish turn as a mill speed. The tool does not mill. The page you are reading is the warning.",
            "Building mill for a four-player table with one mill card. Ninety-nine-card libraries times three opponents is the actual job.",
            "Milling yourself by accident and calling it the same plan. Self-mill is a reanimator setup. Milling the opponent is a win condition. The graveyards are not interchangeable.",
            "Paying Mindcrank prices and then never untapping it. An engine that costs $13.32 on this printing has to be the card the deck is about, or it is an expensive permanent that dies to the first removal.",
            "Ignoring the unpriced cards on the N'ghathrod list. The $135.80 total is missing any printing that had no TCGplayer nonfoil retail. The real cardboard cost is higher.",
        ],
        "faq": [
            ("Does the simulator mill?", "No. Wins are combat damage or direct damage. Both official mill precons show a combat clock near turn 11 because that is the plan the tool can see. The mill plan is invisible to it."),
            ("Which precon actually mills without attacking?", "Mind Flayarrrs includes Mindcrank, which mills when life is lost. Anowon mills when rogues deal combat damage. One can function on a turn you did not attack. The other cannot."),
            ("Why is Anowon cheaper?", "The priced total is $69.98 against $135.80, and Anowon's large line items include the basic lands shipped in the product. N'ghathrod's top nonbasic is Mindcrank at $13.32, with several cards unpriced on top of that."),
            ("Is mill good against a combo deck?", "Only if you mill the card they needed before they draw it, or you empty the library. Milling them into the graveyard can help a reanimator or graveyard combo. Know which opponent you are milling."),
        ],
    },
    {
        "slug": "voltron-commander-guide",
        "title": "How Many Auras Does a Voltron Deck Need?",
        "description": "How many auras does voltron need in Magic: The Gathering? The Pioneer auras product has 31 one-drops. Lurrus is banned. Ellivere's precon costs $127.24.",
        "date": "2027-01-12",
        "keywords": ["voltron mtg", "auras deck pioneer", "ellivere precon", "lurrus banned pioneer"],
        "related": ["should-you-play-aggro", "mtg-tempo-decks-explained", "aristocrats-sacrifice-deck-guide", "mtg-deck-archetypes-explained"],
        "decks": ["orzhov-auras", "virtue-and-valor"],
        "lens": "auras",
        "cta_format": "commander",
        "cta_brief": "Aura voltron",
        "thesis": [
            "A voltron deck needs enough auras or equipment that the creature is lethal in one or two attacks, and enough extra creatures or protection that one removal spell does not end your game. In Magic: The Gathering (MTG), voltron means one creature wearing the rest of the deck. The math is harsh: every aura in your hand does nothing until a creature is on the battlefield, and every aura on a creature that dies goes to the graveyard with it. You do not need twenty auras if six of them already kill. You need the creature to stay in play, or another creature to wear the next wave.",
            "Orzhov Auras, the 2021 Pioneer Challenger product, is the 60-card version. Thirty-one nonlands cost one mana. The curve is the strategy: the creature and the auras have to come down immediately. The goldfish average win is turn 8.09, slower than burn, because auras spend cards to make one body larger instead of adding more attackers. Lurrus of the Dream-Den is in the printed list and is not legal today per the Scryfall bulk of 2026-11-01. The companion was the card that made dying auras easy to replay. Without it, the printed deck is a historical object, not a registration sheet. Thoughtseize and Sram are the other price centers, inside a $46.84 total.",
            "Virtue and Valor, Ellivere of the Wild Court, is the Commander version at $127.24. Bear Umbra, Retether, and Hall of Heliod's Generosity are the top nonbasics, 30.1% of the product. Retether and the Hall are cards that get auras back. That is the Commander answer to the same problem Lurrus used to solve in Pioneer: auras in the graveyard are not on a creature. The [tempo page](/blog/mtg-tempo-decks-explained) is the small-creature comparison when you would rather have many bodies than one enchanted one.",
        ],
        "table": [
            ["60-card auras", "31 one-drops, turn 8.09, and a banned companion", "Do not register Lurrus"],
            ["Commander auras", "Ellivere, with Retether and the Hall as the recursion", "$127.24, 30.1% in three cards"],
            ["One removal spell ends your turn", "You need a second creature or a way to replay auras", "A single creature and a hand of enchantments is a mulligan"],
            ["You want many attackers", "Voltron is the wrong shape", "Tokens or a normal aggro curve"],
        ],
        "mistakes": [
            "Registering the Pioneer auras product as printed. Lurrus is not legal. The goldfish was run on the printed list anyway so you can see the curve, not so you can copy it.",
            "Drawing seven auras and no creature and keeping the hand. The one-drop count is high so this happens less often. It still happens, and the hand does nothing.",
            "Spending Thoughtseize on a random card and then losing the creature you needed the life total to race with. Thoughtseize is $6.63 of a $46.84 product. It has to take the removal spell.",
            "Buying Ellivere's expensive recursion and not playing enough auras to recur. Retether is a blank if the graveyard is empty.",
            "Equating auras and equipment without checking what happens when the creature dies. Some equipment stays. Auras do not. The Pioneer list is auras.",
        ],
        "faq": [
            ("How many auras is enough?", "Enough that one creature becomes lethal, which on these curves means a lot of one-mana auras in the 60-card list (31 one-drops, not all of them auras) and a Commander list that can get the auras back. Count the auras that actually grant evasion or power, not every enchantment."),
            ("Can I play Lurrus in Pioneer?", "No. Lurrus of the Dream-Den is not legal today per the Scryfall bulk of 2026-11-01. The 2021 product included it as a companion."),
            ("Why is the Commander aura deck almost three times the price?", "Virtue and Valor is $127.24 against the Pioneer product's $46.84. Bear Umbra alone is $14.51, and the recursion pieces are the rest of the top three. Different formats, different expensive cards."),
            ("Is voltron the same as tempo?", "Tempo uses several small creatures and disruption. Voltron uses one creature and a stack of auras. Spirits goldfishes faster than the auras product because the creatures are the threats, not the costumes."),
        ],
    },
    {
        "slug": "spellslinger-deck-guide",
        "title": "What Does a Spellslinger Deck Spend Its Mana On?",
        "description": "What does a spellslinger deck pay for in Magic: The Gathering? Kalamax's precon is $152.89, and Deflecting Swat is $75.69 of it. The goldfish won 0 games.",
        "date": "2027-01-20",
        "keywords": ["spellslinger mtg", "kalamax precon price", "deflecting swat", "zaffai thunder conductor"],
        "related": ["mtg-combo-decks-explained", "mtg-control-deck-guide", "should-you-play-control", "card-advantage-explained"],
        "decks": ["arcane-maelstrom", "prismari-performance"],
        "lens": "spells",
        "cta_format": "commander",
        "cta_brief": "Spellslinger",
        "thesis": [
            "A spellslinger deck spends its mana on instants and sorceries, and on whatever permanent makes those spells better, and it is in trouble when it draws the permanent and not the spells. In Magic: The Gathering (MTG), the payoff might copy a spell, reduce its cost, or deal damage when you cast it. The mana still has to be there on the turn you cast two spells, not just on the turn you cast the payoff. If your curve is twelve seven-mana spells and one cost reducer, you do not have a spellslinger deck. You have expensive sorceries.",
            "Arcane Maelstrom, Kalamax, the Stormsire, is the price lesson. The product total is $152.89 on priced printings. Deflecting Swat is $75.69 of that, and the top three nonbasics are 61.7%. You are not buying a spellslinger deck at that receipt. You are buying a free counterspell that happens to live in a spellslinger precon. Twinning Staff is the next line at $14.52, and that one is actually a spell payoff. If Deflecting Swat is the card you want, say so. If the deck is the card you want, price the list without Swat and see if the plan is still the plan. The goldfish won zero games in 120. Kalamax copies spells. The simulator attacks. A zero is the wrong scoreboard, same as the combo page, and it is useful precisely because it refuses to pretend combat is the win.",
            "Prismari Performance, Zaffai, Thunder Conductor, is the curve lesson at $76.00 where prices existed. The nonland curve has 12 cards at seven or more and peaks in the middle at five. Seething Song is the top priced spell, a ritual, which is mana for a big spell rather than a threat. Zaffai wants you to cast large spells. That is a mana question: rituals and lands, 37 of them, under a top-heavy curve. The [combo guide](/blog/mtg-combo-decks-explained) covers the other kind of spell deck, the one with a named winning pile. Spellslinger can be that, or it can be a value deck that casts two spells a turn and never combos. Know which one you sleeved.",
        ],
        "table": [
            ["One card is half the receipt", "Deflecting Swat is $75.69 of Kalamax's $152.89", "Decide if you are buying the card or the deck"],
            ["The curve peaks at seven", "Zaffai needs rituals and 37 lands, not more seven-drops", "A two-mana spell deck is a different commander"],
            ["You want the goldfish to storm off", "It will not. Both spell lists won 0 of 120", "Practice the turn you cast two spells, by hand"],
            ["You wanted creatures", "These products spend the mana on spells", "Tokens or voltron"],
        ],
        "mistakes": [
            "Calling Deflecting Swat the spellslinger plan. It is half the Kalamax product's price and it is a free counter, not a copy engine. Twinning Staff is the payoff that cares about spells.",
            "Adding more big spells to Zaffai without a ritual or a land. The curve is already top-heavy. Seething Song is in the list because the spells cost what they cost.",
            "Expecting a combat goldfish to show storm. Zero wins is the tool telling you it cannot see the plan. Do not add creatures until the number moves and then call it fixed.",
            "Cutting lands because spells are the deck. Prismari plays 37 lands. Kalamax plays 38. The second spell on a turn needs the mana the land would have been.",
            "Swapping a cheap sorcery in for a spell that copies spells. The prices are different because the jobs are different.",
        ],
        "faq": [
            ("Why is Deflecting Swat so much of the deck?", "The product printing's TCGplayer nonfoil price on 2026-11-01 is $75.69 inside a $152.89 total. One card, about half the receipt. The top three nonbasics together are 61.7%."),
            ("Did either deck win a goldfish game?", "No. 0 of 120 games each, seed 1729, combo policy, 40-life opponent, 16 turns. The simulator does not copy spells or storm. The zero is expected."),
            ("What should the mana be spent on in a turn?", "On two spells if the payoff cares that you cast two, or on one large spell if the commander is Zaffai. Look at the commander's text before you add another ritual."),
            ("Is spellslinger the same as control?", "Control spends mana to answer a threat and then draws. Spellslinger spends mana to cast its own spells for a payoff. Seize Control's Mizzix deck is the overlap, and it lives on the control page because the product used the word control. Kalamax is here because the payoff is copying your spells."),
        ],
    },
]


def render(guide: dict, decks: dict[str, dict], fetched_at: str) -> str:
    rows = "\n".join(f"| {left} | {mid} | {right} |" for left, mid, right in guide["table"])
    mistakes = "\n".join(f"- {item}" for item in guide["mistakes"])
    faqs = "\n\n".join(f"### {question}\n\n{answer}" for question, answer in guide["faq"])
    blocks = "\n\n".join(
        f'<DeckBlock id="{deck_id}" />\n\n' + narrate(decks[deck_id], fetched_at) for deck_id in guide["decks"]
    )
    thesis = "\n\n".join(guide["thesis"])
    related = ", ".join(f'"{slug}"' for slug in guide["related"])
    keywords = ", ".join(f'"{word}"' for word in guide["keywords"])
    # One short shared note. The long fetch paragraph used to be copied onto every guide.
    made = (
        f"Lists and nonfoil prices are MTGJSON; legality is the Scryfall oracle-cards bulk. Fetched {fetched_at}. "
        "The clock is the Deck Lab goldfish, 120 games, seed 1729."
    )
    body = f"""---
title: "{guide["title"]}"
description: "{guide["description"]}"
date: {PUBLISH_ON}
updated: {fetched_at}
author: Deck Lab Editorial
reviewed: true
category: deck-archetypes
keywords: [{keywords}]
related: [{related}]
---

## Short answer

{thesis}

<InArticleAd />

## When to choose this

| Situation | Lean in | Walk away |
| --- | --- | --- |
{rows}

## Example decks

{blocks}

<InArticleAd />

## Common mistakes

{mistakes}

## FAQ

{faqs}

## How this was made

{made}

<FanContentNotice />

<DeckLabCTA format="{guide["cta_format"]}" brief="{guide["cta_brief"]}" />
"""
    return body


def main() -> None:
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    fetched_at = str(facts["fetched_at"])
    decks = facts["decks"]
    problems: list[str] = []
    for guide in GUIDES:
        missing = [deck_id for deck_id in guide["decks"] if deck_id not in decks]
        if missing:
            raise SystemExit(f"{guide['slug']} missing decks {missing}")
        description = guide["description"]
        if not 120 <= len(description) <= 170:
            raise SystemExit(f"{guide['slug']} description is {len(description)} chars")
        text = render(guide, decks, fetched_at)
        if "{" in text.split("---", 2)[-1]:
            # Frontmatter has no braces. A brace in the body breaks MDX.
            body = text.split("---", 2)[-1]
            raise SystemExit(f"{guide['slug']} has a bare brace: {body[body.index('{'):body.index('{')+40]!r}")
        count = words_of(text.split("---", 2)[-1])
        path = BLOG / f"{guide['slug']}.mdx"
        path.write_text(text, encoding="utf-8")
        print(f"{guide['slug']}: {count} words, description {len(description)}")
        if count < 900 or count > 3500:
            problems.append(f"{guide['slug']} word count {count} out of range")
    if problems:
        raise SystemExit("\n".join(problems))


if __name__ == "__main__":
    main()
