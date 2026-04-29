"""Decision policies for the goldfish simulator.

A policy is a callable ``policy(state, hand) -> list[Decision]`` that
takes the current game state and produces a sequence of intended
actions for the turn (lay land, cast spells, attack). Different
archetypes use different policies; the optimizer picks the policy
based on the deck's dominant role weights.
"""

from app.sim.policy.aggro import aggro_policy
from app.sim.policy.combo import combo_policy
from app.sim.policy.control import control_policy
from app.sim.policy.midrange import midrange_policy

POLICIES = {
    "aggro": aggro_policy,
    "combo": combo_policy,
    "control": control_policy,
    "midrange": midrange_policy,
}


def select_policy(role_profile: dict[str, float]):
    """Pick the best-matching policy for a deck's role profile."""
    score_aggro = role_profile.get("threat", 0) + role_profile.get("closer", 0)
    score_combo = role_profile.get("payoff", 0) + role_profile.get("enabler", 0) + role_profile.get("tutor", 0)
    score_control = role_profile.get("disruption", 0) + role_profile.get("removal", 0)
    score_midrange = role_profile.get("value_engine", 0) + 0.5 * (
        role_profile.get("threat", 0) + role_profile.get("removal", 0)
    )
    scores = {"aggro": score_aggro, "combo": score_combo, "control": score_control, "midrange": score_midrange}
    return max(scores, key=scores.get)


__all__ = ["aggro_policy", "combo_policy", "control_policy", "midrange_policy", "POLICIES", "select_policy"]
