"""What a card does in a game, in plain words, for the per-card "Why?" note.

The note used to explain where a card came from ("Part of the Azorius
Control list this deck is built from"). Players want the in-game reason:
what the card does, and why that matters for this deck's plan. Both come
from data we have: the oracle text and keywords for the first, and the
card's role plus the deck's strategy for the second.

Everything here is pattern-based and conservative. When nothing matches,
the caller falls back to a plain description (mana value and card type),
so a note never claims an effect the card doesn't have.
"""

from __future__ import annotations

import re

from app.models import CardRecord

_NUMBER_WORDS = {"a": "a", "an": "a", "one": "a", "two": "two", "three": "three", "four": "four", "x": "X"}


def _count(word: str) -> str:
    return _NUMBER_WORDS.get(word.lower(), word)


def _article(noun: str) -> str:
    return f"an {noun}" if noun[:1].lower() in "aeiou" else f"a {noun}"


def _counter(match: re.Match[str]) -> str:
    kind = match.group(1).strip()
    return f"counters {_article(f'{kind} spell' if kind else 'spell')}"


def _mana(match: re.Match[str]) -> str:
    symbols = re.findall(r"\{[^}]+\}", match.group(1))
    words = {1: "", 2: "two ", 3: "three ", 4: "four "}
    return f"adds {words.get(len(symbols), f'{len(symbols)} ')}mana"


def _cards(word: str) -> str:
    count = _count(word)
    return f"{count} card" if count == "a" else f"{count} cards"


# (pattern, phrase) in priority order. Phrases are third-person verb
# phrases, so they read after the card name: "Lightning Bolt deals 3
# damage to any creature or player." Group 1, when present, feeds the
# phrase.
_EFFECTS: tuple[tuple[re.Pattern[str], object], ...] = (
    (re.compile(r"counter target ([a-z ]*?)spell", re.I), _counter),
    (re.compile(r"exile each permanent with mana value|(?:destroy|exile) all (?:creatures|nonland permanents)|deals \d+ damage to each creature|all creatures get -\d+/-\d+|each creature gets -\d+/-\d+", re.I), "wipes the board"),
    (re.compile(r"put target nonland permanent into its owner's library", re.I), "tucks an opposing nonland permanent"),
    (re.compile(r"(?:destroy|exile) target (?:nonland )?permanent", re.I), "removes a permanent"),
    (re.compile(r"(?:destroy|exile) target (?:attacking |blocking |tapped |nonblack |nonartifact )*creature", re.I), "removes a creature"),
    (re.compile(r"(?:destroy|exile) target (artifact or enchantment|artifact|enchantment)", re.I), lambda m: f"destroys {_article(m.group(1))}"),
    (re.compile(r"(?:destroy|exile) target planeswalker", re.I), "removes a planeswalker"),
    (re.compile(r"return target (?:nonland )?(creature|permanent)[^.]*? to its owner's hand", re.I), lambda m: f"bounces a {m.group(1)}"),
    (re.compile(r"deals (\d+|x) damage to any target", re.I), lambda m: f"deals {m.group(1).upper() if m.group(1) == 'x' else m.group(1)} damage to any creature or player"),
    (re.compile(r"deals (\d+|x) damage to target creature", re.I), lambda m: f"deals {m.group(1)} damage to a creature"),
    (re.compile(r"deals (\d+|x) damage to (?:target player|each opponent|target opponent)", re.I), lambda m: f"deals {m.group(1)} damage straight to the opponent"),
    (re.compile(r"target creature (?:an opponent controls )?gets -(\d+)/-\d+", re.I), lambda m: f"shrinks a creature by -{m.group(1)}"),
    (re.compile(r"fights? (?:target|up to one target) creature", re.I), "fights an opposing creature"),
    (re.compile(r"target (?:player|opponent) (?:reveals (?:his or her|their) hand[^.]*\. you choose|discards)", re.I), "strips a card from the opponent's hand"),
    (re.compile(r"each player discards", re.I), "makes each player discard"),
    (re.compile(r"target player exiles a card from (?:their|his or her) hand", re.I), "strips a card from the opponent's hand"),
    (re.compile(r"(?:target player|each opponent|target opponent) sacrifices an? (?:creature|attacking creature)", re.I), "makes the opponent sacrifice a creature"),
    (re.compile(r"gains flashback", re.I), "lets you recast a spell from your graveyard"),
    (re.compile(r"exile the top card of your library[^.]*\.[^.]*you may (?:play|cast)", re.I), "lets you play the top card of your library"),
    (re.compile(r"exile the top (\w+) cards of your library[^.]*\.[^.]*you may (?:play|cast)", re.I), lambda m: f"lets you play the top {_cards(m.group(1))} of your library"),
    (re.compile(r"(?<!opponent )(?<!player )(?<!that player )draws? (a|an|one|two|three|four|x) cards?", re.I), lambda m: f"draws {_cards(m.group(1))}"),
    (re.compile(r"look at the top (\w+) cards of your library", re.I), "digs through your library for the right card"),
    (re.compile(r"\binvestigate\b", re.I), "makes Clues to draw cards later"),
    (re.compile(r"\bscry (\d+)", re.I), lambda m: f"scries {m.group(1)}"),
    (re.compile(r"search your library for a card\b", re.I), "tutors any card from your library"),
    (re.compile(r"search your library for (?:a|up to \w+) (?:basic )?lands?", re.I), "fetches a land"),
    (re.compile(r"untap (?:up to )?(?:two|\w+) lands", re.I), "untaps lands"),
    (re.compile(r"sacrifice an? (?:creature|artifact)[^:]*: add", re.I), "sacrifices creatures for mana"),
    (re.compile(r"\badd ((?:\{[^}]+\})+)", re.I), _mana),
    (re.compile(r"\badd one mana", re.I), "adds mana"),
    (re.compile(r"create [^.]*treasure token", re.I), "makes Treasure"),
    (re.compile(r"create (?:a|an|one|two|three|four|x|\w+) [^.]*?creature tokens?", re.I), "makes creature tokens"),
    (re.compile(r"creatures you control get \+(\d+)/\+(\d+)", re.I), lambda m: f"gives your team +{m.group(1)}/+{m.group(2)}"),
    (re.compile(r"other [a-z ]*?creatures? you control get \+(\d+)/\+(\d+)", re.I), lambda m: f"gives your other creatures +{m.group(1)}/+{m.group(2)}"),
    (re.compile(r"return target [^.]*?card from your graveyard to (?:your hand|the battlefield)", re.I), "brings back a card from your graveyard"),
    (re.compile(r"exile (?:all cards from )?(?:target player's|all|each player's) graveyards?|cards in graveyards (?:can't|lose)", re.I), "shuts down graveyards"),
    (re.compile(r"whenever [^.]*\bcreatures? [^.]*\bdies\b", re.I), "triggers whenever a creature dies"),
    (re.compile(r"(?:target player|each opponent) loses (\d+) life", re.I), lambda m: f"drains the opponent for {m.group(1)}"),
    (re.compile(r"you gain (\d+|x) life", re.I), lambda m: f"gains you {m.group(1)} life"),
    (re.compile(r"can't be countered", re.I), "can't be countered"),
)

_KEYWORD_PHRASES: tuple[tuple[str, str], ...] = (
    ("Haste", "can attack the turn it comes down"),
    ("Flash", "can be cast at instant speed"),
    ("Flying", "flies over most blockers"),
    ("Prowess", "grows each time you cast a noncreature spell"),
    ("Trample", "tramples over chump blockers"),
    ("Double strike", "deals combat damage twice"),
    ("First strike", "strikes first in combat"),
    ("Deathtouch", "kills any creature it damages"),
    ("Lifelink", "gains you life whenever it deals damage"),
    ("Menace", "is hard to block"),
    ("Hexproof", "can't be targeted by your opponent's spells"),
    ("Ward", "taxes your opponent's removal"),
    ("Vigilance", "attacks without tapping"),
    ("Cascade", "casts a free spell when you cast it"),
    ("Flashback", "can be cast again from your graveyard"),
    ("Escape", "can be cast again from your graveyard"),
    ("Delve", "costs less by exiling cards from your graveyard"),
    ("Convoke", "can be paid for by tapping your creatures"),
    ("Undying", "comes back once after it dies"),
    ("Persist", "comes back once after it dies"),
    ("Infect", "deals damage as poison counters"),
)

_LOYALTY = re.compile(r"^\s*([+−\-]?(?:\d+|X)|0):\s*(.+)$", re.M)


def _text(card: CardRecord) -> str:
    return card.oracle_text or "\n".join(face.oracle_text or "" for face in card.faces)


def _effects(text: str, limit: int) -> list[str]:
    # Reminder text (in parentheses) explains other cards' rules, e.g. the
    # Treasure "Add one mana" on Smothering Tithe.
    text = re.sub(r"\([^)]*\)", "", text)
    phrases: list[str] = []
    for pattern, phrase in _EFFECTS:
        match = pattern.search(text)
        if not match:
            continue
        rendered = phrase(match) if callable(phrase) else str(phrase)
        if rendered.startswith("adds ") and "sacrifices creatures for mana" in phrases:
            continue
        if rendered not in phrases:
            phrases.append(rendered)
        if len(phrases) >= limit:
            break
    return phrases


def _join(phrases: list[str]) -> str:
    if len(phrases) <= 1:
        return "".join(phrases)
    return ", ".join(phrases[:-1]) + " and " + phrases[-1]


def _land_function(card: CardRecord, text: str) -> str | None:
    colors = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green", "C": "colorless"}
    produced = [colors[c] for c in dict.fromkeys(re.findall(r"\{([WUBRGC])\}", text)) if "add" in text.lower()]
    if re.search(r"any color", text, re.I):
        produced = ["any color of"]
    extras = [p for p in _effects(text, 2) if p not in ("adds mana", "adds two mana")]
    if re.search(r"search your library for [^.]*land", text, re.I):
        return "fetches the land you need, fixing your colors"
    parts: list[str] = []
    if produced:
        parts.append(f"taps for {' or '.join(produced)} mana" if produced != ["any color of"] else "taps for mana of any color")
    parts += extras[:1]
    return _join(parts) or None


def describe(card: CardRecord) -> str | None:
    """'draws a card and untaps lands, and its −3 tucks an opposing nonland permanent'."""
    text = _text(card)
    type_line = card.type_line or ""
    if "Land" in type_line and "Creature" not in type_line:
        return _land_function(card, text)
    if "Planeswalker" in type_line:
        abilities = [(cost.replace("-", "−"), body) for cost, body in _LOYALTY.findall(text)]
        # One plus and one minus ability reads best; skip emblem ultimates.
        def ultimate(cost: str) -> bool:
            digits = cost.lstrip("+−-")
            return cost.startswith("−") and digits.isdigit() and int(digits) >= 7

        abilities = [a for a in abilities if "emblem" not in a[1].lower() and not ultimate(a[0])]
        plus = [a for a in abilities if not a[0].startswith("−")]
        minus = [a for a in abilities if a[0].startswith("−")]
        clauses: list[str] = []
        for group in (plus, minus):
            for cost, body in group:
                effects = _effects(body, 2)
                if effects:
                    clauses.append(f"its {cost} {_join(effects)}")
                    break
        return ", and ".join(clauses) if clauses else None
    phrases: list[str] = []
    if "Creature" in type_line:
        phrases += [phrase for keyword, phrase in _KEYWORD_PHRASES if keyword in card.keywords][:2]
    phrases += [p for p in _effects(text, 3) if p not in phrases]
    return _join(phrases[:3]) or None


# Why that matters, by the card's role and the deck's plan.
_PLAN_CLAUSES: dict[tuple[str, str], str] = {
    ("threat", "aggro"): "That's early pressure the opponent has to answer right away.",
    ("threat", "tempo"): "It's a cheap clock to protect with your interaction.",
    ("threat", "control"): "It closes out the game once you've taken control.",
    ("threat", "midrange"): "It's a sturdy threat that wins the fights in the middle turns.",
    ("threat", "ramp"): "It's the kind of big payoff your extra mana is for.",
    ("threat", "combo"): "It keeps the opponent busy while you assemble the combo.",
    ("interaction", "aggro"): "It clears blockers so your attackers keep connecting.",
    ("interaction", "tempo"): "It handles a threat cheaply while your clock keeps attacking.",
    ("interaction", "control"): "It answers threats so you survive to the late game.",
    ("interaction", "midrange"): "It trades one-for-one with the opponent's best cards.",
    ("interaction", "combo"): "It protects your combo turn or slows the opponent down.",
    ("card advantage", "control"): "It refills your hand so you don't run out of answers.",
    ("card advantage", "aggro"): "It keeps the pressure coming after your hand runs out.",
    ("card advantage", "combo"): "It digs you toward your combo pieces.",
    ("mana development", "ramp"): "It accelerates you into your biggest spells.",
    ("mana development", "combo"): "It speeds up the turn you go off.",
    ("reach", "aggro"): "It finishes the opponent after your creatures soften them up.",
}
_ROLE_CLAUSES: dict[str, str] = {
    "threat": "It's one of the ways this deck wins.",
    "interaction": "It keeps the opponent's best cards in check.",
    "card advantage": "It keeps your hand stocked.",
    "mana development": "It gets you ahead on mana.",
    "reach": "It can finish the game when the board is stalled.",
}

PLANS = ("aggro", "tempo", "control", "midrange", "combo", "ramp")


def plan_clause(role: str, plan: str | None) -> str | None:
    if plan and (role, plan) in _PLAN_CLAUSES:
        return _PLAN_CLAUSES[(role, plan)]
    return _ROLE_CLAUSES.get(role)
