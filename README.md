# MTG Deck Builder

Full-stack deck-construction app with a **first-principles simulator + optimizer**
that produces tournament-grade decks for all five major formats. FastAPI
backend, Next.js frontend, structured `DeckRationale` output narrated by an
optional LLM coach.

**Current state:** 291 backend tests passing, frontend TypeScript clean
(`next build` green), end-to-end optimizer flow live behind a feature
flag, multi-format meta + deck-evaluation engine + embedding retrieval
wired.

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
| `MTG_API_KEY` | Comma-separated API keys; enables `X-API-Key` auth on optimize/prose/evaluate/save | (unset → auth off) |
| `MTG_USE_PGVECTOR` | Use the pgvector NN path for `/similar` when the `card_embeddings` table exists | `false` |

## Postgres data pipeline

```bash
cd api
createdb mtg_deck_builder
python -m app.scripts.seed_sample_cards
python -m app.scripts.ingest_scryfall              # full Scryfall ingest (optional)
python -m app.scripts.ingest_tournament_decks
python -m app.scripts.build_archetypes
python -m app.scripts.build_card_profiles          # parses oracle text → card_profiles
python -m app.scripts.build_card_embeddings        # dense embeddings → card_embeddings
```

Embeddings power the retriever's `vector` mode (works on SQLite too) and
the pgvector `<=>` path on Postgres. The default embedder is a
deterministic feature-hash projection ([app/services/embeddings.py](api/app/services/embeddings.py))
so it runs offline; swap `embed_features` for a learned model without
changing the table schema, ingest script, or retriever.

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

## Deck evaluation engine

The simulator now ships a **multi-signal evaluation layer**
([api/app/sim/evaluation.py](api/app/sim/evaluation.py)) that grades a
concrete decklist beyond a single kill-turn number:

- **Win rate + Wilson 95% confidence interval** — so callers know when a
  delta is signal vs. noise.
- **Flood / screw resistance** — re-runs the deck with opening hands
  forced land-heavy and land-light.
- **Interaction resilience** — re-runs with a hypothetical opponent
  answering a fraction of spells (gated `disruption_rate` goldfish primitive).
- **Inevitability** — late-game win share + card-advantage density.
- **Consistency** — inverse of kill-turn variance.

Exposed at `POST /v1/decks/evaluate` and folded into the optimizer's
fitness as the `resilience` + `inevitability` axes (computed on
`deep_eval=True`, off in the hot anneal loop).

## Newer endpoints

- `POST /v1/decks/evaluate` — run the evaluation battery on a decklist
- `POST /v1/decks/diff` — card-by-card before/after diff
- `POST /v1/decks/save`, `GET /v1/decks/history`,
  `GET /v1/decks/saved/{id}`, `GET /v1/decks/shared/{token}`,
  `DELETE /v1/decks/saved/{id}` — persistent history + sharing
- `GET /v1/cards/{name}/similar` — semantic-ish neighbours (pgvector
  fast-path, deterministic lexical fallback)

Optional API-key auth (`MTG_API_KEY`, `X-API-Key` header) gates the
optimize / prose / evaluate / save endpoints; the prose endpoint also
carries a tighter dedicated rate limit.

## Resolved to-do items

- **Per-format meta archetypes** — `META_BY_FORMAT` now ships Standard,
  Pioneer, Legacy, and Commander opponent sets plus Modern Yawgmoth &
  Amulet Titan; `build_matchup_matrix` grades each candidate against its
  own format's meta.
- **Synergy registry expansion** — combos live in a versioned
  [combos.json](api/app/synergy/combos.json) (31 cliques across formats)
  with `suggest_clique_candidates()` mining tournament lists for new
  candidates.
- **Tournament benchmark coverage** — per-archetype goldfish benchmarks
  in [test_meta_benchmarks.py](api/tests/test_meta_benchmarks.py).
- **Production wiring** — API-key auth, dedicated prose rate limit, and
  pgvector retrieval (with fallback) are wired.

## Still pending

- Real Redis/Celery broker provisioning (the backend is ready)
- A *learned* embedding model to replace the deterministic feature-hash
  embedder (the full pipeline — table, build script, `vector`/pgvector
  retrieval modes — is wired and tested today)
- Multi-tenant identity (the current `owner` field keys off the API key)
- Deeper frontend wiring of the new evaluation/diff/history components
  into the workshop flow
