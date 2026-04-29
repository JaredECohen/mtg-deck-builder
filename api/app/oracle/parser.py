"""Oracle-text parser.

Translates an MTG card's oracle text into a typed :class:`Effect` list.
Pattern-based rather than grammar-based — Magic's oracle text is too
irregular for a clean grammar, but the *output* schema is what matters
for downstream simulation. Coverage is reported per card so that
unparsed clauses can be flagged for the ``card-evaluator`` Skill.
"""

from __future__ import annotations

import re
from typing import Iterable

from app.oracle.profile import Action, ActionKind, Effect, TriggerType

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")
_SELF_REF_RE = re.compile(r"~|CARDNAME", flags=re.IGNORECASE)
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "x": 1,
}


def _to_int(token: str) -> int:
    token = token.strip().lower().replace(",", "")
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token, 0)


def _replace_self(text: str, name: str | None) -> str:
    """Replace the literal cardname with ``~`` so we can pattern match."""
    if name and name in text:
        text = text.replace(name, "~")
    return text


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    text = text.strip()
    if not text:
        return []
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


_TRIGGER_PATTERNS: list[tuple[re.Pattern[str], TriggerType]] = [
    (re.compile(r"^when(?:ever)?\s+~\s+enters", re.I), "etb"),
    (re.compile(r"^when(?:ever)?\s+~\s+leaves", re.I), "ltb"),
    (re.compile(r"^when(?:ever)?\s+~\s+dies", re.I), "dies"),
    (re.compile(r"^when(?:ever)?\s+~\s+attacks", re.I), "attacks"),
    (re.compile(r"^when(?:ever)?\s+~\s+blocks", re.I), "blocks"),
    (re.compile(r"^when(?:ever)?\s+~\s+deals\s+(?:combat\s+)?damage", re.I), "deals_damage"),
    (re.compile(r"^when(?:ever)?\s+you\s+cast\s+a\s+(?:noncreature|non-creature)", re.I), "cast_noncreature"),
    (re.compile(r"^when(?:ever)?\s+you\s+cast\s+(?:an?\s+)?(?:instant|sorcery)", re.I), "cast_instant_or_sorcery"),
    (re.compile(r"^when(?:ever)?\s+you\s+cast", re.I), "cast_trigger"),
    (re.compile(r"^at\s+the\s+beginning\s+of\s+(?:your\s+)?upkeep", re.I), "upkeep"),
    (re.compile(r"^at\s+the\s+beginning\s+of\s+(?:your\s+)?end\s+step", re.I), "end_step"),
    (re.compile(r"^at\s+the\s+beginning\s+of\s+(?:your\s+)?(?:next\s+)?draw\s+step", re.I), "draw_step"),
    (re.compile(r"^when(?:ever)?\s+", re.I), "cast_trigger"),
    (re.compile(r"^at\s+the\s+beginning", re.I), "upkeep"),
]


def _detect_trigger(sentence: str) -> tuple[TriggerType, str]:
    """Return (trigger, residual_clause)."""
    for pat, kind in _TRIGGER_PATTERNS:
        m = pat.match(sentence)
        if m:
            residual = sentence[m.end():].lstrip(" ,").rstrip(".")
            return kind, residual
    if re.match(r"^\{[^}]+\}(?:\s*,\s*\{[^}]+\})*\s*:", sentence):
        return "activated", sentence.split(":", 1)[1].strip().rstrip(".")
    return "none", sentence.rstrip(".")


_DRAW_RE = re.compile(r"draw[s]?\s+(\w+)\s+card", re.I)
_DAMAGE_RE = re.compile(
    r"deal[s]?\s+(\w+)\s+damage\s+to\s+(any target|target [^,.;]+|each opponent|each player|each creature|you|its controller)",
    re.I,
)
_DESTROY_RE = re.compile(r"destroy\s+(?:target|all|each)\s+([^,.;]+)", re.I)
# Match exile only when it's targeted/board-wide removal — NOT cost payments
# like "exile a card from your hand" (Evoke) or "exile the top card" (impulse).
_EXILE_RE = re.compile(
    r"exile\s+(target|all|each|up\s+to\s+\w+\s+target)\s+([^,.;]+)",
    re.I,
)
_COUNTER_RE = re.compile(r"counter\s+(?:target|that)\s+([^,.;]+)", re.I)
_TOKEN_RE = re.compile(
    r"create[s]?\s+(\w+)\s+([^,.;]*?)(?:creature\s+token|token\s+creature|token)",
    re.I,
)
_ADD_MANA_RE = re.compile(r"add\s+((?:\{[^}]+\}\s*)+|\w+\s+mana)", re.I)
_MILL_RE = re.compile(r"(?:mill[s]?|put[s]?\s+the\s+top)\s+(\w+)\s+card", re.I)
_DISCARD_RE = re.compile(r"discard[s]?\s+(\w+)\s+card", re.I)
_TUTOR_RE = re.compile(r"search\s+your\s+library\s+for\s+([^,.;]+)", re.I)
_GAIN_LIFE_RE = re.compile(r"(?:gain|gains)\s+(\w+)\s+life", re.I)
_LOSE_LIFE_RE = re.compile(r"(?:lose|loses)\s+(\w+)\s+life", re.I)
_PUMP_RE = re.compile(r"\+(\d+)\s*/\s*\+(\d+)", re.I)
_SCRY_RE = re.compile(r"scry\s+(\d+)", re.I)
_SURVEIL_RE = re.compile(r"surveil\s+(\d+)", re.I)
_RETURN_RE = re.compile(r"return\s+(?:target|each)\s+([^,.;]+?)\s+to\s+(?:its|their)\s+owner", re.I)
_COPY_RE = re.compile(r"copy\s+(?:target|that)\s+(spell|instant|sorcery)", re.I)
_WIN_RE = re.compile(r"you\s+win\s+the\s+game", re.I)
_EXTRA_TURN_RE = re.compile(r"take\s+an\s+extra\s+turn", re.I)
_INVESTIGATE_RE = re.compile(r"investigate", re.I)
_TREASURE_RE = re.compile(r"create[s]?\s+(\w+)\s+treasure\s+token", re.I)
_FOOD_RE = re.compile(r"create[s]?\s+(\w+)\s+food\s+token", re.I)
_BLOOD_RE = re.compile(r"create[s]?\s+(\w+)\s+blood\s+token", re.I)
_CLUE_RE = re.compile(r"create[s]?\s+(\w+)\s+clue\s+token", re.I)


def _extract_actions(clause: str) -> list[Action]:
    actions: list[Action] = []
    for m in _DRAW_RE.finditer(clause):
        actions.append(Action(kind="draw", quantity=_to_int(m.group(1)), text=m.group(0)))
    for m in _DAMAGE_RE.finditer(clause):
        actions.append(
            Action(
                kind="damage",
                quantity=_to_int(m.group(1)),
                target=m.group(2).strip().lower(),
                text=m.group(0),
            )
        )
    for m in _DESTROY_RE.finditer(clause):
        actions.append(Action(kind="destroy", quantity=1, target=m.group(1).strip(), text=m.group(0)))
    for m in _EXILE_RE.finditer(clause):
        actions.append(Action(kind="exile", quantity=1, target=m.group(2).strip(), text=m.group(0)))
    for m in _COUNTER_RE.finditer(clause):
        actions.append(Action(kind="counter", quantity=1, target=m.group(1).strip(), text=m.group(0)))
    for m in _TREASURE_RE.finditer(clause):
        actions.append(Action(kind="treasure", quantity=_to_int(m.group(1)), text=m.group(0)))
    for m in _FOOD_RE.finditer(clause):
        actions.append(Action(kind="food", quantity=_to_int(m.group(1)), text=m.group(0)))
    for m in _BLOOD_RE.finditer(clause):
        actions.append(Action(kind="blood", quantity=_to_int(m.group(1)), text=m.group(0)))
    for m in _CLUE_RE.finditer(clause):
        actions.append(Action(kind="clue", quantity=_to_int(m.group(1)), text=m.group(0)))
    for m in _TOKEN_RE.finditer(clause):
        if any(a.kind in {"treasure", "food", "blood", "clue"} for a in actions if a.text == m.group(0)):
            continue
        descriptor = m.group(2).strip().lower()
        if any(t in descriptor for t in ("treasure", "food", "blood", "clue")):
            continue
        actions.append(
            Action(
                kind="create_token",
                quantity=_to_int(m.group(1)),
                target=descriptor or "creature",
                text=m.group(0),
            )
        )
    for m in _ADD_MANA_RE.finditer(clause):
        symbols = re.findall(r"\{[^}]+\}", m.group(1))
        qty = float(len(symbols)) if symbols else 1.0
        actions.append(Action(kind="add_mana", quantity=qty, target=m.group(1).strip(), text=m.group(0)))
    for m in _MILL_RE.finditer(clause):
        actions.append(Action(kind="mill", quantity=_to_int(m.group(1)), text=m.group(0)))
    for m in _DISCARD_RE.finditer(clause):
        actions.append(Action(kind="discard", quantity=_to_int(m.group(1)), text=m.group(0)))
    for m in _TUTOR_RE.finditer(clause):
        actions.append(Action(kind="tutor", quantity=1, target=m.group(1).strip(), text=m.group(0)))
    for m in _GAIN_LIFE_RE.finditer(clause):
        actions.append(Action(kind="gain_life", quantity=_to_int(m.group(1)), text=m.group(0)))
    for m in _LOSE_LIFE_RE.finditer(clause):
        actions.append(Action(kind="lose_life", quantity=_to_int(m.group(1)), text=m.group(0)))
    for m in _PUMP_RE.finditer(clause):
        actions.append(
            Action(
                kind="pump",
                quantity=float(int(m.group(1)) + int(m.group(2))) / 2.0,
                text=m.group(0),
            )
        )
    for m in _SCRY_RE.finditer(clause):
        actions.append(Action(kind="scry", quantity=_to_int(m.group(1)), text=m.group(0)))
    for m in _SURVEIL_RE.finditer(clause):
        actions.append(Action(kind="surveil", quantity=_to_int(m.group(1)), text=m.group(0)))
    for m in _RETURN_RE.finditer(clause):
        actions.append(Action(kind="return_to_hand", quantity=1, target=m.group(1).strip(), text=m.group(0)))
    for m in _COPY_RE.finditer(clause):
        actions.append(Action(kind="copy_spell", quantity=1, target=m.group(1).strip(), text=m.group(0)))
    if _WIN_RE.search(clause):
        actions.append(Action(kind="win_game", quantity=1, text="win the game"))
    if _EXTRA_TURN_RE.search(clause):
        actions.append(Action(kind="extra_turn", quantity=1, text="extra turn"))
    if _INVESTIGATE_RE.search(clause):
        actions.append(Action(kind="investigate", quantity=1, text="investigate"))
    return actions


_KEYWORD_INTERACTION = {
    "flash", "haste", "vigilance", "deathtouch", "lifelink", "trample",
    "first strike", "double strike", "hexproof", "indestructible",
    "menace", "reach", "ward", "flying", "defender", "skulk", "prowess",
    "annihilator", "cascade", "convoke", "delve", "dredge", "evoke",
    "flashback", "kicker", "madness", "miracle", "morph", "overload",
    "scry", "storm", "suspend", "buyback", "cycling", "channel",
    "disturb", "embalm", "escape", "explore", "foretell", "ninjutsu",
    "phasing", "rebound", "recover", "shadow", "split second", "surge",
    "transmute", "undying", "unearth", "vanishing", "wither",
    "afterlife", "amplify", "ascend", "aura swap", "battle cry",
    "boast", "champion", "changeling", "companion", "conspire",
    "crew", "demonstrate", "echo", "enchant", "encore", "entwine",
    "epic", "equip", "exalted", "fabricate", "fading", "fear",
    "fortify", "frenzy", "fuse", "graft", "haunt", "hideaway",
    "horsemanship", "improvise", "infect", "intimidate", "jump-start",
    "level up", "living weapon", "manifest", "melee", "modular",
    "mutate", "myriad", "ninjutsu", "offering", "outlast", "partner",
    "persist", "poisonous", "protection", "provoke", "rampage",
    "renown", "replicate", "retrace", "ripple", "shroud", "soulbond",
    "soulshift", "spectacle", "splice", "substance", "support",
    "totem armor", "training", "tribute", "unleash", "vanishing",
    "wither",
}


def _detect_keywords(text: str) -> list[str]:
    text_l = text.lower()
    found: list[str] = []
    for kw in _KEYWORD_INTERACTION:
        if re.search(rf"\b{re.escape(kw)}\b", text_l):
            found.append(kw)
    return sorted(set(found))


_ALT_COST_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"evoke\s*(?:—|-)\s*([^.]+?)(?=\.|$)", re.I), "evoke"),
    (re.compile(r"evoke\s+((?:\{[^}]+\}\s*)+)", re.I), "evoke"),
    (re.compile(r"dash\s+((?:\{[^}]+\}\s*)+)", re.I), "dash"),
    (re.compile(r"suspend\s+(\d+)\s*(?:—|-)\s*((?:\{[^}]+\}\s*)+)", re.I), "suspend"),
    (re.compile(r"flashback\s+((?:\{[^}]+\}\s*)+)", re.I), "flashback"),
    (re.compile(r"flashback\s*(?:—|-)\s*([^.]+?)(?=\.|$)", re.I), "flashback"),
    (re.compile(r"channel\s*(?:—|-)\s*([^.]+?)(?=\.|$)", re.I), "channel"),
    (re.compile(r"cycling\s+((?:\{[^}]+\}\s*)+)", re.I), "cycling"),
    (re.compile(r"kicker\s+((?:\{[^}]+\}\s*)+)", re.I), "kicker"),
    (re.compile(r"escape\s*(?:—|-)\s*([^.]+?)(?=\.|$)", re.I), "escape"),
    (re.compile(r"\bcascade\b", re.I), "cascade"),
    (re.compile(r"\bdelve\b", re.I), "delve"),
    (re.compile(r"\bconvoke\b", re.I), "convoke"),
    (re.compile(r"\bimprovise\b", re.I), "improvise"),
]


def detect_alt_costs(oracle_text: str) -> list[str]:
    """Pull alternate-cost mechanics (Evoke, Suspend, Dash, etc.) out of text.

    Modern depends heavily on these — Suspend changes effective turn-cost,
    Evoke gives a discount with a downside, Cascade enables free spells.
    Returned strings are formatted ``mechanic`` or ``mechanic:cost``.
    """
    found: list[str] = []
    seen: set[str] = set()
    for pat, mechanic in _ALT_COST_PATTERNS:
        for m in pat.finditer(oracle_text):
            tail = m.group(1).strip() if m.groups() else ""
            tail2 = m.group(2).strip() if len(m.groups()) >= 2 else ""
            if mechanic == "suspend" and tail2:
                token = f"suspend:{tail}:{tail2}"
            elif tail:
                token = f"{mechanic}:{tail}"
            else:
                token = mechanic
            if token not in seen:
                seen.add(token)
                found.append(token)
    return found


def parse_oracle_text(oracle_text: str, name: str | None = None) -> tuple[list[Effect], float, list[str]]:
    """Parse a card's oracle text into a structured Effect list.

    Returns ``(effects, coverage, residual_clauses)``. ``coverage`` is the
    fraction of clauses that produced at least one structured action; the
    ``residual_clauses`` list contains clauses that produced no actions
    and were not pure flavor.
    """
    if not oracle_text or not oracle_text.strip():
        return [], 1.0, []

    text = _replace_self(oracle_text, name)
    text = re.sub(r"\([^)]*\)", "", text)  # strip reminder text
    sentences = _split_sentences(text)
    if not sentences:
        return [], 1.0, []

    effects: list[Effect] = []
    residual: list[str] = []
    parsed = 0
    for sentence in sentences:
        flat = " ".join(sentence.split())
        if not flat:
            continue
        trigger, body = _detect_trigger(flat)
        actions = _extract_actions(body)
        cost: str | None = None
        if trigger == "activated":
            cost_match = re.match(r"^(\{[^}]+\}(?:\s*,\s*\{[^}]+\})*)\s*:", flat)
            if cost_match:
                cost = cost_match.group(1)
        if actions:
            parsed += 1
        else:
            keyword_only = _detect_keywords(flat)
            if keyword_only:
                actions = [Action(kind="uncategorized", text=", ".join(keyword_only))]
                parsed += 1
            else:
                residual.append(flat)
        conditional = bool(re.search(r"\bif\b|\bunless\b|\bwhile\b", flat, re.I))
        effects.append(
            Effect(
                trigger=trigger,
                cost=cost,
                actions=actions,
                text=flat,
                conditional=conditional,
            )
        )

    total = max(1, len(sentences))
    coverage = parsed / total
    return effects, coverage, residual


def iter_actions(effects: Iterable[Effect]) -> Iterable[Action]:
    for eff in effects:
        for a in eff.actions:
            yield a
