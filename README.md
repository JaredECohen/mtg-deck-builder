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

- live LLM orchestration in the critic loop (Claude/GPT clients are wired but
  default to mocks in tests; production keys not provisioned)
- pgvector retrieval
- authentication
- format support beyond Modern in the simulator/optimizer pipeline

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
| 7 | [api/app/critic/](api/app/critic/) | Builder (Claude) ⇄ Critic (GPT-5.5) loop with strict JSON envelope, 6-item evidence-bound rubric, deterministic short-circuit, auto-downgrade if critic over-approves, monotonic-improvement rollback, 4-round cap |
| 8 | [api/app/services/deck_rationale.py](api/app/services/deck_rationale.py) | Structured `DeckRationale`: headline, why-this-wins, key turns, mulligan guide, soft matchups, weakness callouts, critic transcript. Frontend renderer at [web/src/components/workshop/deck-rationale.tsx](web/src/components/workshop/deck-rationale.tsx) |

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
- Optimizer respects exclude-lists, color identity, and 4-of cap monotonically

## Pending / not yet wired

These are intentional gaps from the v1 simulator pass — each is tractable in
its own follow-up but not blocking on prior phases.

### Live LLM integration
- `AnthropicBuilder` and `OpenAICritic` clients in [api/app/critic/clients.py](api/app/critic/clients.py)
  are wired to the real SDKs but production keys / orchestration are not yet
  provisioned. Tests use `MockBuilder`/`MockCritic`. Next: env-driven client
  selection + cost gating.

### Worker backend
- `ThreadJobQueue` is the default and works without infra. `CeleryJobQueue`
  hook exists but the broker file (`celery_backend.py`) is not implemented.
  Next: minimal Celery+Redis wiring + healthcheck.

### Card profile cache
- [api/app/scripts/build_card_profiles.py](api/app/scripts/build_card_profiles.py)
  exists but isn't run in the bootstrap pipeline. `optimizer_service.py`
  currently profiles on the fly each request. Next: include profile build
  in the bootstrap flow, read from `card_profiles` table at request time.

### Optimizer ↔ legacy generator
- `/v1/decks/generate` still routes through the legacy heuristic generator;
  `/v1/jobs/optimize` is parallel. Next: feature-flag the new path and
  migrate the workshop UI to it.

### Frontend
- `DeckRationaleView` component is built but not yet imported into
  [web/src/components/deck-workshop.tsx](web/src/components/deck-workshop.tsx).
  Next: wire it under the deck-results tab, gated on rationale presence.

### Matchup matrix
- Currently stubbed in `DeckEnvelope.matchup_matrix`; the rubric uses it but
  no module populates it from real data. Next: add `api/app/sim/match.py`
  that runs goldfish vs. archetype-templated opponents.

### Sideboard generation
- The optimizer ignores sideboard slots. Next: add a sideboard pass that
  evolves a 15-card response set to the matchup matrix's worst entries.

### Synergy registry
- `KNOWN_COMBOS` in [api/app/synergy/builder.py](api/app/synergy/builder.py)
  lists 12 well-known Modern cliques. Next: pull from a versioned data file,
  add automation to flag new clique candidates from tournament data.

### Format support
- Modern only for now. Constraints, mulligan profiles, and policies are
  Modern-tuned. Standard / Pioneer / Commander would each need a phase-2/3
  re-tune (different curves, mulligan thresholds, ban lists).

### Tournament deck benchmark
- Phase 3's kill criterion ("kill turn matches community benchmarks") is
  validated against Burn only. Living End, Tron, and Yawgmoth need their
  own benchmark tests pinned.
