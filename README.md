# MTG Deck Builder

Greenfield monorepo implementing the v1 foundation from [PRODUCT_SPEC.md](/Users/jaredcohen/code/mtg-deck-builder/PRODUCT_SPEC.md).

## Structure

- `api/`: FastAPI backend for deck generation, validation, refinement, export, and data ingestion
- `web/`: Next.js frontend for the deck workshop experience
- `packages/shared/`: shared product/domain documentation and JSON schema placeholders
- `infra/`: local infrastructure notes

## Local Development

### Backend

```bash
cd /Users/jaredcohen/code/mtg-deck-builder/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.scripts.seed_sample_cards
python -m app.scripts.ingest_tournament_decks
python -m app.scripts.build_archetypes
uvicorn app.main:app --reload
```

### Frontend

```bash
cd /Users/jaredcohen/code/mtg-deck-builder/web
npm install
npm run dev
```

## Current Status

This repository includes:

- production-oriented API scaffolding
- deterministic rules-based deck validation
- heuristic deck generation (legacy path, served by `/v1/decks/generate`)
- a **first-principles simulator + optimizer pipeline** for Modern (new path, served by `/v1/jobs/optimize`) — see [Simulator architecture](#simulator-architecture) below
- structured sample archetype data
- Scryfall bulk-data ingestion script
- frontend deck workshop UI wired to the API

## Postgres Card Ingestion

The card repository is now Postgres-backed.

### Local bootstrap

```bash
createdb mtg_deck_builder
cd /Users/jaredcohen/code/mtg-deck-builder/api
python -m app.scripts.seed_sample_cards
python -m app.scripts.ingest_tournament_decks
python -m app.scripts.build_archetypes
```

### Full Scryfall ingestion

```bash
cd /Users/jaredcohen/code/mtg-deck-builder/api
python -m app.scripts.ingest_scryfall
```

This creates the schema, downloads Scryfall `default_cards`, normalizes card fields, and upserts them into the `cards` table.

## Tournament Deck And Archetype Pipeline

Archetypes are now derived offline from tournament deck rows stored in Postgres.

Bootstrap flow:

```bash
cd /Users/jaredcohen/code/mtg-deck-builder/api
python -m app.scripts.seed_sample_cards
python -m app.scripts.ingest_tournament_decks
python -m app.scripts.build_archetypes
```

Pipeline stages:

- `ingest_tournament_decks`: normalizes raw decklists into `tournament_decks`
- `build_archetypes`: groups similar decks into archetypes and upserts the `archetypes` table

At runtime, the API reads both cards and archetypes from Postgres, not JSON files.

It does not yet include:

- pgvector retrieval
- authentication
- live Redis/Celery broker (the backend is implemented and selectable via
  `MTG_WORKER_BACKEND=celery` + `REDIS_URL`, but no broker is provisioned
  by default — `ThreadJobQueue` is the default)

## Simulator architecture

The Modern deck-construction pipeline is a multi-stage simulator-driven
optimizer. Each stage is independently testable and runs without FastAPI/DB
dependencies. Implemented in 8 phases (199 backend tests passing as of
last commit):

| Layer | Module | Purpose |
|---|---|---|
| 1 | [api/app/oracle/](api/app/oracle/) | Parse oracle text into typed `CardProfile`: cost vector, effect vector, role weights, combo primitives, alt-cost detection (Evoke/Suspend/Cascade/Delve/Channel/Flashback/Cycling) |
| 2 | [api/app/sim/mana.py](api/app/sim/mana.py) | Mana-base solver: closed-form hypergeometric (Karsten thresholds) + Monte Carlo for fetch/shock/MDFC/painland interactions |
| 3 | [api/app/sim/goldfish.py](api/app/sim/goldfish.py) | Solitaire turn-by-turn simulator with 4 pluggable policies (aggro/combo/control/midrange) → kill-turn distribution |
| 4 | [api/app/synergy/](api/app/synergy/) | Synergy graph: produces→requires edges, tutor→closer edges, known combo cliques (Splinter Twin, Storm, Living End, Yawgmoth, Ad Nauseam, Hardened Scales, Devoted Druid, Goryo's, Thoracle, Scapeshift, Amulet Titan). Criticality scored via vanilla-replacement ∆kill-turn |
| 5 | [api/app/optimizer/](api/app/optimizer/) | Simulated annealing with targeted swap proposals (driven by worst fitness axis), constraint-repair branch, monotonic violation reduction, 4-of cap enforcement |
| 6 | [api/app/workers/](api/app/workers/) + [/v1/jobs/](api/app/main.py) | Backend-agnostic async job queue (ThreadPoolExecutor default, Celery hook ready), result caching by hash, async API endpoints |
| 7 | [api/app/critic/](api/app/critic/) | Builder (Claude) ⇄ Critic (GPT-5.5) loop with strict JSON envelope, 6-item evidence-bound rubric, deterministic short-circuit, auto-downgrade if critic over-approves, monotonic-improvement rollback, 4-round cap. Live SDK clients with retries + cost gating; falls back to deterministic mocks when API keys are absent |
| 8 | [api/app/services/deck_rationale.py](api/app/services/deck_rationale.py) | Structured `DeckRationale`: headline, why-this-wins, key turns, mulligan guide, soft matchups, weakness callouts, critic transcript. Frontend renderer at [web/src/components/workshop/deck-rationale.tsx](web/src/components/workshop/deck-rationale.tsx), wired into [deck-workshop.tsx](web/src/components/deck-workshop.tsx) via [use-deck-rationale](web/src/hooks/use-deck-rationale.ts) |
| 9 | [api/app/sim/match.py](api/app/sim/match.py) + [meta_archetypes.py](api/app/sim/meta_archetypes.py) | Two-player matchup simulator: parallel goldfish + simplified combat with blocking + opponent instant-removal probe. Builds the matchup matrix consumed by the critic's R3 rubric and the optimizer's `matchup_strength` fitness axis. Pre-baked Modern meta opponents (Burn, Murktide, Tron, Living End) |
| 10 | [api/app/optimizer/format_config.py](api/app/optimizer/format_config.py) | Format-specific config: deck size, singleton rule, starting life, ideal land range, mulligan profile floor. Drives Modern, Standard, Pioneer, Legacy, **and Commander** (99-card singleton, 40 life, 35-42 lands) |
| 11 | [api/app/workers/celery_backend.py](api/app/workers/celery_backend.py) | Celery+Redis backend behind the same `JobQueue` interface — selectable via `MTG_WORKER_BACKEND=celery`. Result caching via Redis hash; ThreadPoolExecutor remains the default for dev/tests |

### Skills (cached one-time analyses)

Versioned LLM system prompts under [.claude/skills/](.claude/skills/), used
out-of-loop with results cached so generation stays fast and deterministic.

- `card-evaluator` — fallback parser for cards whose oracle text the
  deterministic parser can't fully cover (writes back to `card_profiles`)
- `deck-critic` — GPT-5.5 system prompt for the critic loop
- `builder-responder` — Claude system prompt for the builder side of the loop
- `goldfish-coach` — narrates structured `DeckRationale` into prose

### Benchmarks pinned by tests

- Burn manabase: solver outputs 19–20 lands (matches published lists ±1)
- Murktide manabase: 19 lands, U sources hit T2 ≥ 85% / T4 ≥ 95%
- Burn goldfish: kill-turn 4.8–5.2 (community benchmark ~4.5–5)
- Aggro-curated deck scores higher fitness than off-curve dragon pile
- Optimizer respects exclude-lists, color identity, and playset cap monotonically (4-of for constructed; 1-of for Commander)
- Burn-vs-Burn matchup ≈ 50% (symmetric self-play, with on-the-play alternation)
- Matchup matrix differentiates archetypes: Burn 71.8% avg vs the meta, Murktide loses to Burn 16% (fast-clock vs. tempo)
- All 5 formats (Modern / Standard / Pioneer / Legacy / Commander) flag size, color, and playset violations correctly
- Synergy graph is cached by deck identity + profile_version — same deck → same instance
- Goldfish ETB-tapped lands are tracked per-turn (not just T1)
- Match simulator's instant interaction taps mana — no infinite removal
- Commander matchups use (3-5) ideal lands (format mulligan floor), not Modern's (2-5)
- Cross-format matchups apply the opponent's *native* format mulligan profile
  (e.g. Commander candidate vs Modern Burn opponent each mulligan correctly)
- Sideboard generator targets losing matchups first; produces 15 deduped slots
  with rationales tagged by matchup; respects deck color identity; returns
  empty plan for Commander (sideboard_size=0)
- Sideboard plan is rendered in the workshop UI under the rationale section
- Coach prose moved off the hot path — fetched lazily via `POST /v1/jobs/{id}/prose`
  (returns 202 while parent job is still running)
- Tron-assembly rule modeled: Urza Tower + Power Plant + Mine together produce
  7 colorless mana, enabling T3 7-drops in goldfish runs

## Pending / not yet wired

These are intentional gaps remaining after the format expansion + LLM/Celery
+ matchup pass. Each is tractable in its own follow-up.

### Optimizer ↔ legacy generator
- `/v1/decks/generate` still defaults to the legacy heuristic generator. Set
  `MTG_USE_OPTIMIZER_DEFAULT=true` to route requests through the optimizer
  pipeline (synchronous wrapper, falls back to legacy on error).
- Next: flip the default once the optimizer-default path has been
  exercised in staging.

### Synergy registry
- `KNOWN_COMBOS` in [api/app/synergy/builder.py](api/app/synergy/builder.py)
  lists 12 well-known Modern cliques. Next: pull from a versioned data file,
  add automation to flag new clique candidates from tournament data.

### Meta archetypes per format
- [api/app/sim/meta_archetypes.py](api/app/sim/meta_archetypes.py) contains
  Modern opponents (Burn, Murktide, Tron, Living End). Standard / Pioneer /
  Legacy / Commander need their own meta sets. The matchup pipeline is
  format-aware; the data isn't.

### Tournament deck benchmark coverage
- Kill-turn benchmarks are pinned for Burn only. Living End, Yawgmoth, and
  Tron each need their own benchmark tests (currently their goldfish kill
  turns aren't asserted, just produced).
