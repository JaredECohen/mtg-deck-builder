from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any

import anthropic
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── In-process LRU cache for LLM enrichment ──────────────────────────────────
# Same deck (same cards, role mix, archetype, format, commander) re-analyzed
# back-to-back hits the cache instead of paying the LLM round-trip again.
_ENRICHMENT_CACHE_MAX = 256
_ENRICHMENT_CACHE_TTL_SEC = 30 * 60  # 30 minutes — enough for an interactive session
_enrichment_cache: "OrderedDict[str, tuple[float, dict[str, Any]]]" = OrderedDict()
_enrichment_cache_lock = threading.Lock()


def _enrichment_cache_get(key: str) -> dict[str, Any] | None:
    with _enrichment_cache_lock:
        entry = _enrichment_cache.get(key)
        if entry is None:
            return None
        timestamp, value = entry
        if time.monotonic() - timestamp > _ENRICHMENT_CACHE_TTL_SEC:
            _enrichment_cache.pop(key, None)
            return None
        _enrichment_cache.move_to_end(key)
        return value


def _enrichment_cache_put(key: str, value: dict[str, Any]) -> None:
    with _enrichment_cache_lock:
        _enrichment_cache[key] = (time.monotonic(), value)
        _enrichment_cache.move_to_end(key)
        while len(_enrichment_cache) > _ENRICHMENT_CACHE_MAX:
            _enrichment_cache.popitem(last=False)

# Single ANTHROPIC_MODEL var controls both paths; ANTHROPIC_FAST_MODEL /
# ANTHROPIC_ANALYSIS_MODEL still let you override one path at a time. Default
# is Sonnet 4.6 — current-gen with the best price/intelligence for both
# structured extraction and richer deck analysis.
_DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
_FAST_MODEL = os.getenv("ANTHROPIC_FAST_MODEL", _DEFAULT_MODEL)
_ANALYSIS_MODEL = os.getenv("ANTHROPIC_ANALYSIS_MODEL", _DEFAULT_MODEL)

_client: anthropic.Anthropic | None = None
_client_lock = threading.Lock()


def _get_client() -> anthropic.Anthropic | None:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                key = os.getenv("ANTHROPIC_API_KEY")
                if key:
                    _client = anthropic.Anthropic(api_key=key)
    return _client


def _extract_json(response: anthropic.types.Message) -> dict[str, Any]:
    """Pull JSON from a Claude response, stripping markdown fences if present."""
    if not response.content:
        raise ValueError("Empty response content from API")
    block = response.content[0]
    if block.type != "text":
        raise ValueError(f"Expected text block, got {block.type}")
    raw = block.text.strip()
    # Strip optional ```json ... ``` or ``` ... ``` fences
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]
    return json.loads(raw)


# ── Refinement intent extraction ──────────────────────────────────────────────

class RefinementIntent(BaseModel):
    budget: float | None = None
    scale_budget_by: float | None = None
    add_playstyle_tags: list[str] = []
    remove_playstyle_tags: list[str] = []
    include_cards: list[str] = []
    exclude_cards: list[str] = []
    color_changes: list[str] = []


_REFINE_SYSTEM = """You are an MTG deck-building assistant.
Extract the player's refinement intent from their prompt. Return ONLY valid JSON — no prose, no markdown.

Schema:
{
  "budget": <number | null>,
  "scale_budget_by": <number | null>,
  "add_playstyle_tags": [...],
  "remove_playstyle_tags": [...],
  "include_cards": [...],
  "exclude_cards": [...],
  "color_changes": [...]
}

Rules:
- budget: absolute USD cap if explicitly stated ("$50 budget" → 50.0)
- scale_budget_by: multiplier for relative cost requests ("cheaper" → 0.7, "much cheaper" → 0.5, "more expensive/upgrade" → null)
- Valid playstyle tags: aggro, control, midrange, combo, tempo, ramp, spells, tokens, tribal, lifegain, graveyard, sacrifice, interactive, prowess
- color_changes: WUBRG letters to add ("add blue" → ["U"])
- include_cards / exclude_cards: exact card names the player mentions
- Return null / empty array for anything not mentioned"""


def interpret_refinement(prompt: str) -> RefinementIntent:
    """Extract structured refinement intent from a natural-language prompt.

    Falls back to keyword matching on any failure so the refine flow never breaks.
    """
    client = _get_client()
    if not client or not prompt.strip():
        return _keyword_fallback(prompt)
    try:
        response = client.messages.create(
            model=_FAST_MODEL,
            max_tokens=512,
            system=[{"type": "text", "text": _REFINE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )
        data: dict[str, Any] = _extract_json(response)
        return RefinementIntent.model_validate(data)
    except Exception:
        logger.warning("LLM refinement extraction failed; using keyword fallback", exc_info=True)
        return _keyword_fallback(prompt)


def _keyword_fallback(prompt: str) -> RefinementIntent:
    lower = prompt.lower()
    tags = [
        tag for tag in (
            "aggro", "control", "midrange", "combo", "tempo", "ramp",
            "spells", "tokens", "tribal", "lifegain", "graveyard", "sacrifice",
        )
        if tag in lower
    ]
    if any(t in lower for t in ("interactive", "interaction", "removal")):
        tags.append("control")
    scale = 0.7 if any(t in lower for t in ("budget", "cheap", "cheaper")) else None
    return RefinementIntent(add_playstyle_tags=tags, scale_budget_by=scale)


# ── Generate prompt intent extraction ─────────────────────────────────────────

class GeneratePromptIntent(BaseModel):
    colors: list[str] = []
    playstyle_tags: list[str] = []
    theme_tags: list[str] = []
    budget: float | None = None
    commander_name: str | None = None
    include_cards: list[str] = []
    exclude_cards: list[str] = []


_GENERATE_SYSTEM = """You are an MTG deck-building assistant.
Extract deck constraints from the player's free-text prompt. Return ONLY valid JSON — no prose, no markdown.

Schema:
{
  "colors": [...],
  "playstyle_tags": [...],
  "theme_tags": [...],
  "budget": <number | null>,
  "commander_name": <string | null>,
  "include_cards": [...],
  "exclude_cards": [...]
}

Rules:
- colors: WUBRG letters ("blue-red" → ["U","R"], "Jeskai" → ["W","U","R"], "mono-green" → ["G"])
- Valid playstyle tags: aggro, control, midrange, combo, tempo, ramp, spells, tokens, tribal, lifegain, graveyard, sacrifice
- theme_tags: specific mechanics or tribes ("prowess", "slivers", "dragons", "aristocrats", "storm")
- budget: USD amount if stated
- commander_name: full card name only if this is a Commander deck and a specific commander is mentioned
- Return empty arrays / null for omitted fields"""


def interpret_generate_prompt(prompt: str) -> GeneratePromptIntent:
    """Extract structured deck constraints from a free-text generation prompt."""
    client = _get_client()
    if not client or not prompt.strip():
        return GeneratePromptIntent()
    try:
        response = client.messages.create(
            model=_FAST_MODEL,
            max_tokens=512,
            system=[{"type": "text", "text": _GENERATE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )
        data: dict[str, Any] = _extract_json(response)
        return GeneratePromptIntent.model_validate(data)
    except Exception:
        logger.warning("LLM generate prompt interpretation failed; ignoring prompt", exc_info=True)
        return GeneratePromptIntent()


# ── Deck analysis enrichment ───────────────────────────────────────────────────

class DeckEnrichment(BaseModel):
    game_plan_summary: str
    play_pattern_summary: str
    ai_coaching_note: str
    strengths: list[str] = []
    weaknesses: list[str] = []


_ANALYSIS_SYSTEM = """You are an expert Magic: The Gathering deck analyst with deep knowledge of competitive formats.
Analyze the provided deck and return ONLY valid JSON — no prose, no markdown fences.

Schema:
{
  "game_plan_summary": "<2-3 sentences: what the deck is trying to do, its win conditions, and core strategy>",
  "play_pattern_summary": "<2-3 sentences: how the deck plays turn by turn, what it does in the early/mid/late game>",
  "ai_coaching_note": "<exactly 3 numbered lines (1. ... 2. ... 3. ...) — the highest-impact changes the pilot should make next, each referencing specific cards or categories>",
  "strengths": ["<concrete strength, reference actual cards>", ...],
  "weaknesses": ["<concrete weakness or vulnerability>", ...]
}

Be specific. Reference actual cards from the list. Focus on what a player needs to know to win more games.
Keep strengths and weaknesses to 2-4 items each. The coaching note should prioritize the single most impactful change first."""


# ── Blend refinement (LLM curates a hybrid anchor list) ──────────────────────

_BLEND_SYSTEM = """You are an expert Magic: The Gathering deckbuilder.

The user wants to blend multiple archetypes into one deck. You'll receive:
  • Format, color identity, optional budget
  • The user's free-text brief
  • Each matched archetype's display name + canonical anchor card list

Your job: produce a single coherent anchor card list that pulls the best parts of each archetype while making a deck that actually functions. You're seeding the deck — the host system will fill flex slots and lands afterward, so focus on the CORE 24–34 cards that define the blend's identity.

Principles:
  • Pick threats and payoffs from each archetype; cut redundancies.
  • Keep the curve playable — don't load 30 5-mana cards.
  • Honor format legality (you'll be told the format; don't suggest cards illegal there).
  • Respect color identity. If the blend's colors don't support a card from one of the archetypes, drop it.
  • If a budget is given, prefer cheaper alternatives where they exist.
  • Don't add cards that aren't in either input list unless they're an obvious bridge card that ties the archetypes together (e.g. "Lightning Helix" bridging Burn + Lifegain). Limit bridges to 4 cards max.
  • Quantity per card: 1–4 for constructed, 1 for commander.
  • Total card count: 24–34 cards.

Return ONLY valid JSON — no prose, no markdown fences:

{
  "blended_strategy": "<2-3 sentence game plan for the hybrid>",
  "anchor_cards": [
    {"name": "<exact card name>", "quantity": <int>},
    ...
  ]
}"""


class BlendRefinement(BaseModel):
    blended_strategy: str
    anchor_cards: list[dict[str, Any]]


_blend_cache: "OrderedDict[str, tuple[float, dict[str, Any]]]" = OrderedDict()
_blend_cache_lock = threading.Lock()
_BLEND_CACHE_TTL_SEC = 30 * 60
_BLEND_CACHE_MAX = 128


def _blend_cache_get(key: str) -> dict[str, Any] | None:
    with _blend_cache_lock:
        entry = _blend_cache.get(key)
        if entry is None:
            return None
        timestamp, value = entry
        if time.monotonic() - timestamp > _BLEND_CACHE_TTL_SEC:
            _blend_cache.pop(key, None)
            return None
        _blend_cache.move_to_end(key)
        return value


def _blend_cache_put(key: str, value: dict[str, Any]) -> None:
    with _blend_cache_lock:
        _blend_cache[key] = (time.monotonic(), value)
        _blend_cache.move_to_end(key)
        while len(_blend_cache) > _BLEND_CACHE_MAX:
            _blend_cache.popitem(last=False)


def refine_blend(
    *,
    matched_archetypes: list[dict[str, Any]],
    format_name: str,
    colors: list[str],
    budget: float | None,
    user_brief: str,
) -> dict[str, Any] | None:
    """LLM-refine the anchor card list for a multi-archetype blend.

    Returns {"blended_strategy": str, "anchor_cards": [(name, qty), ...]} on
    success, or None when:
      • Fewer than 2 archetypes matched (no blending needed; caller uses the
        deterministic single-archetype path).
      • API key absent or LLM call failed (caller falls back to the
        deterministic blend in builtin_archetypes.blend_archetypes).

    Each matched_archetypes entry is a dict with keys:
      • display_name (str)
      • anchor_cards: list[(name, qty)] tuples or list of dicts

    Results are cached for 30 minutes keyed by inputs so a refresh / repeat
    of the same blend reuses the previous call.
    """
    if len(matched_archetypes) < 2:
        return None
    client = _get_client()
    if not client:
        return None

    archetypes_block = []
    for arch in matched_archetypes:
        name = arch.get("display_name", "Unknown")
        anchors = arch.get("anchor_cards", [])
        lines = [f"  - {qty}x {card_name}" for card_name, qty in anchors if qty > 0]
        archetypes_block.append(f"## {name}\n" + "\n".join(lines))
    archetypes_text = "\n\n".join(archetypes_block)

    user_content = (
        f"Format: {format_name}\n"
        f"Color identity: {','.join(colors) or '(unspecified, default to blend union)'}\n"
        f"Budget (USD): {budget if budget is not None else 'no cap'}\n"
        f"\nUser brief: {user_brief or '(none)'}\n"
        f"\nMatched archetypes:\n\n{archetypes_text}"
    )

    cache_key = hashlib.sha256(
        f"{_FAST_MODEL}\n{user_content}".encode("utf-8")
    ).hexdigest()
    cached = _blend_cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        response = client.messages.create(
            model=_FAST_MODEL,
            max_tokens=1024,
            system=[
                {"type": "text", "text": _BLEND_SYSTEM, "cache_control": {"type": "ephemeral"}},
            ],
            messages=[{"role": "user", "content": user_content}],
        )
        data = _extract_json(response)
        validated = BlendRefinement.model_validate(data)
        cards: list[tuple[str, int]] = []
        for entry in validated.anchor_cards:
            name = str(entry.get("name", "")).strip()
            try:
                qty = int(entry.get("quantity", 0))
            except (TypeError, ValueError):
                qty = 0
            if name and qty > 0:
                cards.append((name, qty))
        result = {
            "blended_strategy": validated.blended_strategy.strip(),
            "anchor_cards": cards,
        }
        _blend_cache_put(cache_key, result)
        return result
    except Exception:
        logger.warning("LLM blend refinement failed; caller will fall back to deterministic blend", exc_info=True)
        return None


# ── Compose-from-scratch fallback ────────────────────────────────────────────

_COMPOSE_SYSTEM = """You are an expert Magic: The Gathering deckbuilder.

The user has asked for a deck and the system did NOT match any known
archetype. Rather than fall back to a near-miss corpus shell, you'll
compose a complete anchor card list from scratch.

Input:
  • Format, color identity, optional budget
  • The user's free-text brief
  • Optional list of nudges (playstyle / theme tags they prefer)

Output: 24–34 anchor cards forming a coherent strategy. The host system
fills lands and flex slots; you focus on the spine.

Principles:
  • Choose ONE strategy and commit. If the brief is ambiguous, pick the
    most-playable shape for the requested colors in the requested format.
  • Use real cards legal in the format. No alpha names, no fake cards.
  • Quantity per card: 1–4 for constructed (60-card), 1 for commander.
  • Curve must be playable — don't load up on 5+ mana cards.
  • Respect color identity strictly.
  • Honor budget if given (prefer cheap alternatives where they exist).

Return ONLY valid JSON — no prose, no markdown fences:

{
  "archetype_label": "<short name for the strategy you chose, e.g. 'BR Aggro', 'Mono-G Stompy'>",
  "strategy": "<2-3 sentence game plan>",
  "anchor_cards": [
    {"name": "<exact card name>", "quantity": <int>},
    ...
  ]
}"""


class ComposeFromScratch(BaseModel):
    archetype_label: str
    strategy: str
    anchor_cards: list[dict[str, Any]]


_compose_cache: "OrderedDict[str, tuple[float, dict[str, Any]]]" = OrderedDict()
_compose_cache_lock = threading.Lock()
_COMPOSE_CACHE_TTL_SEC = 30 * 60
_COMPOSE_CACHE_MAX = 64


def _compose_cache_get(key: str) -> dict[str, Any] | None:
    with _compose_cache_lock:
        entry = _compose_cache.get(key)
        if entry is None:
            return None
        timestamp, value = entry
        if time.monotonic() - timestamp > _COMPOSE_CACHE_TTL_SEC:
            _compose_cache.pop(key, None)
            return None
        _compose_cache.move_to_end(key)
        return value


def _compose_cache_put(key: str, value: dict[str, Any]) -> None:
    with _compose_cache_lock:
        _compose_cache[key] = (time.monotonic(), value)
        _compose_cache.move_to_end(key)
        while len(_compose_cache) > _COMPOSE_CACHE_MAX:
            _compose_cache.popitem(last=False)


_REFINE_COMPOSE_SYSTEM = """You are an expert Magic: The Gathering deckbuilder.

You'll receive a draft anchor card list (24–34 cards) from an earlier compose
pass. Your job: tighten it. Cut weak/off-curve cards, add 0–4 bridge cards
that make the strategy more cohesive, ensure the curve plays, and respect
color identity strictly. Keep the SAME ARCHETYPE — don't pivot strategies.

Return ONLY valid JSON, no prose, no markdown fences:

{
  "archetype_label": "<unchanged or sharpened label>",
  "strategy": "<2-3 sentences, slightly refined>",
  "anchor_cards": [
    {"name": "<exact card name>", "quantity": <int>},
    ...
  ]
}

Constraints:
  • 24–34 cards total. 1–4 quantity per card for constructed, 1 for commander.
  • Strict format legality. Strict color identity (subset of declared colors).
  • Don't strip the deck of its identity — refine, don't rewrite."""


def refine_compose(
    *,
    composed: dict[str, Any],
    format_name: str,
    colors: list[str],
    budget: float | None,
    user_brief: str,
) -> dict[str, Any] | None:
    """Polish a compose_from_scratch result with a second LLM pass. The
    compose pass is a cold-start cast that often includes redundant or
    slightly-off-curve cards; this second pass tightens the list.

    Returns the same dict shape as compose_from_scratch (archetype_label,
    strategy, anchor_cards) or None when the LLM is unavailable. The caller
    falls back to the original compose result on None.
    """
    client = _get_client()
    if not client:
        return None
    anchors = composed.get("anchor_cards", [])
    if not anchors:
        return None

    anchor_lines = "\n".join(f"  - {qty}x {name}" for name, qty in anchors if qty > 0)
    user_content = (
        f"Format: {format_name}\n"
        f"Color identity: {','.join(colors) or '(open)'}\n"
        f"Budget (USD): {budget if budget is not None else 'no cap'}\n"
        f"User brief: {user_brief or '(none provided)'}\n"
        f"\nDraft archetype: {composed.get('archetype_label', 'Composed')}\n"
        f"Draft strategy: {composed.get('strategy', '(none)')}\n"
        f"\nDraft anchor cards ({len(anchors)} entries):\n{anchor_lines}"
    )
    cache_key = hashlib.sha256(f"refine-compose\n{_FAST_MODEL}\n{user_content}".encode("utf-8")).hexdigest()
    cached = _compose_cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        response = client.messages.create(
            model=_FAST_MODEL,
            max_tokens=1024,
            system=[{"type": "text", "text": _REFINE_COMPOSE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_content}],
        )
        data = _extract_json(response)
        validated = ComposeFromScratch.model_validate(data)
        cards: list[tuple[str, int]] = []
        for entry in validated.anchor_cards:
            name = str(entry.get("name", "")).strip()
            try:
                qty = int(entry.get("quantity", 0))
            except (TypeError, ValueError):
                qty = 0
            if name and qty > 0:
                cards.append((name, qty))
        if not cards:
            return None
        result = {
            "archetype_label": validated.archetype_label.strip(),
            "strategy": validated.strategy.strip(),
            "anchor_cards": cards,
        }
        _compose_cache_put(cache_key, result)
        logger.info(
            "refine_compose tightened %d → %d cards (label='%s')",
            len(anchors), len(cards), result["archetype_label"],
        )
        return result
    except Exception:
        logger.warning("LLM refine_compose failed; caller will use the raw compose output", exc_info=True)
        return None


def compose_from_scratch(
    *,
    format_name: str,
    colors: list[str],
    playstyle_tags: list[str],
    theme_tags: list[str],
    budget: float | None,
    user_brief: str,
) -> dict[str, Any] | None:
    """When no builtin matched and the corpus has no good shell, ask Claude
    to compose ~30 anchor cards from scratch. Returns
    {"archetype_label": str, "strategy": str, "anchor_cards": [(name, qty), ...]}
    or None when LLM is unavailable. Caller still owns mana base + flex fill.

    Cached for 30 minutes keyed by the request shape so refreshes are free.
    """
    client = _get_client()
    if not client:
        return None

    user_content = (
        f"Format: {format_name}\n"
        f"Color identity: {','.join(colors) or '(open)'}\n"
        f"Budget (USD): {budget if budget is not None else 'no cap'}\n"
        f"Playstyle nudges: {', '.join(playstyle_tags) or '(none)'}\n"
        f"Theme nudges: {', '.join(theme_tags) or '(none)'}\n"
        f"\nUser brief: {user_brief or '(none provided)'}"
    )
    cache_key = hashlib.sha256(f"{_FAST_MODEL}\n{user_content}".encode("utf-8")).hexdigest()
    cached = _compose_cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        response = client.messages.create(
            model=_FAST_MODEL,
            max_tokens=1024,
            system=[{"type": "text", "text": _COMPOSE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_content}],
        )
        data = _extract_json(response)
        validated = ComposeFromScratch.model_validate(data)
        cards: list[tuple[str, int]] = []
        for entry in validated.anchor_cards:
            name = str(entry.get("name", "")).strip()
            try:
                qty = int(entry.get("quantity", 0))
            except (TypeError, ValueError):
                qty = 0
            if name and qty > 0:
                cards.append((name, qty))
        if not cards:
            return None
        result = {
            "archetype_label": validated.archetype_label.strip(),
            "strategy": validated.strategy.strip(),
            "anchor_cards": cards,
        }
        _compose_cache_put(cache_key, result)
        return result
    except Exception:
        logger.warning("LLM compose-from-scratch failed; falling through to corpus path", exc_info=True)
        return None


_CHAT_SYSTEM = """You are an expert Magic: The Gathering deck coach. The user has just been shown a generated decklist and wants to ask about it.

You will receive:
  • The current decklist (mainboard + sideboard) and metadata.
  • Recent chat turns (may be empty on the first message).
  • The user's new message.

Decide the user's intent on every turn:

  (A) Question / discussion → return a clear, deck-specific answer. Reference actual cards and counts. 2–6 sentences. Use plain prose, no markdown headers.

  (B) Deck-modification request ("swap X for Y", "make it cheaper", "more removal", "cut the artifacts", "add a sideboard plan against Tron", etc.) → return a short answer describing the proposed change AND a `suggested_refinement` string. The refinement string must be a self-contained, imperative instruction (≤200 chars) suitable for passing to a deck-refinement endpoint. Example: "Cut 4 Urn of Godfire, add 4 Lava Spike. Reduce total budget by 30%."

Return ONLY valid JSON, no prose, no markdown fences:

{
  "reply": "<your answer to the user, plain prose>",
  "suggested_refinement": "<imperative instruction OR null if this was Q&A>"
}

Rules:
  • Never invent cards that aren't in the decklist when answering questions about *this deck*.
  • Suggested refinements that name cards must use the exact card names.
  • If you're uncertain whether the user wants a change or just an explanation, default to (A) and leave suggested_refinement null.
  • Be direct. Don't hedge with "great question" or "as an AI"."""


def chat_about_deck(
    *,
    deck_summary: str,
    history: list[dict[str, str]],
    user_message: str,
) -> dict[str, Any] | None:
    """Conversational Q&A about a generated deck.

    Returns {"reply": str, "suggested_refinement": str | None} on success,
    or None when the API key is absent or the call fails. The deck summary
    is passed via system prompt with ephemeral caching so multi-turn
    conversations about the same deck don't re-tokenize the list each turn.
    """
    client = _get_client()
    if not client:
        return None

    messages: list[dict[str, Any]] = []
    for turn in history[-8:]:  # cap at last 8 turns to keep prompts bounded
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.messages.create(
            model=_FAST_MODEL,
            max_tokens=600,
            system=[
                {"type": "text", "text": _CHAT_SYSTEM},
                {"type": "text", "text": f"Current deck:\n{deck_summary}", "cache_control": {"type": "ephemeral"}},
            ],
            messages=messages,
        )
        data = _extract_json(response)
        reply = (data.get("reply") or "").strip()
        suggested = data.get("suggested_refinement")
        if isinstance(suggested, str):
            suggested = suggested.strip() or None
        else:
            suggested = None
        if not reply:
            return None
        return {"reply": reply, "suggested_refinement": suggested}
    except Exception:
        logger.warning("LLM deck chat failed", exc_info=True)
        return None


def enrich_deck_analysis(
    *,
    format_name: str,
    commander: str | None,
    card_list: str,
    role_summary: str,
    mana_curve_summary: str,
    nearest_archetype: str | None,
    existing_warnings: list[str],
    enabled: bool = True,
) -> DeckEnrichment | None:
    """Ask Claude for a richer analysis narrative and coaching note.

    Returns None when:
      - `enabled=False` (caller opted out — used by the UI's "deep analysis"
        toggle so we don't pay the LLM round-trip on every keystroke)
      - the API key is absent
      - the call fails

    Successful results are cached for 30 minutes keyed by a hash of the
    request payload, so re-analyzing the same deck (e.g. after toggling notes)
    does not re-bill the LLM.
    """
    if not enabled:
        return None
    client = _get_client()
    if not client:
        return None

    archetype_note = f"Nearest known archetype: {nearest_archetype}." if nearest_archetype else "No close archetype match found — likely a custom or hybrid shell."
    warnings_text = "\n".join(f"- {w}" for w in existing_warnings[:6]) if existing_warnings else "None detected."

    user_content = (
        f"Format: {format_name}"
        + (f" | Commander: {commander}" if commander else "")
        + f"\n\nDeck list:\n{card_list}"
        + f"\n\nRole breakdown: {role_summary}"
        + f"\nMana curve: {mana_curve_summary}"
        + f"\n{archetype_note}"
        + f"\n\nStructural warnings:\n{warnings_text}"
    )

    cache_key = hashlib.sha256(
        f"{_ANALYSIS_MODEL}\n{user_content}".encode("utf-8")
    ).hexdigest()
    cached = _enrichment_cache_get(cache_key)
    if cached is not None:
        try:
            return DeckEnrichment.model_validate(cached)
        except Exception:
            # Bad cache entry; fall through and refetch.
            pass

    try:
        response = client.messages.create(
            model=_ANALYSIS_MODEL,
            max_tokens=1024,
            system=[{"type": "text", "text": _ANALYSIS_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_content}],
        )
        data: dict[str, Any] = _extract_json(response)
        enrichment = DeckEnrichment.model_validate(data)
        _enrichment_cache_put(cache_key, enrichment.model_dump())
        return enrichment
    except Exception:
        logger.warning("LLM deck analysis enrichment failed; using rule-based output", exc_info=True)
        return None
