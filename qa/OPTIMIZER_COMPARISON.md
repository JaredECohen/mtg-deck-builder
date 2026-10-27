# Optimizer vs legacy generator

Database: CI fixture (about 2,000 cards).
Cards: 1928.
Each optimized list is what `generate_via_optimizer` would return
(the production annealer: 8 rounds, 3 proposals, 120 sims, seed 1729).
Win rate, average kill turn, and consistency come from
`evaluate_decklist` on that returned list, 60 games, seed 1729.
Commander is not in this table: the optimizer path returns the legacy
Commander deck without annealing.

The default stays `MTG_USE_OPTIMIZER_DEFAULT=false`. A result on the
CI fixture (about 2,000 cards) is not a production result. Re-run
`python3 qa/compare_generators.py --database-url sqlite:///...` against
the full ingest before flipping the flag. The annealer also keeps the
legacy list when fitness does not rise by at least 0.01.

A win rate of 0.000 with kill turn at the cap means the goldfish
never closed the game. Those rows still count: the optimizer returned
the same list, so the scores match.

| Scenario | Kept legacy | Legacy win | Optimizer win | Legacy kill | Optimizer kill | Legacy consistency | Optimizer consistency | Legacy $ | Optimizer $ | Optimizer seconds |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Modern mono-red aggro | yes | 0.000 | 0.000 | 13.00 | 13.00 | 1.000 | 1.000 | 35.06 | 35.06 | 2.1 |
| Modern Izzet spells | yes | 0.000 | 0.000 | 13.00 | 13.00 | 1.000 | 1.000 | 98.62 | 98.62 | 2.3 |
| Pioneer mono-black midrange | yes | 0.000 | 0.000 | 13.00 | 13.00 | 1.000 | 1.000 | 45.02 | 45.02 | 2.1 |
| Standard mono-white aggro | yes | 0.450 | 0.450 | 10.15 | 10.15 | 0.847 | 0.847 | 28.69 | 28.69 | 2.1 |

## Notes

- Modern mono-red aggro: Simulator optimization kept the generated list: the simulator found no improvement over the generated list.
- Modern mono-red aggro: legacy legal=True, optimizer legal=True, legacy generate 0.2s, evaluation games=60.
- Modern Izzet spells: Simulator optimization kept the generated list: the simulator found no improvement over the generated list.
- Modern Izzet spells: legacy legal=True, optimizer legal=True, legacy generate 0.0s, evaluation games=60.
- Pioneer mono-black midrange: Simulator optimization kept the generated list: the simulator found no improvement over the generated list.
- Pioneer mono-black midrange: legacy legal=True, optimizer legal=True, legacy generate 0.0s, evaluation games=60.
- Standard mono-white aggro: Simulator optimization kept the generated list: the simulator found no improvement over the generated list.
- Standard mono-white aggro: legacy legal=True, optimizer legal=True, legacy generate 0.0s, evaluation games=60.

Scenarios where the optimizer changed the list, stayed legal, and gained at least 0.03 win rate: 0 of 4.
That count is not a decision to switch the default.
