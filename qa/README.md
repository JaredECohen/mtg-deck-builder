# QA harnesses

Two harnesses live here. They answer different questions.

| Harness | Question | LLM | Output |
|---|---|---|---|
| `benchmark.py` | Does the engine honor the request? Objective pass/fail metrics over a 108-scenario matrix. | None. Deterministic. | `artifacts/benchmark.json`, `BENCHMARK.md` |
| `run_eval.py` | Do the decks look like good decks? Heuristic + LLM-judged scoring of 10 hand-written scenarios. | OpenAI judge (optional) | `artifacts/deck_eval_*.json`, `REPORT.md` |

The CI gate `api/tests/test_benchmark_gate.py` runs a 40-scenario subset of `benchmark.py` with every test run.

## `benchmark.py`: deterministic benchmark

```bash
# From the repo root (uses api/.venv; the script puts api/ on sys.path itself)
api/.venv/bin/python qa/benchmark.py                    # 108 scenarios on the fixture DB, ~15 s
api/.venv/bin/python qa/benchmark.py --gate             # just the CI-gate subset (40)
api/.venv/bin/python qa/benchmark.py --limit 10         # quick smoke run

# Against another database, e.g. the full local ingest (~35 s)
cp var/mtg_deck_builder.db /tmp/full.db
api/.venv/bin/python qa/benchmark.py --database-url sqlite:////tmp/full.db \
    --json qa/artifacts/benchmark-full-db.json --summary qa/BENCHMARK-full-db.md
```

What it does:

- Runs in-process through FastAPI's `TestClient(app)`, so no server is needed.
- Before the app is imported it blanks `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MTG_API_KEY` and `MTG_USE_OPTIMIZER_DEFAULT`. That makes the run LLM-free and auth-free, and it uses the default legacy generator.
- Disables the per-IP rate limiters and the background Scryfall refresh.
- Database:
  - The default is the checked-in fixture `api/tests/fixtures/cards.db.gz`, decompressed to a temp dir. This is the same data the test suite uses.
  - `--database-url` points it at another database.
  - A SQLite file under `var/` is copied to a temp dir first, so the benchmark never writes to `var/`.
- Outputs:
  - `qa/artifacts/benchmark.json` (gitignored): every scenario's request, the deck summary, each check and its failure detail, the recomputed price, and the refine picks.
  - `qa/BENCHMARK.md` (committed): run date, git commit, the DB used (card count, data date), pass rate per metric overall and by format, endpoint latency, and failing scenario IDs with what was wrong (12 per metric).
  - `qa/BENCHMARK-full-db.md` is the same summary for the full local DB.

### Scenario matrix

The scenarios are generated in code by `generate_scenarios()`; nothing is hand-listed except the prompts. They are deterministic and don't read the DB, so IDs are stable between runs.

- **Constructed (60).** Each of standard, pioneer, modern and legacy gets 15 color specs:
  - the 5 mono colors
  - 5 guilds and 3 shards, rotated per format so all 10 of each get covered
  - colorless (`["C"]`)
  - unspecified (`[]`)

  Playstyle, budget tier, `mode` and `match_type` (bo1/bo3) rotate with different strides, so each axis is spread across formats and colors.
- **Commander (24).**
  - 14 color specs: mono, 4 guilds, 3 shards, unspecified, colorless.
  - 10 explicit `commander_name` requests. These are commanders present in both the fixture and the full DB.
  - `bracket` cycles through none and 1–5. Budget, mode and playstyle rotate.
- **Prompts (24).** These send only `format` + `prompt`, for example "cheap mono-green stompy under $40". They measure how well the no-LLM path reads intent. The expected colors, price ceiling and commander are in the `PROMPTS` table.
- **Budget tiers.** Each format has its own tiers (`BUDGET_TIERS`): none, low or mid. A $50 Standard budget is realistic, but a $50 Legacy budget isn't.
- **Refine.** Every third constructed and Commander scenario also runs the scripted refine.
- **Gate subset.** The CI gate takes every third constructed scenario, every other Commander scenario and every third prompt. That's 40 scenarios.

### Metrics

A metric that doesn't apply to a scenario is `n/a`. For example, sideboard doesn't apply to Commander, and bracket only applies when a bracket was requested. N/a scenarios are left out of that metric's denominator. When generation fails (non-200), only `http_success` is scored for that scenario.

| Metric | Pass condition |
|---|---|
| `http_success` | `/v1/decks/generate` returns 200. |
| `legality` | The returned list is re-validated through `/v1/decks/validate` (main, side, commander) and comes back legal. The response's own `is_legal` is not trusted, and a mismatch is noted in the detail. |
| `deck_size` | Constructed mainboard is exactly 60. Commander is 99 + a commander. |
| `land_count` | Constructed has 14–28 lands, Commander 30–42. Lands are counted with `app.rules.is_land_card`, so spell//land MDFCs count as spells. |
| `color_fidelity` | Applies to explicit color or commander requests. Every card's color identity (main, side, commander) is within the requested colors, or within the commander's identity when no colors were given. Each requested color also appears on at least one nonland card (the commander counts). `["C"]` means nothing colored is allowed. An explicit `commander_name` must be the commander returned. Unspecified constructed colors are n/a. |
| `budget_adherence` | Applies when `budget` is set. The price is recomputed from the DB (main + side + commander, `price_usd` × qty) and must be ≤ budget. Unpriced cards count as $0 and are listed. |
| `sideboard_completeness` | Constructed bo3 has exactly 15 sideboard cards; bo1 has 0. |
| `bracket_compliance` | Applies when `bracket` is set. The response must carry `bracket` with `estimated` ≤ target. When target ≤ 2, `bracket.game_changers` must be empty. A missing assessment fails. |
| `refine_success` | `/v1/decks/refine` runs with `app.services.deck_generator.interpret_refinement` monkeypatched to return a scripted `RefinementIntent`. The intent excludes one nonland card from the deck and includes one legal, on-color nonland card that isn't already in the deck and costs ≤ $1. Both cards are picked deterministically from a hash of the scenario ID. To pass, the excluded card must be gone from main *and* side, the included card must be in main, the land count must be unchanged, and the refined list must re-validate as legal. |
| `prompt_fidelity` | Applies to prompt scenarios. Card identities must be within the prompt's colors, each prompt color must be on a nonland card, the price must be ≤ the stated ceiling, and the commander must match when the prompt names one. Prompt scenarios are scored here, not under color/budget fidelity. |
| latency | p50/p95/max wall time per endpoint (generate, validate, refine) through TestClient. This is in-process, so there's no network. |

### Adding scenarios

- **New axis value** (a playstyle, budget tier or commander): add it to the matching constant at the top of `benchmark.py`, such as `PLAYSTYLES`, `BUDGET_TIERS` or `EXPLICIT_COMMANDERS`. The rotations pick it up. A new commander must exist in the fixture DB, or the gate will 400. Check with `repository.get_card(name)` and rebuild the fixture if needed (`python -m app.scripts.build_test_fixture`).
- **New prompt:** append a dict to `PROMPTS` with `format`, `prompt`, `allowed` (a color string; `""` means colorless) and optionally `required`, `max_price` and `commander`.
- **New metric:** add a `Check` in `run_scenario`, then add the metric to `METRICS` and `METRIC_HELP`. If it should gate CI, add a floor and/or target in `api/tests/test_benchmark_gate.py`.
- Scenario IDs come from the parameters, so changing a rotation renames scenarios. That's fine, but note it when comparing runs.

### CI gate thresholds

`api/tests/test_benchmark_gate.py` has two kinds of test:

- **Floors** are the pass rates measured when the gate was written. Falling below one fails CI.
- **Targets** come from the implementation plan: legality 100%, color fidelity ≥ 95%, budget ≥ 90%, bo3 sideboard 100%, bracket 100%, plus refine 100% and prompt fidelity ≥ 90%. A target is `xfail(strict=False)` while the engine work is pending. When one shows XPASS, remove its xfail and raise the matching floor.

## `run_eval.py`: LLM-judged scenario review (April 2026)

```bash
DATABASE_URL=sqlite:////tmp/full.db api/.venv/bin/python qa/run_eval.py
```

- Runs the 10 hand-written scenarios in `deck_scenarios.json`.
- Uses a live API on `MTG_API_BASE`, `:8010` or `:8000` when one is healthy. Otherwise it runs in-process.
- Set `DATABASE_URL` for the in-process path. Without it the app opens the default `var/` database.
- When `OPENAI_API_KEY` is set, `OPENAI_EVAL_MODEL` judges each deck. Without a key the LLM part is skipped and only the heuristic scores are reported.
- Rewrites `qa/REPORT.md` in full on every run.
