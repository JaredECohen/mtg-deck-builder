"""Pluggable model clients for the critic loop.

Production:
* :class:`AnthropicBuilder` — Claude. Reads the ``builder-responder``
  Skill prompt and emits a revised :class:`DeckEnvelope`.
* :class:`OpenAICritic` — GPT-5.5. Reads the ``deck-critic`` Skill
  prompt and emits a :class:`Critique`.

Tests use :class:`MockBuilder` / :class:`MockCritic` which return
pre-programmed responses so the loop is fully deterministic.

Production clients honor:
* ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` from env (loaded lazily)
* Per-call retries with exponential backoff on transient errors
* Cost gating: ``MTG_CRITIC_MAX_TOKENS_PER_CALL``,
  ``MTG_CRITIC_MAX_USD_PER_JOB`` (best-effort estimation)
* JSON-only response enforcement; malformed responses raise
  :class:`CriticResponseError` so the loop can roll back the round.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.critic.envelope import Critique, CritiqueItem, DeckEnvelope, Verdict


logger = logging.getLogger(__name__)


class CriticResponseError(RuntimeError):
    """Raised when an LLM response can't be parsed into the envelope/critique
    schema. Loop driver treats this as a soft round failure (rollback)."""


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class CostBudget:
    """Per-job cost gate. Compared against estimated token spend at each
    LLM call. The gate raises a :class:`CriticResponseError` when the
    budget would be exceeded — the loop rolls back and falls back to
    deterministic rubric-only critique."""

    max_tokens_per_call: int = 4096
    max_usd_per_job: float = 1.50
    estimated_input_cost_per_1k: float = 0.003
    estimated_output_cost_per_1k: float = 0.015
    spent_usd: float = 0.0

    @classmethod
    def from_env(cls) -> "CostBudget":
        return cls(
            max_tokens_per_call=_get_int_env("MTG_CRITIC_MAX_TOKENS_PER_CALL", 4096),
            max_usd_per_job=_get_float_env("MTG_CRITIC_MAX_USD_PER_JOB", 1.50),
        )

    def estimate(self, *, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1000 * self.estimated_input_cost_per_1k
            + output_tokens / 1000 * self.estimated_output_cost_per_1k
        )

    def gate(self, *, input_tokens: int, output_tokens: int) -> None:
        cost = self.estimate(input_tokens=input_tokens, output_tokens=output_tokens)
        if self.spent_usd + cost > self.max_usd_per_job:
            raise CriticResponseError(
                f"cost gate: would exceed ${self.max_usd_per_job:.2f} job budget "
                f"(${self.spent_usd:.2f} + ${cost:.2f})"
            )

    def record(self, *, input_tokens: int, output_tokens: int) -> None:
        self.spent_usd += self.estimate(
            input_tokens=input_tokens, output_tokens=output_tokens
        )


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


def _retry_call(fn: Callable[[], Any], *, attempts: int = 3, base_delay: float = 0.5) -> Any:
    """Exponential backoff retry. Re-raises the last exception on exhaust."""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — retry on any SDK error
            last_exc = exc
            transient = type(exc).__name__ in {
                "APIConnectionError", "APITimeoutError", "RateLimitError",
                "InternalServerError", "APIStatusError", "Timeout",
            }
            if not transient and attempt > 0:
                # Non-transient error after first retry — give up early.
                break
            sleep_for = base_delay * (2 ** attempt)
            logger.warning(
                "critic-loop transient error (%s) attempt=%d, retrying in %.1fs",
                type(exc).__name__, attempt + 1, sleep_for,
            )
            time.sleep(sleep_for)
    assert last_exc is not None
    raise last_exc


def _approx_tokens(text: str) -> int:
    """Rough token count — 4 chars / token. Good enough for cost gating
    where exact billing precision isn't required."""
    return max(1, len(text) // 4)


class AnthropicBuilder(BuilderClient):
    """Claude-backed builder. Loads the ``builder-responder`` Skill
    prompt at construct time and uses it as the system prompt for
    every revise() call.

    Configuration via env:
      * ``ANTHROPIC_API_KEY`` — required (SDK reads automatically)
      * ``MTG_BUILDER_MODEL`` — model id; default ``claude-opus-4-7``
      * ``MTG_CRITIC_MAX_TOKENS_PER_CALL`` — max output tokens
      * ``MTG_CRITIC_MAX_USD_PER_JOB`` — per-job cost cap
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        skill_dir: str = ".claude/skills/builder-responder",
        budget: CostBudget | None = None,
    ):
        from anthropic import Anthropic  # lazy
        from pathlib import Path

        self._anthropic = Anthropic()  # picks up ANTHROPIC_API_KEY from env
        self.model = model or os.getenv("MTG_BUILDER_MODEL", "claude-opus-4-7")
        skill_path = Path(skill_dir) / "SKILL.md"
        self.system_prompt = skill_path.read_text() if skill_path.exists() else ""
        self.budget = budget or CostBudget.from_env()

    def revise(self, envelope: DeckEnvelope, critique: Critique) -> DeckEnvelope:
        user_payload = json.dumps({
            "envelope": envelope.to_dict(),
            "critique": critique.to_dict(),
        })
        input_tokens = _approx_tokens(self.system_prompt) + _approx_tokens(user_payload)
        self.budget.gate(
            input_tokens=input_tokens,
            output_tokens=self.budget.max_tokens_per_call,
        )

        def _call():
            return self._anthropic.messages.create(
                model=self.model,
                max_tokens=self.budget.max_tokens_per_call,
                system=self.system_prompt,
                messages=[{"role": "user", "content": user_payload}],
            )

        message = _retry_call(_call)
        text = message.content[0].text
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CriticResponseError(f"builder returned non-JSON: {exc}") from exc
        try:
            new_env = DeckEnvelope(**payload)
        except TypeError as exc:
            raise CriticResponseError(f"builder JSON didn't match envelope schema: {exc}") from exc
        new_env.round = envelope.round + 1
        new_env.previous_critique = critique.to_dict()
        output_tokens = _approx_tokens(text)
        self.budget.record(input_tokens=input_tokens, output_tokens=output_tokens)
        return new_env


class OpenAICritic(CriticClient):
    """GPT-backed critic. Loads ``deck-critic`` Skill prompt; speaks
    only the critique JSON envelope.

    Configuration via env:
      * ``OPENAI_API_KEY`` — required (SDK reads automatically)
      * ``MTG_CRITIC_MODEL`` — model id; default ``gpt-5.5``
      * cost gating same as :class:`AnthropicBuilder`
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        skill_dir: str = ".claude/skills/deck-critic",
        client_factory: Callable[[], Any] | None = None,
        budget: CostBudget | None = None,
    ):
        from pathlib import Path

        self.model = model or os.getenv("MTG_CRITIC_MODEL", "gpt-5.5")
        skill_path = Path(skill_dir) / "SKILL.md"
        self.system_prompt = skill_path.read_text() if skill_path.exists() else ""
        if client_factory is None:
            from openai import OpenAI  # lazy
            self._client = OpenAI()  # picks up OPENAI_API_KEY from env
        else:
            self._client = client_factory()
        self.budget = budget or CostBudget.from_env()

    def review(self, envelope: DeckEnvelope) -> Critique:
        user_payload = json.dumps(envelope.to_dict())
        input_tokens = _approx_tokens(self.system_prompt) + _approx_tokens(user_payload)
        self.budget.gate(
            input_tokens=input_tokens,
            output_tokens=self.budget.max_tokens_per_call,
        )

        def _call():
            return self._client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                max_tokens=self.budget.max_tokens_per_call,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_payload},
                ],
            )

        resp = _retry_call(_call)
        raw = resp.choices[0].message.content
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CriticResponseError(f"critic returned non-JSON: {exc}") from exc

        try:
            verdict = Verdict(payload["verdict"])
        except (KeyError, ValueError) as exc:
            raise CriticResponseError(f"critic JSON missing valid verdict: {exc}") from exc

        items: list[CritiqueItem] = []
        for raw_item in payload.get("items", []):
            try:
                items.append(CritiqueItem(**raw_item))
            except TypeError as exc:
                raise CriticResponseError(f"critic item malformed: {exc}") from exc

        critique = Critique(
            verdict=verdict,
            items=items,
            required_fixes=list(payload.get("required_fixes", [])),
            optional_fixes=list(payload.get("optional_fixes", [])),
            notes=str(payload.get("notes", "")),
        )
        output_tokens = _approx_tokens(raw)
        self.budget.record(input_tokens=input_tokens, output_tokens=output_tokens)
        return critique


def make_critic_clients_from_env(
    *, shared_budget: CostBudget | None = None,
) -> tuple[BuilderClient, CriticClient, CostBudget]:
    """Factory that returns production clients (and the shared budget)
    when API keys are set, falling back to the deterministic mocks
    otherwise.

    The shared budget is the third return value so callers can pass it
    to :class:`CriticConfig.shared_budget` and reuse it across the
    loop. Mocks ignore the budget but it's returned anyway for API
    symmetry.
    """
    budget = shared_budget or CostBudget.from_env()
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    if not (has_anthropic and has_openai):
        logger.info(
            "critic clients: missing keys (anthropic=%s, openai=%s); using mocks",
            has_anthropic, has_openai,
        )
        return MockBuilder(), MockCritic(), budget
    try:
        builder: BuilderClient = AnthropicBuilder(budget=budget)
        critic: CriticClient = OpenAICritic(budget=budget)
    except Exception as exc:  # noqa: BLE001
        logger.warning("critic clients: SDK init failed (%s); using mocks", exc)
        return MockBuilder(), MockCritic(), budget
    return builder, critic, budget
