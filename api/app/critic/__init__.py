"""Critic loop.

The deck candidate emitted by the optimizer (Phase 5) is fed through
an adversarial review loop:

    Builder (Claude) -> Critic (GPT-5.5) -> Builder -> ...

Until the critic returns ``verdict="approve"`` or the round budget
runs out (default 4). The critic is constrained to *evidence-bound*
critiques drawn from a fixed rubric; the builder must address every
``required_fixes`` item with simulator evidence or revise.

The model clients are abstracted behind :class:`CriticClient` and
:class:`BuilderClient` interfaces. Tests use deterministic mocks; prod
wires in real Anthropic + OpenAI SDK calls.
"""

from app.critic.envelope import (
    Critique,
    CritiqueItem,
    DeckEnvelope,
    EnvelopeVersion,
    Verdict,
)
from app.critic.loop import (
    CriticConfig,
    CriticLoopResult,
    run_critic_loop,
)
from app.critic.clients import (
    BuilderClient,
    CostBudget,
    CriticClient,
    CriticResponseError,
    MockBuilder,
    MockCritic,
    make_critic_clients_from_env,
)
from app.critic.rubric import RUBRIC, RubricCheck, run_rubric

__all__ = [
    "BuilderClient",
    "CostBudget",
    "CriticClient",
    "CriticConfig",
    "CriticLoopResult",
    "CriticResponseError",
    "Critique",
    "CritiqueItem",
    "DeckEnvelope",
    "EnvelopeVersion",
    "MockBuilder",
    "MockCritic",
    "RUBRIC",
    "RubricCheck",
    "Verdict",
    "make_critic_clients_from_env",
    "run_critic_loop",
    "run_rubric",
]
