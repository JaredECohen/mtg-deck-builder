from __future__ import annotations

from app.critic.envelope import DeckEnvelope
from app.optimizer.fitness import FitnessVector, OptimizerCandidate
from app.oracle.profile import (
    CardProfile,
    ComboPrimitives,
    CostVector,
    EffectVector,
    PROFILE_VERSION,
    RoleWeights,
)
from app.services.deck_rationale import (
    DeckRationale,
    MulliganGuide,
    build_deck_rationale,
)


def _profile(name, **kw):
    return CardProfile(
        card_id=name, name=name,
        cost_vector=CostVector(cmc=kw.get("cmc", 1.0)),
        effect_vector=EffectVector(**kw.get("effect", {})),
        role_weights=RoleWeights(**kw.get("role", {})),
        combo_primitives=ComboPrimitives(),
        oracle_ast=[], profile_version=PROFILE_VERSION, parse_method="pattern",
    )


def test_rationale_built_for_aggro_candidate():
    deck = [
        (_profile("Lightning Bolt", role={"removal": 0.6, "closer": 0.4}, effect={"damage_dealt": 3.0}), "Instant"),
        (_profile("Goblin Guide", role={"threat": 0.9}, effect={"board_impact": 2.5}), "Creature"),
        (_profile("Mountain", role={"land": 1.0}), "Basic Land — Mountain"),
    ] * 20
    fitness = FitnessVector(
        kill_turn_score=0.85, mulligan_keep=0.96, mana_consistency=0.94,
        synergy_density=0.5, redundancy=0.8, role_balance=0.85,
        raw={"avg_kill_turn": 4.6, "win_rate": 0.94, "archetype": "aggro"},
    )
    candidate = OptimizerCandidate(deck=deck, fitness=fitness, score=0.83)
    r = build_deck_rationale(candidate)
    assert r.archetype == "aggro"
    assert r.avg_kill_turn == 4.6
    assert r.win_rate == 0.94
    assert "fast" in r.headline.lower() or "aggressive" in r.headline.lower()
    assert len(r.key_turns) >= 3
    assert r.mulligan_guide.keep_threshold_summary != ""
    assert "removal" not in r.cards_breakdown.keys() or "Lightning Bolt" in r.cards_breakdown["removal"]
    assert "threats" in r.cards_breakdown
    assert "Goblin Guide" in r.cards_breakdown["threats"]
    assert "lands" in r.cards_breakdown
    assert "Mountain" in r.cards_breakdown["lands"]


def test_rationale_includes_matchups_when_envelope_present():
    deck = [(_profile("X", role={"land": 1.0}), "Land")] * 60
    fitness = FitnessVector(raw={"archetype": "control"})
    candidate = OptimizerCandidate(deck=deck, fitness=fitness, score=0.5)
    envelope = DeckEnvelope(matchup_matrix={"Burn": 0.45, "Murktide": 0.55, "Tron": 0.35})
    r = build_deck_rationale(candidate, final_envelope=envelope)
    assert len(r.soft_matchups) == 3
    # Ordered worst-first.
    assert r.soft_matchups[0].opponent_archetype == "Tron"
    assert r.soft_matchups[0].win_rate == 0.35
    assert "Unfavored" in r.soft_matchups[0].plan


def test_rationale_handles_missing_metrics():
    deck = [(_profile("X", role={"land": 1.0}), "Land")] * 60
    fitness = FitnessVector()
    candidate = OptimizerCandidate(deck=deck, fitness=fitness, score=0.0)
    r = build_deck_rationale(candidate)
    assert r.archetype != ""  # falls back gracefully
    assert r.headline != ""


def test_rationale_weakness_callouts():
    deck = [(_profile("X", role={"land": 1.0}), "Land")] * 60
    fitness = FitnessVector(
        kill_turn_score=0.2, mulligan_keep=0.6, mana_consistency=0.7,
        synergy_density=0.2, redundancy=0.3, role_balance=0.5,
        raw={"archetype": "midrange"},
    )
    candidate = OptimizerCandidate(deck=deck, fitness=fitness, score=0.4)
    r = build_deck_rationale(candidate)
    assert len(r.weakness_callouts) >= 2
    # Each callout should be a complete sentence.
    for w in r.weakness_callouts:
        assert len(w) > 10


def test_rationale_serializes_to_dict():
    deck = [(_profile("X", role={"land": 1.0}), "Land")] * 60
    fitness = FitnessVector(raw={"archetype": "aggro", "avg_kill_turn": 4.0, "win_rate": 0.8})
    candidate = OptimizerCandidate(deck=deck, fitness=fitness, score=0.7)
    r = build_deck_rationale(candidate)
    d = r.to_dict()
    assert isinstance(d, dict)
    assert "headline" in d
    assert "key_turns" in d
    assert isinstance(d["mulligan_guide"], dict)


def test_rationale_critic_transcript_round_summary():
    deck = [(_profile("X", role={"land": 1.0}), "Land")] * 60
    fitness = FitnessVector(raw={"archetype": "aggro"})
    candidate = OptimizerCandidate(deck=deck, fitness=fitness, score=0.7)

    class FakeRound:
        def __init__(self, round_num, items):
            self.round = round_num
            self.critique = {"items": items, "required_fixes": ["fix one", "fix two"]}

    rounds = [
        FakeRound(0, [{"summary": "mana too thin"}]),
        FakeRound(1, [{"summary": "kill turn slow"}]),
    ]
    r = build_deck_rationale(candidate, critic_rounds=rounds)
    assert len(r.critic_transcript) == 2
    assert r.critic_transcript[0].round == 0
    assert "mana too thin" in r.critic_transcript[0].flagged
