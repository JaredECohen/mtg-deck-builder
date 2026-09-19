"""Request shapes for llm_service (offline; the Anthropic client is a recorder).

Every function must send its module system prompt verbatim, its cache markers in the
places the caching layout expects, and a byte-identical payload for identical inputs.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import llm_usage
from app.services import llm_service


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Message:
    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]
        self.usage = SimpleNamespace(
            input_tokens=100, output_tokens=20,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )


def _recorder(reply: dict, recorded: list[dict]):
    def create(**kwargs):
        recorded.append(kwargs)
        return _Message(json.dumps(reply))

    return SimpleNamespace(messages=SimpleNamespace(create=create))


def _strip_markers(value):
    if isinstance(value, dict):
        return {k: _strip_markers(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [_strip_markers(v) for v in value]
    return value


@pytest.fixture(autouse=True)
def _fresh_caches():
    llm_service._enrichment_cache.clear()
    llm_service._blend_cache.clear()
    llm_service._compose_cache.clear()
    yield


CARDS = {"archetype_label": "L", "strategy": "s", "anchor_cards": [{"name": "A", "quantity": 4}]}
CALLS = {
    "interpret_refinement": (
        lambda: llm_service.interpret_refinement("make it cheaper"), {},
        llm_service._REFINE_SYSTEM, [{"role": "user", "content": "make it cheaper"}],
    ),
    "interpret_generate_prompt": (
        lambda: llm_service.interpret_generate_prompt("mono red"), {},
        llm_service._GENERATE_SYSTEM, [{"role": "user", "content": "mono red"}],
    ),
    "refine_blend": (
        lambda: llm_service.refine_blend(
            matched_archetypes=[
                {"display_name": "Burn", "anchor_cards": [("A", 4)]},
                {"display_name": "Prowess", "anchor_cards": [("B", 4)]},
            ],
            format_name="modern", colors=["R"], budget=None, user_brief="x",
        ),
        {"blended_strategy": "s", "anchor_cards": [{"name": "A", "quantity": 4}]},
        llm_service._BLEND_SYSTEM, None,
    ),
    "refine_compose": (
        lambda: llm_service.refine_compose(
            composed={"archetype_label": "L", "strategy": "s", "anchor_cards": [("A", 4)]},
            format_name="modern", colors=["R"], budget=None, user_brief="x",
        ),
        CARDS, llm_service._REFINE_COMPOSE_SYSTEM, None,
    ),
    "compose_from_scratch": (
        lambda: llm_service.compose_from_scratch(
            format_name="modern", colors=["R"], playstyle_tags=[], theme_tags=[],
            budget=None, user_brief="x",
        ),
        CARDS, llm_service._COMPOSE_SYSTEM, None,
    ),
    "enrich_deck_analysis": (
        lambda: llm_service.enrich_deck_analysis(
            format_name="modern", commander=None, card_list="4 A", role_summary="r",
            mana_curve_summary="m", nearest_archetype=None, existing_warnings=[],
        ),
        {"game_plan_summary": "g", "play_pattern_summary": "p", "ai_coaching_note": "1. a 2. b 3. c"},
        llm_service._ANALYSIS_SYSTEM, None,
    ),
}


@pytest.mark.parametrize("name", sorted(CALLS))
def test_single_shot_calls_send_the_module_prompt_as_one_marked_block(monkeypatch, name):
    call, reply, system_text, expected_messages = CALLS[name]
    recorded: list[dict] = []
    monkeypatch.setattr(llm_service, "_get_client", lambda: _recorder(reply, recorded))
    assert call() is not None
    assert len(recorded) == 1
    request = recorded[0]
    assert request["system"] == [
        {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}},
    ]
    if expected_messages is not None:
        assert request["messages"] == expected_messages
    assert isinstance(request["messages"][0]["content"], str)
    assert json.dumps(request).count('"cache_control"') == 1


@pytest.mark.parametrize("name", sorted(CALLS))
def test_identical_inputs_build_byte_identical_requests(monkeypatch, name):
    call, reply, _, _ = CALLS[name]
    recorded: list[dict] = []
    monkeypatch.setattr(llm_service, "_get_client", lambda: _recorder(reply, recorded))
    call()
    for cache in (llm_service._enrichment_cache, llm_service._blend_cache, llm_service._compose_cache):
        cache.clear()  # the in-process LRU would otherwise answer the second call itself
    call()
    assert len(recorded) == 2
    assert json.dumps(recorded[0], sort_keys=True) == json.dumps(recorded[1], sort_keys=True)


def test_chat_marks_the_deck_block_and_the_newest_turn_only(monkeypatch):
    recorded: list[dict] = []
    monkeypatch.setattr(
        llm_service, "_get_client",
        lambda: _recorder({"reply": "r", "suggested_refinement": None}, recorded),
    )
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    assert llm_service.chat_about_deck(deck_summary="4 A", history=history, user_message="why A?") == {
        "reply": "r", "suggested_refinement": None,
    }
    request = recorded[0]
    assert request["system"] == [
        {"type": "text", "text": llm_service._CHAT_SYSTEM},
        {"type": "text", "text": "Current deck:\n4 A", "cache_control": {"type": "ephemeral"}},
    ]
    assert request["messages"][:2] == history
    assert request["messages"][2] == {
        "role": "user",
        "content": [{"type": "text", "text": "why A?", "cache_control": {"type": "ephemeral"}}],
    }
    assert json.dumps(request).count('"cache_control"') == 2
    # Stripped of markers the conversation is exactly the history plus the new message.
    assert _strip_markers(request["messages"]) == history + [
        {"role": "user", "content": [{"type": "text", "text": "why A?"}]},
    ]


def test_log_usage_reads_real_ints_and_ignores_mocks():
    real = SimpleNamespace(input_tokens=10, output_tokens=2,
                           cache_creation_input_tokens=300, cache_read_input_tokens=1200)
    assert llm_usage.log_usage("t", "m", real) == {
        "input_tokens": 10, "output_tokens": 2,
        "cache_creation_input_tokens": 300, "cache_read_input_tokens": 1200,
    }
    assert llm_usage.log_usage("t", "m", MagicMock()) == dict.fromkeys(llm_usage.FIELDS, 0)
    assert llm_usage.log_usage("t", "m", None) == dict.fromkeys(llm_usage.FIELDS, 0)
    openai = SimpleNamespace(prompt_tokens=50, completion_tokens=5,
                             prompt_tokens_details=SimpleNamespace(cached_tokens=40))
    assert llm_usage.log_usage("t", "m", openai, provider="openai") == {
        "input_tokens": 50, "output_tokens": 5,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 40,
    }
