from __future__ import annotations

import pytest

from app.critic import (
    BuilderClient,
    CostBudget,
    Critique,
    CritiqueItem,
    CriticConfig,
    CriticResponseError,
    DeckEnvelope,
    MockBuilder,
    MockCritic,
    Verdict,
    make_critic_clients_from_env,
    run_critic_loop,
    run_rubric,
)
from app.critic.clients import _retry_call


def make_envelope(**kw) -> DeckEnvelope:
    base = dict(
        deck=[{"name": "Lightning Bolt", "type_line": "Instant", "cmc": 1.0,
               "color_demand": {"R": 1}, "role_weights": {"removal": 1.0}}] * 4,
        simulator_metrics={"avg_kill_turn": 4.5, "win_rate": 0.92},
        fitness={"score": 0.82, "kill_turn_score": 0.83, "mana_consistency": 0.92,
                 "synergy_density": 0.5, "redundancy": 0.7, "role_balance": 0.8,
                 "archetype": "aggro"},
        synergy_clique=[],
        matchup_matrix={"Murktide": 0.55, "Tron": 0.45, "Burn": 0.50},
        constraints={"violations": []},
    )
    base.update(kw)
    return DeckEnvelope(**base)


def test_rubric_passes_clean_deck():
    envelope = make_envelope()
    items = run_rubric(envelope)
    # Clean deck should yield no errors.
    assert all(i.severity != "error" for i in items)


def test_rubric_flags_low_mana_consistency():
    envelope = make_envelope(fitness={"mana_consistency": 0.65, "score": 0.5,
                                      "archetype": "aggro"})
    items = run_rubric(envelope)
    assert any(i.rubric_id == "R2_mana_consistency" and i.severity == "error" for i in items)


def test_rubric_flags_slow_kill_turn():
    envelope = make_envelope(simulator_metrics={"avg_kill_turn": 9.5})
    items = run_rubric(envelope)
    assert any(i.rubric_id == "R1_win_condition" for i in items)


def test_rubric_flags_constraint_violations():
    envelope = make_envelope(constraints={"violations": ["over_budget"]})
    items = run_rubric(envelope)
    assert any(i.rubric_id == "R5_constraints" for i in items)


def test_rubric_flags_synergy_bottleneck():
    envelope = make_envelope(
        deck=[{"name": "Splinter Twin", "cmc": 4}] * 1 +
             [{"name": "Deceiver Exarch", "cmc": 3}] * 2,
        synergy_clique=["Splinter Twin", "Deceiver Exarch"],
    )
    items = run_rubric(envelope)
    assert any(i.rubric_id == "R4_synergy_redundancy" for i in items)


def test_loop_short_circuits_on_clean_rubric_and_critic_approval():
    envelope = make_envelope()
    critic = MockCritic(responses=[Critique(verdict=Verdict.APPROVE)])
    builder = MockBuilder()
    result = run_critic_loop(envelope, critic=critic, builder=builder)
    assert result.approved is True
    assert len(result.rounds) == 1
    assert len(builder.calls) == 0  # builder never invoked


def test_loop_revises_when_critic_rejects():
    envelope = make_envelope()

    def revise(env, crit):
        new_metrics = dict(env.simulator_metrics)
        new_metrics["avg_kill_turn"] = (env.simulator_metrics or {}).get("avg_kill_turn", 5.0) - 0.5
        new_metrics["win_rate"] = (env.simulator_metrics or {}).get("win_rate", 0.5) + 0.05
        from dataclasses import replace
        return DeckEnvelope(
            version=env.version,
            deck=env.deck,
            simulator_metrics=new_metrics,
            fitness=env.fitness,
            synergy_clique=env.synergy_clique,
            matchup_matrix=env.matchup_matrix,
            constraints=env.constraints,
            builder_notes=env.builder_notes + [f"applied: {crit.required_fixes[:1]}"],
            round=env.round + 1,
        )

    critic = MockCritic(responses=[
        Critique(verdict=Verdict.REVISE,
                 items=[CritiqueItem(rubric_id="R1_win_condition", severity="warning",
                                     summary="too slow", evidence={})],
                 required_fixes=["lower curve"]),
        Critique(verdict=Verdict.APPROVE),
    ])
    builder = MockBuilder(revision_fn=revise)
    result = run_critic_loop(envelope, critic=critic, builder=builder,
                             config=CriticConfig(short_circuit_on_clean_rubric=False))
    assert result.approved is True
    assert len(builder.calls) == 1


def test_loop_caps_at_max_rounds_and_returns_best():
    envelope = make_envelope()

    def stuck_revise(env, crit):
        from dataclasses import replace
        # Each round flips kill_turn back and forth — never strictly improves.
        return DeckEnvelope(
            version=env.version,
            deck=env.deck,
            simulator_metrics={"avg_kill_turn": 5.0, "win_rate": 0.6},
            fitness=env.fitness,
            synergy_clique=env.synergy_clique,
            matchup_matrix=env.matchup_matrix,
            constraints=env.constraints,
            round=env.round + 1,
        )

    critic = MockCritic(responses=[
        Critique(verdict=Verdict.REVISE, required_fixes=["a"]),
        Critique(verdict=Verdict.REVISE, required_fixes=["b"]),
        Critique(verdict=Verdict.REVISE, required_fixes=["c"]),
        Critique(verdict=Verdict.REVISE, required_fixes=["d"]),
        Critique(verdict=Verdict.REVISE, required_fixes=["e"]),
    ])
    builder = MockBuilder(revision_fn=stuck_revise)
    result = run_critic_loop(
        envelope, critic=critic, builder=builder,
        config=CriticConfig(max_rounds=3, short_circuit_on_clean_rubric=False),
    )
    assert result.approved is False
    assert len(result.rounds) <= 3


def test_loop_overrides_critic_approval_on_deterministic_error():
    """If the critic says APPROVE but the deterministic rubric flags
    an error, the loop should auto-downgrade to REVISE."""
    envelope = make_envelope(fitness={"mana_consistency": 0.5, "score": 0.5,
                                      "archetype": "aggro"})

    def revise(env, crit):
        return DeckEnvelope(
            version=env.version,
            deck=env.deck,
            simulator_metrics=env.simulator_metrics,
            fitness={"mana_consistency": 0.95, "score": 0.7, "archetype": "aggro"},
            synergy_clique=env.synergy_clique,
            matchup_matrix=env.matchup_matrix,
            constraints=env.constraints,
            round=env.round + 1,
        )

    critic = MockCritic(responses=[
        Critique(verdict=Verdict.APPROVE),  # critic mistakenly approves
        Critique(verdict=Verdict.APPROVE),  # second round, after fix
    ])
    builder = MockBuilder(revision_fn=revise)
    result = run_critic_loop(envelope, critic=critic, builder=builder,
                             config=CriticConfig(short_circuit_on_clean_rubric=False))
    # Should iterate at least once because deterministic rubric had errors.
    assert len(result.rounds) >= 2


def test_loop_rolls_back_round_with_no_metric_improvement():
    envelope = make_envelope(fitness={"score": 0.5, "archetype": "aggro"})

    def regressing(env, crit):
        # New envelope has worse win_rate AND worse kill_turn.
        return DeckEnvelope(
            version=env.version,
            deck=env.deck,
            simulator_metrics={"avg_kill_turn": 12.0, "win_rate": 0.0},
            fitness=env.fitness,
            constraints=env.constraints,
            round=env.round + 1,
        )

    critic = MockCritic(responses=[
        Critique(verdict=Verdict.REVISE, required_fixes=["fix"]),
        Critique(verdict=Verdict.REVISE, required_fixes=["fix"]),
    ])
    builder = MockBuilder(revision_fn=regressing)
    result = run_critic_loop(envelope, critic=critic, builder=builder,
                             config=CriticConfig(max_rounds=2,
                                                short_circuit_on_clean_rubric=False,
                                                require_each_round_improves=True))
    rolled_back = [r for r in result.rounds if r.rolled_back]
    assert len(rolled_back) >= 1


# --- live-client substitutes (cost budget + retry behavior) -----------


def test_cost_budget_gates_overspend():
    budget = CostBudget(
        max_tokens_per_call=1000,
        max_usd_per_job=0.01,  # tiny budget
        estimated_input_cost_per_1k=0.003,
        estimated_output_cost_per_1k=0.015,
    )
    # First call should fit (1000 in + 1000 out ≈ $0.018, exceeds $0.01).
    with pytest.raises(CriticResponseError) as exc:
        budget.gate(input_tokens=1000, output_tokens=1000)
    assert "cost gate" in str(exc.value)


def test_cost_budget_records_spend():
    budget = CostBudget(max_usd_per_job=10.0)
    budget.record(input_tokens=1000, output_tokens=500)
    assert budget.spent_usd > 0


def test_retry_call_succeeds_after_transient_failure():
    calls = {"n": 0}

    class APITimeoutError(Exception):
        pass

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise APITimeoutError("timeout")
        return "ok"

    result = _retry_call(flaky, attempts=4, base_delay=0.01)
    assert result == "ok"
    assert calls["n"] == 3


def test_retry_call_reraises_after_exhausting_attempts():
    class APITimeoutError(Exception):
        pass

    def always_fails():
        raise APITimeoutError("nope")

    with pytest.raises(Exception):
        _retry_call(always_fails, attempts=2, base_delay=0.01)


def test_make_critic_clients_falls_back_to_mocks_without_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    builder, critic, budget = make_critic_clients_from_env()
    assert isinstance(builder, MockBuilder)
    assert isinstance(critic, MockCritic)
    assert isinstance(budget, CostBudget)


def test_shared_budget_is_threaded_through_loop():
    """Critic loop with a shared CostBudget should attach it to both
    clients so per-job spending is bounded across all rounds."""
    envelope = make_envelope()
    budget = CostBudget(
        max_tokens_per_call=100,
        max_usd_per_job=0.0001,  # tiny — would blow on first call
    )
    # Mocks don't actually use the budget but should still accept it.
    critic = MockCritic(responses=[Critique(verdict=Verdict.APPROVE)])
    builder = MockBuilder()

    # Attach budget attrs so the loop's budget-sharing path runs.
    critic.budget = CostBudget()
    builder.budget = CostBudget()

    cfg = CriticConfig(short_circuit_on_clean_rubric=True, shared_budget=budget)
    run_critic_loop(envelope, critic=critic, builder=builder, config=cfg)
    assert critic.budget is budget
    assert builder.budget is budget
