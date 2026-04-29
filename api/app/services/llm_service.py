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

# Haiku for fast structured extraction; configurable for richer analysis
_FAST_MODEL = os.getenv("ANTHROPIC_FAST_MODEL", "claude-haiku-4-5")
_ANALYSIS_MODEL = os.getenv("ANTHROPIC_ANALYSIS_MODEL", "claude-haiku-4-5")

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
