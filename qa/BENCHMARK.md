# Deck-generation benchmark

Deterministic, LLM-free run of `qa/benchmark.py` (see `qa/README.md`).

- Run at: `2026-10-13 00:34 UTC`
- Git commit: `3e0672e`
- Database: fixture `api/tests/fixtures/cards.db.gz` (temp copy) (1936 cards, 93 archetypes, card data as of 2026-06-26)
- Scenarios: 108 (constructed 60, commander 24, prompt 24); wall time 12.1 s

## Pass rates

| Metric | Pass rate | Passed / applicable | What it checks |
|---|---|---|---|
| http_success | 100.0% | 108 / 108 | generate returned HTTP 200 |
| legality | 100.0% | 108 / 108 | returned list re-validated via /v1/decks/validate is legal |
| deck_size | 100.0% | 108 / 108 | constructed main = 60; commander main = 99 + commander |
| land_count | 99.1% | 107 / 108 | constructed 14-28 lands; commander 30-42 |
| color_fidelity | 90.0% | 72 / 80 | no card outside requested colors / commander identity, every requested color on a nonland card |
| budget_adherence | 87.5% | 49 / 56 | recomputed price (main + side + commander) <= requested budget |
| sideboard_completeness | 34.6% | 27 / 78 | constructed bo3 sideboard = 15, bo1 = 0 |
| bracket_compliance | 0.0% | 0 / 20 | bracket.estimated <= target, and no game changers when target <= 2 |
| refine_success | 46.4% | 13 / 28 | scripted refine drops the excluded card, adds the included one, keeps lands, stays legal |
| prompt_fidelity | 20.8% | 5 / 24 | prompt-only request honors the prompt's colors / price / commander |

## By format

| Metric | standard | pioneer | modern | legacy | commander |
|---|---|---|---|---|---|
| http_success | 100% (20/20) | 100% (19/19) | 100% (21/21) | 100% (18/18) | 100% (30/30) |
| legality | 100% (20/20) | 100% (19/19) | 100% (21/21) | 100% (18/18) | 100% (30/30) |
| deck_size | 100% (20/20) | 100% (19/19) | 100% (21/21) | 100% (18/18) | 100% (30/30) |
| land_count | 100% (20/20) | 100% (19/19) | 95% (20/21) | 100% (18/18) | 100% (30/30) |
| color_fidelity | 100% (14/14) | 86% (12/14) | 93% (13/14) | 79% (11/14) | 92% (22/24) |
| budget_adherence | 100% (10/10) | 100% (10/10) | 80% (8/10) | 100% (10/10) | 69% (11/16) |
| sideboard_completeness | 25% (5/20) | 26% (5/19) | 57% (12/21) | 28% (5/18) | n/a |
| bracket_compliance | n/a | n/a | n/a | n/a | 0% (0/20) |
| refine_success | 60% (3/5) | 60% (3/5) | 0% (0/5) | 40% (2/5) | 62% (5/8) |
| prompt_fidelity | 20% (1/5) | 0% (0/4) | 33% (2/6) | 33% (1/3) | 17% (1/6) |

## Latency (in-process TestClient)

| Endpoint | Calls | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| generate | 108 | 27.5 | 330.9 | 973.1 |
| refine | 28 | 22.4 | 60.8 | 62.7 |
| validate | 136 | 6.6 | 252.1 | 394.9 |

## Failures

### land_count (1 failing)

- `prompt-modern-izzet-prowess-with-lots-of-burn`: 34 lands (want 14-28)

### color_fidelity (8 failing)

- `pioneer-rgw-combo-none-creative-bo1`: requested color(s) G on no nonland card
- `pioneer-gwu-tokens-mid-constraint-bo3`: requested color(s) G on no nonland card
- `modern-bgu-spells-none-fast-bo1`: requested color(s) G on no nonland card
- `legacy-wb-midrange-low-constraint-bo3`: requested color(s) B on no nonland card
- `legacy-gur-tribal-mid-fast-bo1`: requested color(s) G on no nonland card
- `legacy-wub-tempo-low-creative-bo3`: requested color(s) B on no nonland card
- `commander-ub-control-none-creative-b5`: requested color(s) U on no nonland card
- `commander-colorless-tempo-mid-constraint-b1`: off-color vs C: Adorned Pouncer (W), Afterlife (W), Angel of Sanctions (W), Bishop of Wings (W), Brimaz, King of Oreskos (W), Castle Ardenvale (W) (+37 more)

### budget_adherence (7 failing)

- `modern-u-ramp-low-constraint-bo1`: price $156.49 > budget $80 (8 unpriced)
- `modern-g-tempo-low-fast-bo3`: price $114.42 > budget $80 (4 unpriced)
- `commander-u-midrange-low-constraint-b1`: price $133.09 > budget $75 (17 unpriced)
- `commander-wbg-midrange-low-creative-b4`: price $202.95 > budget $75 (22 unpriced)
- `commander-anycolor-spells-low-constraint-bnone`: price $136.90 > budget $75 (23 unpriced)
- `commander-niv-mizzet-midrange-low-constraint-b1`: price $132.36 > budget $75 (23 unpriced)
- `commander-ghave-spells-low-fast-b3`: price $190.13 > budget $75 (23 unpriced)

### sideboard_completeness (51 failing)

- `standard-w-aggro-none-constraint-bo3`: bo3 sideboard=0 (want 15)
- `standard-b-midrange-low-creative-bo3`: bo3 sideboard=0 (want 15)
- `standard-r-combo-none-fast-bo1`: bo1 sideboard=2 (want 0)
- `standard-g-tokens-mid-creative-bo3`: bo3 sideboard=0 (want 15)
- `standard-ub-spells-none-creative-bo3`: bo3 sideboard=0 (want 15)
- `standard-br-tribal-mid-constraint-bo1`: bo1 sideboard=2 (want 0)
- `standard-rg-tempo-low-fast-bo3`: bo3 sideboard=0 (want 15)
- `standard-wub-control-mid-fast-bo3`: bo3 sideboard=0 (want 15)
- `standard-brg-combo-none-fast-bo3`: bo3 sideboard=2 (want 15)
- `standard-anycolor-ramp-low-constraint-bo3`: bo3 sideboard=0 (want 15)
- `pioneer-u-combo-none-creative-bo3`: bo3 sideboard=0 (want 15)
- `pioneer-r-ramp-low-creative-bo3`: bo3 sideboard=0 (want 15)
- ... and 39 more (see `qa/artifacts/benchmark.json`)

### bracket_compliance (20 failing)

- `commander-u-midrange-low-constraint-b1`: no bracket assessment in response
- `commander-b-tokens-mid-fast-b2`: no bracket assessment in response
- `commander-r-spells-low-fast-b3`: no bracket assessment in response
- `commander-g-tempo-mid-creative-b4`: no bracket assessment in response
- `commander-ub-control-none-creative-b5`: no bracket assessment in response
- `commander-wb-ramp-none-constraint-b1`: no bracket assessment in response
- `commander-bg-tribal-low-fast-b2`: no bracket assessment in response
- `commander-wub-aggro-none-fast-b3`: no bracket assessment in response
- `commander-wbg-midrange-low-creative-b4`: no bracket assessment in response
- `commander-gur-tokens-mid-creative-b5`: no bracket assessment in response
- `commander-colorless-tempo-mid-constraint-b1`: no bracket assessment in response
- `commander-krenko-control-none-fast-b2`: no bracket assessment in response
- ... and 8 more (see `qa/artifacts/benchmark.json`)

### refine_success (15 failing)

- `standard-w-aggro-none-constraint-bo3`: excluded Get Lost still present (main 4->0, side 4)
- `standard-r-combo-none-fast-bo1`: excluded Witchstalker Frenzy still present (main 2->0, side 2)
- `pioneer-gu-midrange-low-fast-bo3`: excluded Supreme Phantom still present (main 4->0, side 4)
- `pioneer-wbg-ramp-low-creative-bo1`: excluded Elvish Mystic still present (main 4->0, side 4)
- `modern-w-tokens-mid-creative-bo3`: excluded Springleaf Drum still present (main 4->0, side 4)
- `modern-r-tribal-mid-constraint-bo1`: excluded Lightning Bolt still present (main 4->0, side 4)
- `modern-ub-control-mid-fast-bo3`: excluded Springleaf Drum still present (main 4->0, side 4)
- `modern-gw-tokens-mid-creative-bo1`: excluded Aether Vial still present (main 4->0, side 4)
- `modern-rwb-tribal-mid-constraint-bo3`: excluded Thoughtseize still present (main 4->0, side 4)
- `legacy-ur-combo-none-creative-bo1`: excluded Ponder still present (main 4->0, side 3)
- `legacy-gu-spells-none-constraint-bo3`: excluded Ponder still present (main 4->0, side 4)
- `legacy-ubr-aggro-none-fast-bo1`: excluded Ponder still present (main 4->0, side 4)
- ... and 3 more (see `qa/artifacts/benchmark.json`)

### prompt_fidelity (19 failing)

- `prompt-standard-cheap-mono-green-stompy-under-40`: off-color vs G: Island (U), Kaito, Bane of Nightmares (BU), Preacher of the Schism (B), Restless Reef (BU), Spectral Sailor (U), Spell Pierce (U) (+5 more); requested color(s) G on no nonland card; price $213.98 > $40
- `prompt-modern-izzet-prowess-with-lots-of-burn`: off-color vs RU: Inspiring Vantage (RW), Path to Exile (W), Sacred Foundry (RW), Solitude (W), Sunbaked Canyon (RW); requested color(s) U on no nonland card
- `prompt-pioneer-rakdos-midrange-budget-100`: off-color vs BR: Forest (G), Intrepid Paleontologist (G), Outland Liberator // Frenzied Trapbreaker (G), Troublemaker Ouphe (G); requested color(s) R on no nonland card; price $242.04 > $100
- `prompt-commander-golgari-graveyard-recursion-deck`: requested color(s) G on no nonland card
- `prompt-commander-mardu-aristocrats-under-150`: requested color(s) R on no nonland card; price $549.96 > $150
- `prompt-standard-boros-aggro-with-tokens`: off-color vs RW: Dyadrine, Synthesis Amalgam (GW), Forest (G), Seraphic Steed (GW), Tolsimir, Midnight's Light (GW)
- `prompt-pioneer-mono-black-midrange`: off-color vs B: Forest (G), Intrepid Paleontologist (G), Outland Liberator // Frenzied Trapbreaker (G), Troublemaker Ouphe (G)
- `prompt-modern-esper-midrange-under-200`: off-color vs BUW: Endurance (G), Forest (G), Intrepid Paleontologist (G), Tarmogoyf (G); requested color(s) UW on no nonland card; price $344.65 > $200
- `prompt-legacy-dimir-tempo`: off-color vs BU: Lightning Bolt (R), Mountain (R), Runescale Stormbrood // Chilling Screech (RU); requested color(s) B on no nonland card
- `prompt-standard-simic-ramp-with-big-creatures`: requested color(s) U on no nonland card
- `prompt-modern-cheap-gruul-ramp`: requested color(s) R on no nonland card
- `prompt-commander-temur-spellslinger-100-budget`: off-color vs GRU: Adorned Pouncer (W), Angel of Sanctions (W), Anointed Procession (W), Bishop of Wings (W), Blood Artist (B), Brimaz, King of Oreskos (W) (+27 more); requested color(s) GRU on no nonland card; price $462.73 > $100
- ... and 7 more (see `qa/artifacts/benchmark.json`)

