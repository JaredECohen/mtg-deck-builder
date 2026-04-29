"""Convert a parsed oracle AST into a :class:`CardProfile`.

This module is *deterministic* — given an Effect list and a card record,
the same vectors come out every time. No model in the loop. Designed
so the simulator (Phase 2+) and optimizer (Phase 5) can rely on it as
the single source of truth for card features.
"""

from __future__ import annotations

import re
from typing import Iterable

from app.oracle.cost_parser import parse_mana_cost
from app.oracle.parser import detect_alt_costs, iter_actions, parse_oracle_text
from app.oracle.profile import (
    PROFILE_VERSION,
    Action,
    CardProfile,
    ComboPrimitives,
    Effect,
    EffectVector,
    InteractionWindow,
    RoleWeights,
)


_LAND_TYPE_RE = re.compile(r"\bland\b", re.I)
_CREATURE_TYPE_RE = re.compile(r"\bcreature\b", re.I)
_INSTANT_RE = re.compile(r"\binstant\b", re.I)
_SORCERY_RE = re.compile(r"\bsorcery\b", re.I)
_PLANESWALKER_RE = re.compile(r"\bplaneswalker\b", re.I)


def _interaction_window(type_line: str, has_flash: bool) -> InteractionWindow:
    if _LAND_TYPE_RE.search(type_line):
        return "static"
    if _INSTANT_RE.search(type_line) or has_flash:
        return "instant"
    if _SORCERY_RE.search(type_line):
        return "sorcery"
    if _CREATURE_TYPE_RE.search(type_line) or _PLANESWALKER_RE.search(type_line):
        return "permanent"
    return "permanent"


def _normalize_pt(card: dict) -> tuple[float, float]:
    p = card.get("power")
    t = card.get("toughness")
    try:
        power = float(p) if p not in (None, "") else 0.0
    except ValueError:
        power = 0.0
    try:
        tough = float(t) if t not in (None, "") else 0.0
    except ValueError:
        tough = 0.0
    return power, tough


def _aggregate_effects(effects: list[Effect], card: dict) -> EffectVector:
    vec = EffectVector()
    type_line = card.get("type_line", "") or ""
    keywords = " ".join(card.get("keywords") or []).lower() + " " + (card.get("oracle_text") or "").lower()
    has_flash = "flash" in keywords
    vec.interaction_window = _interaction_window(type_line, has_flash)

    for action in iter_actions(effects):
        q = action.quantity or 0.0
        if action.kind == "draw":
            vec.cards_drawn += q
            vec.ca_delta += q
        elif action.kind == "damage":
            vec.damage_dealt += q
            if action.target and "any target" in action.target:
                vec.targets_creatures = True
                vec.targets_players = True
            elif action.target and "creature" in action.target:
                vec.targets_creatures = True
                vec.board_impact += q
            elif action.target and ("player" in action.target or "opponent" in action.target):
                vec.targets_players = True
            vec.removal_scope.append("damage")
        elif action.kind == "destroy":
            vec.board_impact += 2.0 if "creature" in (action.target or "") else 1.5
            vec.removal_scope.append(action.target or "permanent")
            if "creature" in (action.target or ""):
                vec.targets_creatures = True
            vec.targets_permanents = True
        elif action.kind == "exile":
            vec.board_impact += 2.5
            vec.removal_scope.append(action.target or "exile")
            vec.targets_permanents = True
        elif action.kind == "counter":
            vec.is_counterspell = True
            vec.tempo_delta += 2.5
            vec.removal_scope.append("stack")
        elif action.kind == "create_token":
            vec.creatures_made += q
            vec.board_impact += q * 1.0
        elif action.kind in {"treasure", "food", "blood", "clue"}:
            vec.mana_produced += q if action.kind == "treasure" else 0.0
            vec.tempo_delta += q * 0.5
        elif action.kind == "add_mana":
            vec.mana_produced += q
            vec.tempo_delta += q
        elif action.kind == "mill":
            vec.cards_milled += q
        elif action.kind == "discard":
            vec.ca_delta -= q if action.target == "you" else 0.0
            if action.target != "you":
                vec.tempo_delta += q
        elif action.kind == "tutor":
            vec.is_tutor = True
            vec.ca_delta += 0.8
        elif action.kind == "gain_life":
            vec.life_gained += q
        elif action.kind == "lose_life":
            vec.life_lost += q
            vec.damage_dealt += q * 0.5
        elif action.kind == "pump":
            vec.board_impact += q
        elif action.kind == "scry":
            vec.ca_delta += q * 0.2
        elif action.kind == "surveil":
            vec.ca_delta += q * 0.25
        elif action.kind == "return_to_hand":
            vec.tempo_delta += 1.5
            vec.targets_permanents = True
        elif action.kind == "copy_spell":
            vec.tempo_delta += 1.0
            vec.ca_delta += 0.5
        elif action.kind == "win_game":
            vec.closes_game = True
            vec.is_combo_payoff = True
        elif action.kind == "extra_turn":
            vec.closes_game = True
            vec.tempo_delta += 6.0
        elif action.kind == "investigate":
            vec.ca_delta += 0.6

    if _CREATURE_TYPE_RE.search(type_line):
        power, tough = _normalize_pt(card)
        cmc = float(card.get("mana_value") or 0)
        if power == 0 and tough == 0 and cmc > 0:
            # Sample data lacks P/T; assume baseline ~ cmc-vanilla curve.
            power = max(1.0, cmc - 0.5)
            tough = max(1.0, cmc - 0.5)
        vec.board_impact += power + 0.4 * tough

    if any(a.kind == "damage" and a.quantity and a.quantity >= 6 for a in iter_actions(effects)):
        vec.closes_game = True

    speed_bonus = {"instant": 1.0, "permanent": 0.5, "sorcery": 0.0, "static": 0.2, "activated": 0.3, "triggered": 0.4}
    vec.speed_score = speed_bonus.get(vec.interaction_window, 0.0)
    vec.removal_scope = sorted(set(vec.removal_scope))
    return vec


def _derive_roles(card: dict, effects: list[Effect], vec: EffectVector) -> RoleWeights:
    roles = RoleWeights()
    type_line = (card.get("type_line") or "").lower()

    if "land" in type_line:
        roles.land = 1.0
        return roles

    if vec.is_tutor:
        roles.tutor += 1.0
    if vec.is_counterspell:
        roles.disruption += 0.7
        roles.removal += 0.4
    if vec.removal_scope and any(r in {"creature", "permanent", "exile", "damage"} for r in vec.removal_scope):
        if "creature" in vec.removal_scope or vec.targets_creatures:
            roles.removal += 0.7
        if any(r in {"permanent", "exile"} for r in vec.removal_scope):
            roles.removal += 0.5
    if vec.cards_drawn >= 1 or vec.ca_delta >= 1:
        roles.value_engine += min(1.0, vec.ca_delta / 2.0)
    if vec.mana_produced >= 1:
        roles.fixer += min(1.0, vec.mana_produced / 2.0)
    if vec.creatures_made >= 1 or vec.board_impact >= 3:
        roles.threat += min(1.0, (vec.creatures_made + vec.board_impact / 3.0) / 2.0)
    if vec.closes_game:
        roles.closer += 0.8
    if vec.tempo_delta >= 1.5:
        roles.disruption += 0.4
    if any("hexproof" in (a.text.lower() if a.text else "") or "indestructible" in (a.text.lower() if a.text else "") for a in iter_actions(effects)):
        roles.protection += 0.6
    if "creature" in type_line:
        roles.threat += min(0.8, 0.3 + 0.15 * vec.board_impact)
    has_pump = any(a.kind == "pump" for eff in effects for a in eff.actions)
    if has_pump and ("instant" in type_line or "sorcery" in type_line):
        roles.enabler += 0.5
        roles.threat += 0.2
    if any(eff.trigger in {"cast_trigger", "cast_noncreature", "cast_instant_or_sorcery"} for eff in effects):
        roles.payoff += 0.6
        roles.enabler += 0.2
    if any(eff.trigger == "etb" for eff in effects) and vec.ca_delta >= 1:
        roles.value_engine += 0.4
    text_l = (card.get("oracle_text") or "").lower()
    keyword_blob = " ".join((card.get("keywords") or []) + [text_l]).lower()
    if any(k in keyword_blob for k in ("haste", "prowess")):
        roles.threat += 0.3
    if "flying" in keyword_blob:
        roles.threat += 0.15
    if "hexproof" in keyword_blob or "indestructible" in keyword_blob or "ward" in keyword_blob:
        roles.protection += 0.4
    if "ramp" in (card.get("tags") or []):
        roles.fixer += 0.4
    if "draw" in (card.get("tags") or []):
        roles.value_engine += 0.4
    if "interaction" in (card.get("tags") or []):
        roles.removal += 0.3

    # Type-based floor: every non-land card gets *some* role weight so
    # downstream comparators never see a zero vector. Floor reflects the
    # default expectation for the card's primary type.
    if not any(roles.to_dict().values()):
        if "instant" in type_line or "sorcery" in type_line:
            roles.enabler = 1.0
        elif "creature" in type_line:
            roles.threat = 1.0
        elif "planeswalker" in type_line:
            roles.value_engine = 1.0
        elif "artifact" in type_line or "enchantment" in type_line:
            roles.value_engine = 1.0
        else:
            roles.enabler = 1.0

    return roles.normalize()


def _derive_combo(effects: list[Effect], card: dict) -> ComboPrimitives:
    triggers: list[str] = []
    produces: list[str] = []
    requires: list[str] = []
    keyword_set: set[str] = set()
    for eff in effects:
        if eff.trigger and eff.trigger != "none":
            triggers.append(eff.trigger)
        for action in eff.actions:
            if action.kind == "treasure":
                produces.append("mana_treasure")
            elif action.kind == "add_mana":
                produces.append("mana")
            elif action.kind == "create_token":
                produces.append("creature_token")
            elif action.kind == "draw":
                produces.append("card_advantage")
            elif action.kind == "damage" and action.quantity and action.quantity >= 1:
                produces.append("damage")
            elif action.kind == "tutor":
                produces.append("tutored_card")
            elif action.kind == "win_game":
                produces.append("game_win")
            elif action.kind == "extra_turn":
                produces.append("extra_turn")
            elif action.kind == "mill":
                produces.append("graveyard_fill")
            elif action.kind == "uncategorized" and action.text:
                for token in re.split(r"[,;]\s*|\s{2,}", action.text):
                    token = token.strip().lower()
                    if token:
                        keyword_set.add(token)
        if eff.conditional:
            requires.append("conditional")
    text_l = (card.get("oracle_text") or "").lower()
    if "graveyard" in text_l and ("from your graveyard" in text_l or "from a graveyard" in text_l):
        requires.append("graveyard_present")
    if "sacrifice" in text_l and "sacrifice another" not in text_l:
        requires.append("sacrifice_outlet")
    if "untap" in text_l and "untap target" in text_l:
        produces.append("untap")
    for kw in card.get("keywords") or []:
        keyword_set.add(str(kw).lower())
    return ComboPrimitives(
        triggers=sorted(set(triggers)),
        produces=sorted(set(produces)),
        requires=sorted(set(requires)),
        keywords=sorted(keyword_set),
    )


def build_card_profile(card: dict) -> CardProfile:
    """Build a CardProfile from a card record.

    ``card`` is a dict with at least: ``name``, ``mana_cost``, ``mana_value``,
    ``type_line``, ``oracle_text``, ``keywords``, ``tags``. Optional:
    ``power``, ``toughness``, ``oracle_id``, ``scryfall_id``.
    """
    name = card.get("name") or ""
    text = card.get("oracle_text") or ""
    type_line = (card.get("type_line") or "").lower()

    cost_vector = parse_mana_cost(card.get("mana_cost") or "")
    if not cost_vector.cmc and card.get("mana_value"):
        cost_vector.cmc = float(card["mana_value"])

    alt_costs = detect_alt_costs(text)
    for alt in alt_costs:
        if alt not in cost_vector.alt_costs:
            cost_vector.alt_costs.append(alt)

    if "land" in type_line:
        effects: list[Effect] = []
        coverage = 1.0
        residual: list[str] = []
    else:
        effects, coverage, residual = parse_oracle_text(text, name=name)

    effect_vector = _aggregate_effects(effects, card)
    role_weights = _derive_roles(card, effects, effect_vector)
    combos = _derive_combo(effects, card)

    profile = CardProfile(
        card_id=card.get("oracle_id") or card.get("scryfall_id") or name,
        name=name,
        cost_vector=cost_vector,
        effect_vector=effect_vector,
        role_weights=role_weights,
        combo_primitives=combos,
        oracle_ast=effects,
        profile_version=PROFILE_VERSION,
        parse_method="pattern" if coverage >= 0.5 else "fallback",
        parse_coverage=coverage,
        notes=[f"residual: {r}" for r in residual[:5]],
    )
    return profile


def build_card_profile_batch(cards: Iterable[dict]) -> list[CardProfile]:
    return [build_card_profile(c) for c in cards]
