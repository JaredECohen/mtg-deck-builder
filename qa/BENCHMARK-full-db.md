# Deck-generation benchmark

Deterministic, LLM-free run of `qa/benchmark.py` (see `qa/README.md`).

- Run at: `2026-10-13 01:29 UTC`
- Git commit: `38b0ed0`
- Database: full local DB (read-only temp copy) (33794 cards, 92 archetypes, card data as of 2026-07-17)
- Scenarios: 108 (constructed 60, commander 24, prompt 24); wall time 51.8 s

## Pass rates

| Metric | Pass rate | Passed / applicable | What it checks |
|---|---|---|---|
| http_success | 100.0% | 108 / 108 | generate returned HTTP 200 |
| legality | 100.0% | 108 / 108 | returned list re-validated via /v1/decks/validate is legal |
| deck_size | 100.0% | 108 / 108 | constructed main = 60; commander main = 99 + commander |
| land_count | 100.0% | 108 / 108 | constructed 14-28 lands; commander 30-42 |
| color_fidelity | 100.0% | 80 / 80 | no card outside requested colors / commander identity, every requested color on a nonland card |
| budget_adherence | 100.0% | 56 / 56 | recomputed price (main + side + commander) <= requested budget |
| sideboard_completeness | 100.0% | 78 / 78 | constructed bo3 sideboard = 15, bo1 = 0 |
| bracket_compliance | 100.0% | 20 / 20 | bracket.estimated <= max(target, 2) (a list shows a floor of 2), and no game changers when target <= 2 |
| refine_success | 100.0% | 28 / 28 | scripted refine drops the excluded card, adds the included one, keeps lands, stays legal |
| prompt_fidelity | 100.0% | 24 / 24 | prompt-only request honors the prompt's colors / price / commander |

## By format

| Metric | standard | pioneer | modern | legacy | commander |
|---|---|---|---|---|---|
| http_success | 100% (20/20) | 100% (19/19) | 100% (21/21) | 100% (18/18) | 100% (30/30) |
| legality | 100% (20/20) | 100% (19/19) | 100% (21/21) | 100% (18/18) | 100% (30/30) |
| deck_size | 100% (20/20) | 100% (19/19) | 100% (21/21) | 100% (18/18) | 100% (30/30) |
| land_count | 100% (20/20) | 100% (19/19) | 100% (21/21) | 100% (18/18) | 100% (30/30) |
| color_fidelity | 100% (14/14) | 100% (14/14) | 100% (14/14) | 100% (14/14) | 100% (24/24) |
| budget_adherence | 100% (10/10) | 100% (10/10) | 100% (10/10) | 100% (10/10) | 100% (16/16) |
| sideboard_completeness | 100% (20/20) | 100% (19/19) | 100% (21/21) | 100% (18/18) | n/a |
| bracket_compliance | n/a | n/a | n/a | n/a | 100% (20/20) |
| refine_success | 100% (5/5) | 100% (5/5) | 100% (5/5) | 100% (5/5) | 100% (8/8) |
| prompt_fidelity | 100% (5/5) | 100% (4/4) | 100% (6/6) | 100% (3/3) | 100% (6/6) |

## Latency (in-process TestClient)

| Endpoint | Calls | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| generate | 108 | 166.8 | 1488.0 | 3251.9 |
| refine | 28 | 146.0 | 2488.2 | 2707.5 |
| validate | 136 | 6.3 | 19.4 | 212.2 |

## Failures

None.

