"""The Builder ⇄ Critic loop driver."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.critic.clients import BuilderClient, CriticClient
from app.critic.envelope import Critique, DeckEnvelope, Verdict
from app.critic.rubric import RUBRIC_BY_ID, run_rubric


@dataclass
class CriticConfig:
    max_rounds: int = 4
    require_each_round_improves: bool = True
    accept_best_at_max_rounds: bool = True
    short_circuit_on_clean_rubric: bool = True


@dataclass
class CriticLoopRound:
    round: int
    envelope_in: dict
    critique: dict
    envelope_out: dict | None
    deterministic_items: list[dict]
    accepted: bool
    rolled_back: bool = False


@dataclass
class CriticLoopResult:
    final_envelope: DeckEnvelope
    final_critique: Critique
    rounds: list[CriticLoopRound] = field(default_factory=list)
    approved: bool = False
    notes: list[str] = field(default_factory=list)


def run_critic_loop(
    initial: DeckEnvelope,
    *,
    critic: CriticClient,
    builder: BuilderClient,
    config: CriticConfig | None = None,
) -> CriticLoopResult:
    """Run the loop, return the final envelope + critique.

    Behavior:
    1. If the deterministic rubric pass returns no items AND the loop
       config short-circuits, skip the LLM and approve.
    2. Otherwise consult the critic. If it APPROVES *and* the
       deterministic pass agrees, finalize. If it APPROVES but the
       deterministic pass finds an error, treat as REVISE.
    3. Builder produces a revised envelope. If the simulator metrics
       didn't improve in any axis (and config requires it), roll back.
    4. Repeat up to ``max_rounds``. After max, accept the
       highest-fitness envelope visited.
    """
    cfg = config or CriticConfig()
    history: list[tuple[DeckEnvelope, Critique]] = []
    rounds: list[CriticLoopRound] = []
    current = initial
    last_critique: Critique | None = None

    # Deterministic pre-filter.
    deterministic_items = run_rubric(current)
    if cfg.short_circuit_on_clean_rubric and not _has_errors(deterministic_items):
        critique = critic.review(current)
        rounds.append(CriticLoopRound(
            round=0,
            envelope_in=current.to_dict(),
            critique=critique.to_dict(),
            envelope_out=current.to_dict(),
            deterministic_items=[i.to_dict() for i in deterministic_items],
            accepted=critique.is_approved(),
        ))
        if critique.is_approved():
            return CriticLoopResult(
                final_envelope=current,
                final_critique=critique,
                rounds=rounds,
                approved=True,
                notes=["short-circuit on clean deterministic rubric + critic approval"],
            )
        last_critique = critique
        history.append((current, critique))

    for round_idx in range(len(rounds), cfg.max_rounds):
        current.round = round_idx
        critique = last_critique if last_critique is not None else critic.review(current)
        deterministic_items = run_rubric(current)
        last_critique = None
        rolled_back = False

        # Sanity gate: critic cannot APPROVE if deterministic pass has errors.
        if critique.is_approved() and _has_errors(deterministic_items):
            critique = Critique(
                verdict=Verdict.REVISE,
                items=deterministic_items,
                required_fixes=[i.summary for i in deterministic_items if i.severity == "error"],
                notes="auto-downgraded: deterministic rubric flagged errors",
            )

        if critique.is_approved():
            rounds.append(CriticLoopRound(
                round=round_idx,
                envelope_in=current.to_dict(),
                critique=critique.to_dict(),
                envelope_out=current.to_dict(),
                deterministic_items=[i.to_dict() for i in deterministic_items],
                accepted=True,
            ))
            return CriticLoopResult(
                final_envelope=current,
                final_critique=critique,
                rounds=rounds,
                approved=True,
                notes=["critic approved"],
            )

        # Builder revises.
        revised = builder.revise(current, critique)

        # Improvement gate.
        accepted = True
        if cfg.require_each_round_improves and history:
            prev_metrics = history[-1][0].simulator_metrics or {}
            new_metrics = revised.simulator_metrics or {}
            if not _any_metric_improved(prev_metrics, new_metrics):
                accepted = False
                rolled_back = True

        rounds.append(CriticLoopRound(
            round=round_idx,
            envelope_in=current.to_dict(),
            critique=critique.to_dict(),
            envelope_out=revised.to_dict() if accepted else None,
            deterministic_items=[i.to_dict() for i in deterministic_items],
            accepted=accepted,
            rolled_back=rolled_back,
        ))

        if accepted:
            history.append((current, critique))
            current = revised
        else:
            # Rolled back — try a re-critique on the previous candidate
            # next round, but with the same envelope (no further revision).
            history.append((current, critique))

    # Max rounds hit. Pick the highest-fitness envelope from history.
    best = max(history, key=lambda hc: _fitness_key(hc[0])) if history else (current, critique)
    return CriticLoopResult(
        final_envelope=best[0],
        final_critique=best[1],
        rounds=rounds,
        approved=False,
        notes=[f"max rounds ({cfg.max_rounds}) reached without approval — accepted highest-fitness candidate"],
    )


def _has_errors(items) -> bool:
    return any(i.severity == "error" for i in items)


def _any_metric_improved(prev: dict, new: dict) -> bool:
    # Higher is better for win rate, lower is better for kill turn.
    for key in ("win_rate", "mana_consistency", "score"):
        if key in new and key in prev and new[key] > prev[key]:
            return True
    if "avg_kill_turn" in new and "avg_kill_turn" in prev:
        if new["avg_kill_turn"] < prev["avg_kill_turn"]:
            return True
    return False


def _fitness_key(envelope: DeckEnvelope) -> float:
    fit = envelope.fitness or {}
    metrics = envelope.simulator_metrics or {}
    return (
        fit.get("score", 0.0)
        + fit.get("win_rate", 0.0)
        - 0.05 * (metrics.get("avg_kill_turn") or 12.0)
    )
