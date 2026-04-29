---
name: card-evaluator
description: Convert an MTG card into a strict CardProfile JSON object. Use when oracle text fails the deterministic pattern parser (parse_coverage < 0.5) or contains ambiguous language. The output is committed to the card_profiles DB table and reused forever — accuracy matters.
version: 1
---

# Card Evaluator

You receive one card at a time and must emit a single JSON object matching
the `CardProfile` schema below. **No prose, no preamble, no trailing commas.**

## Input
A JSON object with these fields:
- `name` (string)
- `mana_cost` (string, e.g. `"{2}{R}"`)
- `mana_value` (number)
- `type_line` (string)
- `oracle_text` (string)
- `keywords` (array of strings)
- `tags` (array of strings)
- `power`, `toughness` (optional, strings or numbers)
- `colors`, `color_identity` (arrays)
- `residual_clauses` (array of strings) — clauses the deterministic parser
  could not handle. Focus your reasoning here. Other clauses already
  produced structured actions; do not re-extract them.

## Output schema

```json
{
  "card_id": "<oracle_id-or-name>",
  "name": "<name>",
  "cost_vector": {
    "generic": <int>,
    "pips": {"W": <int>, "U": <int>, "B": <int>, "R": <int>, "G": <int>, "C": <int>, "X": <int>},
    "alt_costs": ["phyrexian:R", "cycling:2", "flashback:2R", "kicker:1U"],
    "additional_costs": ["sacrifice_creature", "discard_card", "pay_2_life"],
    "cmc": <number>,
    "pip_intensity": <number>,
    "color_demand": {"W": <number>, ...}
  },
  "effect_vector": {
    "ca_delta": <number>,           // net cards drawn − cards spent on self
    "tempo_delta": <number>,         // mana denied/produced relative to cost
    "board_impact": <number>,        // expected P+T or removal magnitude
    "removal_scope": ["creature", "permanent", "exile", "stack", "damage", "graveyard"],
    "damage_dealt": <number>,
    "life_gained": <number>,
    "life_lost": <number>,
    "cards_drawn": <number>,
    "cards_milled": <number>,
    "creatures_made": <number>,
    "mana_produced": <number>,
    "interaction_window": "instant" | "sorcery" | "static" | "permanent" | "activated" | "triggered",
    "speed_score": <0.0–1.0>,
    "targets_creatures": <bool>,
    "targets_permanents": <bool>,
    "targets_players": <bool>,
    "targets_graveyard": <bool>,
    "is_counterspell": <bool>,
    "is_tutor": <bool>,
    "is_combo_payoff": <bool>,
    "closes_game": <bool>
  },
  "role_weights": {
    "closer": <0–1>, "threat": <0–1>, "enabler": <0–1>, "payoff": <0–1>,
    "disruption": <0–1>, "removal": <0–1>, "fixer": <0–1>,
    "value_engine": <0–1>, "tutor": <0–1>, "protection": <0–1>, "land": <0–1>
  },
  "combo_primitives": {
    "triggers": ["etb", "cast_noncreature", ...],
    "produces": ["mana", "card_advantage", "creature_token", "damage", "untap", ...],
    "requires": ["graveyard_present", "sacrifice_outlet", ...],
    "keywords": ["flash", "haste", ...]
  },
  "oracle_ast": [
    { "trigger": "etb" | "none" | ..., "cost": null | "{2}{R}",
      "actions": [{ "kind": "draw" | "damage" | "destroy" | ..., "quantity": <number>, "target": "creature" | null, "text": "..." }],
      "text": "<original clause>", "conditional": <bool> }
  ],
  "profile_version": 1,
  "parse_method": "skill",
  "parse_coverage": <0–1>,
  "notes": ["<short caveats, e.g. 'storm count interpretation: 1 spell baseline'>"]
}
```

## Rules

1. **Be conservative on `closes_game`**: only `true` if the card alone wins
   (e.g., Approach of the Second Sun) or directly enables a game-winning
   loop (e.g., Splinter Twin half).
2. **`role_weights` must sum to ≤ 1.0** for non-land cards. Land cards
   set `land=1.0` and zero everything else.
3. For modal cards (Adventures, MDFCs, modal spells), aggregate the
   *most often used* mode's effects and note the alternates in `notes`.
4. For X-cost spells, evaluate at `X=2` unless the card text directly
   implies a larger X is the intended use.
5. For triggered abilities that depend on game state ("if you control a…"),
   set `conditional=true` and apply a 0.5 expected-value multiplier to
   that effect's contribution.
6. For Modern-relevant alternate costs (cascade, evoke, suspend, escape,
   delve, flashback, kicker), include them in `alt_costs` with their
   pip cost: e.g., `"flashback:2R"`, `"evoke:R"`.
7. Keywords with hidden mechanical impact (haste, flash, prowess) must
   appear in `combo_primitives.keywords`.
8. Don't invent effects. If oracle text is unclear, raise `parse_coverage`
   only as far as the clauses you confidently parsed.

## Examples

Input fragment: `Splinter Twin — Enchant creature. Enchanted creature has "{T}: Create a token that's a copy of this creature, except it has haste. Exile that token at the beginning of the next end step."`

Set `closes_game: true`, `is_combo_payoff: true`, `combo_primitives.produces: ["creature_token", "untap_synergy"]`, `requires: ["untappable_creature"]`, `role_weights.payoff: 0.7, closer: 0.3`.

Input fragment: `Cascade — When you cast this spell, exile cards from the top of your library until you exile a nonland card with mana value less than this spell's…`

Add `cascade` to `alt_costs` if it's the alternate cost; otherwise add to `combo_primitives.produces: ["free_spell"]`. Note in `notes` the average expected value (≈ +1.0 ca_delta).

## Output

Return **only** the JSON object. No backticks, no markdown, no explanation.
