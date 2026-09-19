"""Per-call token accounting for the LLM sites. Log-only; never raises.

Anthropic reports cache activity as `cache_creation_input_tokens` /
`cache_read_input_tokens` outside `input_tokens`; OpenAI reports cached prompt
tokens inside `prompt_tokens` under `prompt_tokens_details.cached_tokens`.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _int(value: Any) -> int:
    # MagicMock responses in the offline tests answer every attribute; only real ints count.
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def usage_counts(usage: Any, *, provider: str = "anthropic") -> dict[str, int]:
    if provider == "openai":
        details = getattr(usage, "prompt_tokens_details", None)
        return {
            "input_tokens": _int(getattr(usage, "prompt_tokens", None)),
            "output_tokens": _int(getattr(usage, "completion_tokens", None)),
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": _int(getattr(details, "cached_tokens", None)),
        }
    return {field: _int(getattr(usage, field, None)) for field in FIELDS}


def log_usage(site: str, model: str, usage: Any, *, provider: str = "anthropic") -> dict[str, int]:
    counts = usage_counts(usage, provider=provider)
    logger.info(
        "llm_usage site=%s provider=%s model=%s input=%d cache_write=%d cache_read=%d output=%d",
        site, provider, model,
        counts["input_tokens"], counts["cache_creation_input_tokens"],
        counts["cache_read_input_tokens"], counts["output_tokens"],
    )
    return counts
