"""Deck evaluation layer — a richer, multi-signal verdict on a deck.

The goldfish simulator answers "how fast does this deck win in a
vacuum?". That single number hides a lot. The evaluation layer probes
the *shape* of a deck's performance the way a tournament grinder would:

* **Confidence interval** — every win rate is reported with a Wilson
  95% interval so callers know when a difference is real vs. noise.
* **Flood / screw resistance** — re-run the deck with opening hands
  forced to be land-heavy and land-light. A resilient deck still
  functions; a fragile one collapses.
* **Interaction resilience** — re-run with a hypothetical opponent
  answering a fraction of spells (the goldfish ``disruption_rate``).
  Combo decks that fold to one counter score low here.
* **Inevitability** — does the deck still close when the game goes
  long? Built from late-game win share + card-advantage density.
* **Consistency** — inverse of kill-turn variance.

Everything here is deterministic given a seed and runs headlessly, so
it can feed both the optimizer's fitness and the human-facing rationale.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from app.oracle.profile import CardProfile
from app.sim.goldfish import GoldfishConfig, GoldfishReport, _play_game, goldfish
from app.sim.mulligan import MulliganProfile
from app.sim.policy import POLICIES, select_policy
from app.sim.state import build_initial_state


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def wilson_interval(wins: int, n: int, *, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% confidence interval for a binomial win rate.

    More accurate than the normal approximation at the extremes (win
    rates near 0 or 1) and for small sample sizes — exactly the regime
    matchup simulation lives in.
    """
    if n <= 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / denom
    return (_clamp(center - margin), _clamp(center + margin))


@dataclass
class DeckEvaluation:
    format_id: str
    archetype: str
    games: int
    win_rate: float
    win_rate_ci: tuple[float, float]
    avg_kill_turn: float
    kill_turn_stdev: float
    p25_kill_turn: float
    p75_kill_turn: float
    flood_resistance: float
    screw_resistance: float
    interaction_resilience: float
    inevitability: float
    consistency: float
    card_advantage_density: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "format_id": self.format_id,
            "archetype": self.archetype,
            "games": self.games,
            "win_rate": round(self.win_rate, 4),
            "win_rate_ci": [round(self.win_rate_ci[0], 4), round(self.win_rate_ci[1], 4)],
            "avg_kill_turn": round(self.avg_kill_turn, 3),
            "kill_turn_stdev": round(self.kill_turn_stdev, 3),
            "p25_kill_turn": round(self.p25_kill_turn, 2),
            "p75_kill_turn": round(self.p75_kill_turn, 2),
            "flood_resistance": round(self.flood_resistance, 3),
            "screw_resistance": round(self.screw_resistance, 3),
            "interaction_resilience": round(self.interaction_resilience, 3),
            "inevitability": round(self.inevitability, 3),
            "consistency": round(self.consistency, 3),
            "card_advantage_density": round(self.card_advantage_density, 3),
            "notes": list(self.notes),
        }


def _forced_open_winrate(
    deck: list[tuple[CardProfile, str]],
    *,
    policy,
    n_lands: int,
    games: int,
    max_turns: int,
    seed: int,
    starting_life: int,
) -> float:
    """Win rate when the opening hand is forced to contain ``n_lands``
    lands (rest non-lands). Probes flood (high n_lands) and screw (low)
    without touching the mulligan heuristic."""
    wins = 0
    played = 0
    for i in range(games):
        state = build_initial_state(
            deck, seed=seed + i, on_play=(i % 2 == 0), starting_life=starting_life
        )
        lands = [c for c in state.library if c.is_land]
        nonlands = [c for c in state.library if not c.is_land]
        k = min(n_lands, len(lands))
        rest = 7 - k
        hand = lands[:k] + nonlands[:rest]
        if len(hand) < 7:  # pool ran short on non-lands; top up with lands
            hand += lands[k : k + (7 - len(hand))]
        hand = hand[:7]
        keep = {id(c) for c in hand}
        state.hand = hand
        state.library = [c for c in state.library if id(c) not in keep]
        _play_game(state, policy=policy, max_turns=max_turns)
        played += 1
        if state.win_turn is not None:
            wins += 1
    return wins / max(1, played)


def _card_advantage_density(deck: list[tuple[CardProfile, str]]) -> float:
    """Raw card-advantage potential of the non-land spells, normalized
    to [0, 1]. Rewards draw + selection + recurring value engines."""
    total = 0.0
    nonland = 0
    for p, tl in deck:
        if "land" in tl.lower() or p.role_weights.land >= 0.9:
            continue
        nonland += 1
        ev = p.effect_vector
        total += ev.cards_drawn + max(0.0, ev.ca_delta)
        total += 0.6 * p.role_weights.value_engine
    if nonland == 0:
        return 0.0
    # ~10-18 points of card advantage across a deck is a strong engine.
    return _clamp(total / 14.0)


def evaluate_deck(
    deck: list[tuple[CardProfile, str]],
    *,
    format_id: str = "modern",
    games: int = 200,
    max_turns: int = 12,
    seed: int = 1729,
    policy=None,
    mulligan_profile: MulliganProfile | None = None,
    disruption_rate: float = 0.25,
) -> DeckEvaluation:
    """Run the full evaluation battery on ``deck``.

    Four goldfish passes (baseline, flooded open, screwed open,
    disrupted) plus structural card-advantage analysis. ~``4 * games``
    simulated games total, so keep ``games`` modest (200-400) for
    interactive use.
    """
    from app.optimizer.format_config import get_format_config

    fmt = get_format_config(format_id) if _format_known(format_id) else None
    starting_life = fmt.starting_life if fmt else 20
    needs_action = fmt.needs_action_by_turn if fmt else 3

    role_profile: dict[str, float] = {}
    for p, _ in deck:
        for role, w in p.role_weights.to_dict().items():
            role_profile[role] = role_profile.get(role, 0.0) + w
    archetype = select_policy(role_profile)
    policy = policy or POLICIES[archetype]
    mp = mulligan_profile or MulliganProfile()

    base_cfg = GoldfishConfig(
        games=games, max_turns=max_turns, seed=seed, starting_life=starting_life
    )
    base = goldfish(deck, policy=policy, mulligan_profile=mp, config=base_cfg)
    base_wr = base.wins / max(1, base.games_played)
    ci = wilson_interval(base.wins, base.games_played)

    # Flood / screw: forced openings.
    flood_wr = _forced_open_winrate(
        deck, policy=policy, n_lands=6, games=games, max_turns=max_turns,
        seed=seed + 7, starting_life=starting_life,
    )
    screw_wr = _forced_open_winrate(
        deck, policy=policy, n_lands=1, games=games, max_turns=max_turns,
        seed=seed + 13, starting_life=starting_life,
    )
    # Resistance = how much of the baseline win rate survives the bad
    # keep. A deck that wins *more* when flooded/screwed caps at 1.0.
    flood_resistance = _clamp(flood_wr / base_wr) if base_wr > 0 else 0.0
    screw_resistance = _clamp(screw_wr / base_wr) if base_wr > 0 else 0.0

    # Interaction resilience.
    dis_cfg = GoldfishConfig(
        games=games, max_turns=max_turns, seed=seed + 21,
        starting_life=starting_life, disruption_rate=disruption_rate,
    )
    disrupted = goldfish(deck, policy=policy, mulligan_profile=mp, config=dis_cfg)
    dis_wr = disrupted.wins / max(1, disrupted.games_played)
    interaction_resilience = _clamp(dis_wr / base_wr) if base_wr > 0 else 0.0

    # Inevitability: closes long games + card advantage.
    late_t = max(needs_action + 2, round(0.6 * max_turns))
    late_wins = sum(c for t, c in base.kill_turn_distribution.items() if t >= late_t)
    late_win_share = late_wins / max(1, base.games_played)
    ca_density = _card_advantage_density(deck)
    inevitability = _clamp(0.5 * ca_density + 0.5 * min(1.0, late_win_share * 2.5))

    # Consistency: inverse of kill-turn variance (relative to the mean).
    if base.avg_kill_turn > 0 and base.kill_turn_stdev >= 0:
        consistency = _clamp(1.0 - base.kill_turn_stdev / max(1.0, base.avg_kill_turn))
    else:
        consistency = 0.5

    notes: list[str] = []
    if interaction_resilience < 0.6:
        notes.append(
            f"fragile to interaction — wins drop {(1 - interaction_resilience):.0%} "
            f"under {disruption_rate:.0%} disruption"
        )
    if screw_resistance < 0.5:
        notes.append("mana-screw fragile: collapses on 1-land keeps")
    if flood_resistance < 0.5:
        notes.append("flood-fragile: drowns on 6-land keeps (consider mana sinks)")
    if ci[1] - ci[0] > 0.2:
        notes.append("wide confidence interval — increase games for a stable read")

    return DeckEvaluation(
        format_id=format_id,
        archetype=archetype,
        games=base.games_played,
        win_rate=base_wr,
        win_rate_ci=ci,
        avg_kill_turn=base.avg_kill_turn,
        kill_turn_stdev=base.kill_turn_stdev,
        p25_kill_turn=base.p25_kill_turn,
        p75_kill_turn=base.p75_kill_turn,
        flood_resistance=flood_resistance,
        screw_resistance=screw_resistance,
        interaction_resilience=interaction_resilience,
        inevitability=inevitability,
        consistency=consistency,
        card_advantage_density=ca_density,
        notes=notes,
    )


def _format_known(format_id: str) -> bool:
    try:
        from app.optimizer.format_config import FORMATS
        return format_id in FORMATS
    except ImportError:
        return False
