# MTG Deck Builder

Full-stack deck-construction app with a **first-principles simulator + optimizer**
that produces tournament-grade decks for all five major formats. FastAPI
backend, Next.js frontend, structured `DeckRationale` output narrated by an
optional LLM coach.

**Current state:** 251 backend tests passing, frontend TypeScript clean,
end-to-end optimizer flow live behind a feature flag.

## Structure

- `api/`: FastAPI backend, simulator kernel, optimizer, critic loop
- `web/`: Next.js frontend
- `packages/shared/`: shared product/domain documentation
- `infra/`: local infrastructure notes
- `.claude/skills/`: versioned LLM system prompts (card-evaluator,
  deck-critic, builder-responder, goldfish-coach)

## Local Development

### Backend

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.scripts.seed_sample_cards
python -m app.scripts.ingest_tournament_decks
python -m app.scripts.build_archetypes
python -m app.scripts.build_card_profiles      # populates the profile cache
uvicorn app.main:app --reload
```

### Frontend

```bash
cd web
npm install
npm run dev
```

### Tests

```bash
cd api
python -m pytest -q     # 251 passing, 1 skipped (Celery without Redis)
```

## Capabilities

### Legacy heuristic path (default)
- `/v1/decks/generate` — rules-based deck assembly using archetype templates
- `/v1/decks/refine`, `/v1/decks/analyze`, `/v1/decks/validate` —
  archetype-similarity analysis and rule checking

### Optimizer pipeline (new)
- `POST /v1/jobs/optimize` — submit a constraint envelope (format,
  colors, budget, includes, excludes, archetype recipes)
- `GET /v1/jobs/{id}` — poll for completion
- `POST /v1/jobs/{id}/prose` — lazily produce LLM-narrated coach prose
  (202 while job is still running, 200 when ready, 404 if unknown)

To make the optimizer the default for `/v1/decks/generate`:

```bash
export MTG_USE_OPTIMIZER_DEFAULT=true
```

The wrapper returns the same `DeckResponse` shape and falls back to the
legacy generator on any error so prod traffic isn't affected by a bad deploy.

## Simulator architecture

Eleven independently-testable layers, all running headlessly without
FastAPI/DB dependencies:

| Layer | Module | Purpose |
|---|---|---|
| 1 | [api/app/oracle/](api/app/oracle/) | Parse oracle text into typed `CardProfile`: cost vector, effect vector, role weights, combo primitives, alt-cost detection (Evoke/Suspend/Cascade/Delve/Channel/Flashback/Cycling) |
| 2 | [api/app/sim/mana.py](api/app/sim/mana.py) | Mana-base solver: closed-form hypergeometric (Karsten thresholds) + Monte Carlo for fetch/shock/MDFC/painland interactions |
| 3 | [api/app/sim/goldfish.py](api/app/sim/goldfish.py) | Solitaire turn-by-turn simulator with 4 pluggable policies (aggro/combo/control/midrange) → kill-turn distribution. Tron-assembly rule, ETB-tapped tracking |
| 4 | [api/app/synergy/](api/app/synergy/) | Synergy graph: produces→requires edges, tutor→closer edges, 12 known combo cliques (Splinter Twin, Storm, Living End, Yawgmoth, Ad Nauseam, Hardened Scales, Devoted Druid, Goryo's, Thoracle, Scapeshift, Amulet Titan). Criticality scored via vanilla-replacement ∆kill-turn. Cached by deck identity + profile_version |
| 5 | [api/app/optimizer/](api/app/optimizer/) | Simulated annealing with targeted swap proposals (driven by worst fitness axis), constraint-repair branch, monotonic violation reduction, format-aware playset cap (4-of constructed, 1-of singleton) |
| 6 | [api/app/workers/](api/app/workers/) | Backend-agnostic async job queue. `ThreadJobQueue` (default, in-process) and `CeleryJobQueue` (Redis-backed, selectable via `MTG_WORKER_BACKEND=celery`). Result caching by hash |
| 7 | [api/app/critic/](api/app/critic/) | Builder (Claude) ⇄ Critic (GPT-5.5) loop with strict JSON envelope, 6-item evidence-bound rubric, deterministic short-circuit, auto-downgrade if critic over-approves, monotonic-improvement rollback, 4-round cap. Live SDK clients with retries + shared per-job cost budget; falls back to deterministic mocks when API keys are absent |
| 8 | [api/app/services/deck_rationale.py](api/app/services/deck_rationale.py) | Structured `DeckRationale`: headline, why-this-wins, key turns, mulligan guide, soft matchups, weakness callouts, critic transcript. Optional LLM-narrated coach prose, fetched lazily via `POST /v1/jobs/{id}/prose` |
| 9 | [api/app/sim/match.py](api/app/sim/match.py) + [meta_archetypes.py](api/app/sim/meta_archetypes.py) | Two-player matchup simulator: parallel goldfish + simplified combat with blocking + opponent instant-removal probe (taps mana — no infinite removal). Per-side format mulligan profiles for cross-format matchups. Pre-baked Modern meta opponents (Burn, Murktide, Tron, Living End) |
| 10 | [api/app/optimizer/format_config.py](api/app/optimizer/format_config.py) | Format-specific config: deck size, singleton rule, starting life, ideal land range, mulligan profile floor. Drives Modern, Standard, Pioneer, Legacy, **and Commander** (99-card singleton, 40 life, 35-42 lands) |
| 11 | [api/app/optimizer/sideboard.py](api/app/optimizer/sideboard.py) | Sideboard generator: targets losing matchups first, classifies opponent archetype, ranks pool cards by answer category. Respects deck color identity; returns empty plan for Commander |

### Frontend integration

The deck workshop ([web/src/components/deck-workshop.tsx](web/src/components/deck-workshop.tsx))
shows the legacy generator's output by default. When a user clicks
"Run optimizer," the workshop submits to `/v1/jobs/optimize` via the
[useDeckRationale](web/src/hooks/use-deck-rationale.ts) hook, polls for
completion, and renders [DeckRationaleView](web/src/components/workshop/deck-rationale.tsx)
with full sections: headline, why-this-wins, key turns, mulligan guide,
matchup table, weakness callouts, critic transcript, and sideboard plan.

### Skills (versioned LLM system prompts)

Under [.claude/skills/](.claude/skills/). Used out-of-loop with results
cached so generation stays fast and deterministic.

- `card-evaluator` — fallback parser for cards whose oracle text the
  deterministic parser can't fully cover (writes back to `card_profiles`)
- `deck-critic` — GPT-5.5 system prompt for the critic loop
- `builder-responder` — Claude system prompt for the builder side
- `goldfish-coach` — narrates structured `DeckRationale` into prose

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Postgres connection | `sqlite:///var/mtg_deck_builder.db` |
| `CORS_ORIGINS` | Allowed CORS origins | `http://localhost:3000,http://127.0.0.1:3000` |
| `MTG_USE_OPTIMIZER_DEFAULT` | Route `/v1/decks/generate` through optimizer | `false` |
| `MTG_WORKER_BACKEND` | `thread` or `celery` | `thread` |
| `MTG_WORKER_THREADS` | ThreadPoolExecutor size | `4` |
| `REDIS_URL` | Celery broker + result backend | `redis://localhost:6379/0` |
| `ANTHROPIC_API_KEY` | Builder client + coach prose | (unset → mocks) |
| `OPENAI_API_KEY` | Critic client | (unset → mocks) |
| `MTG_BUILDER_MODEL` | Override Claude model | `claude-opus-4-7` |
| `MTG_CRITIC_MODEL` | Override GPT model | `gpt-5.5` |
| `MTG_COACH_MODEL` | Override Haiku model for prose | `claude-haiku-4-5-20251001` |
| `MTG_CRITIC_MAX_TOKENS_PER_CALL` | Per-call output cap | `4096` |
| `MTG_CRITIC_MAX_USD_PER_JOB` | Per-job cost cap (shared across rounds) | `1.50` |
| `MTG_COACH_DISABLE` | Force-skip coach prose even with key set | (unset) |
| `TCGPLAYER_AFFILIATE_URL` | TCGplayer affiliate deep-link prefix from Impact (e.g. `https://tcgplayer.pxf.io/c/123456/789012/21018`); every TCGplayer link served by the API is wrapped for attribution | (unset → untracked links) |
| `NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL` | Same prefix, inlined into the frontend for client-built "Shop This Deck" and mass-entry links | (unset) |

### Monetization

Monetized via **TCGplayer affiliate links** (the marketplace where players
actually buy MTG singles). Surfaces:

- **Card detail modal** — a primary **Buy on TCGplayer** button (uses the card's
  own product link, falling back to a name search).
- **Shop This Deck** panel on every generated deck — a **Buy entire deck on
  TCGplayer** button that opens a single [Mass Entry](https://www.tcgplayer.com/massentry)
  cart pre-filled with the whole list at the cheapest available sellers, plus
  per-card single links.

TCGplayer's program runs through [Impact](https://impact.com); once approved you
get a deep-link prefix — set both variables above to it. Links are wrapped at the
API read boundary (`app/services/affiliate.py`) and at build time on the
frontend, so changing the prefix never requires re-ingesting card data. The
required affiliate disclosure renders alongside every link surface.

## Postgres data pipeline

```bash
cd api
createdb mtg_deck_builder
python -m app.scripts.seed_sample_cards
python -m app.scripts.ingest_scryfall              # full Scryfall ingest (optional)
python -m app.scripts.ingest_tournament_decks
python -m app.scripts.build_archetypes
python -m app.scripts.build_card_profiles          # parses oracle text → card_profiles
```

The optimizer reads from `card_profiles` when populated and falls back
to on-the-fly profiling when it isn't (logs a warning).

## Benchmarks pinned by tests

- **Burn manabase** — solver outputs 19–20 lands (matches published lists ±1)
- **Murktide manabase** — 19 lands, U sources hit T2 ≥ 85% / T4 ≥ 95%
- **Burn goldfish** — kill-turn 4.8–5.2 (community benchmark ~4.5–5)
- **Aggro vs. dragon pile** — fitness function ranks the curved Burn list above an off-curve 6-mana dragon stack
- **Constraint monotonicity** — optimizer never accepts a swap that *adds* violations; respects exclude-lists, color identity, and playset cap (4-of constructed, 1-of singleton)
- **Self-play symmetry** — Burn-vs-Burn matchup ≈ 50% with on-the-play alternation
- **Matchup differentiation** — Burn 71.8% avg vs the meta, Murktide loses to Burn 16% (fast-clock vs. tempo)
- **Format coverage** — Modern, Standard, Pioneer, Legacy, Commander all flag size/color/playset violations correctly
- **Cross-format matchup correctness** — Commander candidate vs Modern opponent applies each side's *native* mulligan profile
- **Synergy cache hit** — same deck → same `SynergyGraph` instance (avoids 9000 graph rebuilds per optimization)
- **Goldfish per-turn ETB-tapped** — taplands played T3 don't produce mana T3
- **Tron assembly** — Urza's Tower + Power Plant + Mine together produce 7 colorless mana
- **Sideboard correctness** — targets losing matchups, deduped, color-aware, empty for Commander
- **Critic loop sanity** — auto-downgrades critic-APPROVE when deterministic rubric flags errors; rolls back rounds that don't improve any metric
- **LLM cost gating** — shared budget across all critic-loop rounds enforces the per-job USD cap

## Pending / not yet wired

### Per-format meta archetypes
- [api/app/sim/meta_archetypes.py](api/app/sim/meta_archetypes.py) contains
  Modern opponents only (Burn, Murktide, Tron, Living End). Standard /
  Pioneer / Legacy / Commander need their own meta sets. The matchup
  pipeline is format-aware; the data isn't.

### Synergy registry expansion
- `KNOWN_COMBOS` lists 12 well-known Modern cliques. Pulling from a
  versioned data file + automation to flag new clique candidates from
  tournament data is a follow-up.

### Tournament deck benchmark coverage
- Kill-turn benchmarks are pinned for Burn only. Living End, Yawgmoth,
  and Tron each need their own benchmark tests (currently their
  goldfish kill turns aren't asserted, just produced).

### Production wiring
- Real Redis/Celery broker provisioning (the backend is ready)
- Auth + rate limiting on the prose endpoint
- pgvector retrieval for semantic similarity
