"""Pluggable model clients for the critic loop.

Production:
* :class:`AnthropicBuilder` — Claude. Reads the ``builder-responder``
  Skill prompt and emits a revised :class:`DeckEnvelope`.
* :class:`OpenAICritic` — GPT-5.5. Reads the ``deck-critic`` Skill
  prompt and emits a :class:`Critique`.

Tests use :class:`MockBuilder` / :class:`MockCritic` which return
pre-programmed responses so the loop is fully deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.critic.envelope import Critique, CritiqueItem, DeckEnvelope, Verdict


class CriticClient:
    def review(self, envelope: DeckEnvelope) -> Critique:
        raise NotImplementedError


class BuilderClient:
    def revise(self, envelope: DeckEnvelope, critique: Critique) -> DeckEnvelope:
        raise NotImplementedError


@dataclass
class MockCritic(CriticClient):
    """Deterministic critic — useful for tests and contract validation.

    ``responses`` is a list of (verdict, item-summaries) tuples; each
    call pops the next response. When the queue empties, falls back
    to APPROVE.
    """

    responses: list[Critique] = field(default_factory=list)
    calls: list[DeckEnvelope] = field(default_factory=list)

    def review(self, envelope: DeckEnvelope) -> Critique:
        self.calls.append(envelope)
        if self.responses:
            return self.responses.pop(0)
        return Critique(verdict=Verdict.APPROVE)


@dataclass
class MockBuilder(BuilderClient):
    """Deterministic builder — applies a function over (envelope, critique)."""

    revision_fn: Callable[[DeckEnvelope, Critique], DeckEnvelope] | None = None
    calls: list[tuple[DeckEnvelope, Critique]] = field(default_factory=list)

    def revise(self, envelope: DeckEnvelope, critique: Critique) -> DeckEnvelope:
        self.calls.append((envelope, critique))
        if self.revision_fn is not None:
            new_env = self.revision_fn(envelope, critique)
        else:
            new_env = DeckEnvelope(**{**envelope.to_dict(), "round": envelope.round + 1})
        new_env.previous_critique = critique.to_dict()
        new_env.round = envelope.round + 1
        return new_env


# --- Production clients (lazy SDK imports so tests don't require keys) ---


class AnthropicBuilder(BuilderClient):
    """Claude-backed builder. Loads the ``builder-responder`` Skill
    prompt at construct time and uses it as the system prompt for
    every revise() call."""

    def __init__(self, model: str = "claude-opus-4-7", *, skill_dir: str = ".claude/skills/builder-responder"):
        from anthropic import Anthropic  # lazy
        from pathlib import Path
        self._anthropic = Anthropic()
        self.model = model
        skill_path = Path(skill_dir) / "SKILL.md"
        self.system_prompt = skill_path.read_text() if skill_path.exists() else ""

    def revise(self, envelope: DeckEnvelope, critique: Critique) -> DeckEnvelope:
        import json
        message = self._anthropic.messages.create(
            model=self.model,
            max_tokens=4096,
            system=self.system_prompt,
            messages=[{
                "role": "user",
                "content": json.dumps({
                    "envelope": envelope.to_dict(),
                    "critique": critique.to_dict(),
                }),
            }],
        )
        text = message.content[0].text
        payload = json.loads(text)
        new_env = DeckEnvelope(**payload)
        new_env.round = envelope.round + 1
        new_env.previous_critique = critique.to_dict()
        return new_env


class OpenAICritic(CriticClient):
    """GPT-backed critic. Loads ``deck-critic`` Skill prompt; speaks
    only the critique JSON envelope.

    Deliberately not pinned to a SDK class — accepts any callable that
    matches OpenAI's chat-completions schema, so we can swap providers
    behind it without rewriting the loop.
    """

    def __init__(self, model: str = "gpt-5.5", *, skill_dir: str = ".claude/skills/deck-critic",
                 client_factory: Callable[[], Any] | None = None):
        from pathlib import Path
        self.model = model
        skill_path = Path(skill_dir) / "SKILL.md"
        self.system_prompt = skill_path.read_text() if skill_path.exists() else ""
        if client_factory is None:
            from openai import OpenAI  # lazy import
            self._client = OpenAI()
        else:
            self._client = client_factory()

    def review(self, envelope: DeckEnvelope) -> Critique:
        import json
        resp = self._client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": json.dumps(envelope.to_dict())},
            ],
        )
        payload = json.loads(resp.choices[0].message.content)
        items = [CritiqueItem(**i) for i in payload.get("items", [])]
        return Critique(
            verdict=Verdict(payload["verdict"]),
            items=items,
            required_fixes=payload.get("required_fixes", []),
            optional_fixes=payload.get("optional_fixes", []),
            notes=payload.get("notes", ""),
        )
