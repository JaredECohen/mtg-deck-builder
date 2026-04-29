"""Deck optimizer.

Takes a constraint envelope (format, colors, budget, must-include,
must-exclude, style) and a card pool, and returns the simulator-best
deck found within a CPU budget. Composed of:

* :mod:`fitness` — multi-axis fitness vector + scalar combine
* :mod:`swap_proposals` — propose swaps targeted at the worst metric
* :mod:`anneal` — simulated annealing acceptance loop
* :mod:`seeder` — produce starting candidates from corpus archetypes
* :mod:`constraints` — hard-constraint filter and validator
"""

from app.optimizer.constraints import OptimizerConstraints, validate_constraints
from app.optimizer.fitness import (
    FitnessVector,
    OptimizerCandidate,
    compute_fitness,
    fitness_score,
)
from app.optimizer.anneal import AnnealConfig, OptimizerResult, optimize_deck
from app.optimizer.seeder import seed_candidates
from app.optimizer.swap_proposals import propose_swaps

__all__ = [
    "AnnealConfig",
    "FitnessVector",
    "OptimizerCandidate",
    "OptimizerConstraints",
    "OptimizerResult",
    "compute_fitness",
    "fitness_score",
    "optimize_deck",
    "propose_swaps",
    "seed_candidates",
    "validate_constraints",
]
