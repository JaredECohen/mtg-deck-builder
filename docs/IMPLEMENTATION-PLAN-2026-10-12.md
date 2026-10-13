# Implementation plan: remaining review issues and spec gaps (2026-10-12)

Input: [REVIEW-2026-10-12.md](REVIEW-2026-10-12.md). The "Quick wins" and the CI fixture DB (T-2) are already done on
`fix/review-quick-wins`. This plan covers everything else: the remaining bugs, plus every spec checklist item
marked Partial or Missing.

Branch: `feat/spec-gaps` (stacked on `fix/review-quick-wins`).

## 0. Decisions taken (the review left these open)

| Decision | Choice | Why |
|---|---|---|
| Browser access to the API key | **Server-side proxy in Next.js** (`/api/backend/[...path]`). The key comes from server env `MTG_API_KEY` and never reaches the bundle. `NEXT_PUBLIC_API_KEY` is removed. | Smallest real fix. Real per-user auth needs an identity provider and is still out of scope (multi-tenant is spec phase 4). |
| Gate generate / refine / analyze | **Yes, when `MTG_API_KEY` is set**, plus rate limits on every route. | They spend Anthropic tokens. The browser now goes through the proxy, so gating costs the UI nothing. Auth stays opt-in (unset = open dev mode). |
| Commander corpus source | **No live scraping** (spec §9 says ingest offline; EDHREC/Moxfield ToS unverified). Fix the synthesizer: no basic padding, no duplicate records, and label it honestly as `template` evidence. Real lists come in through the existing `ingest_deck_source` CSV/JSON adapters, documented in the README. | Honest now; real data plugs in without code changes later. |
| `MTG_USE_OPTIMIZER_DEFAULT` path | **Fix it.** Seed with recipes, run the real validator, fall back to legacy when the result is illegal or over budget. | It's a documented switch; it must not return junk marked legal. |
| `mode` field | **Implement it** (fast-competitive / constraint-aware / creative-but-viable). | Spec §6 v1 modes. |
| "Too few lands" hard fail (§12) | **Generator:** hard invariant (never ships under the archetype floor). **Validator:** warning only, with archetype-aware thresholds. | User-submitted lists like Belcher are legal with 1 land; legality is a rules question. |
| Collection-aware building | **Implement a minimal version** (`owned_cards`: prefer owned, cost only counts unowned). | Spec §10 / §22 phase 4, but cheap on top of the budget plumbing. |

## 1. API contract changes (land first; frontend and eval build against them)

### `GenerateDeckRequest` additions
- `mode` is now honored (already present).
- `match_type: "bo1" | "bo3" = "bo3"`. Bo1 means no sideboard and leans toward main-deck interaction.
- `bracket: int | None` (1–5, Commander only). The target power bracket.
- `owned_cards: CardNameList`.
- `archetype_name: str | None`. Build from a specific retrieved shell (powers "Build this alternative").

### `DeckResponse` additions
- `deck_id: str`. Stable hash of the list.
- `constraints: DeckConstraints`. The request constraints (budget, includes, excludes, owned cards, mode, match type, bracket, prompt), persisted so refine can merge them.
- `alternatives: list[DeckAlternative]` (`name`, `source_type`, `colors`, `tags`, `key_cards`, `summary`). The 1–2 runner-up shells (§11F).
- `game_plan: GamePlan` (`summary`, `win_conditions`, `opening_hand`, `mulligan`, `sideboard_guide: list[SideboardGuideEntry]`, `matchups: list[MatchupNote]`). Deterministic §11G explanation.
- `bracket: BracketAssessment | None` (`estimated`, `target`, `game_changers`, `mass_land_denial`, `extra_turns`, `tutors`, `two_card_combos`, `notes`).
- `color_sources: list[ColorSourcePoint]` (`color`, `sources`, `pips`). Feeds the color-source chart.
- `changes: dict | None`. On refine, the diff against the previous version (§15).
- `unpriced_cards: list[str]` and `cost_to_complete_usd: float | None` (owned cards excluded).

### `DeckProvenance` additions
- `source_type` adds **`template`** (built from curated/synthesized templates, not observed tournament results).
- `llm_added_cards: list[str]`, `budget_substitutions: list[BudgetSubstitution]` (`original`, `replacement`, `saved_usd`), `dropped_includes: list[DroppedInclude]` (`name`, `reason`). This is the §24 provenance.

### Other endpoints
- `POST /v1/decks/refine` returns `changes` and an updated explanation.
- `POST /v1/decks/export`: add `archidekt`. Arena output drops the bare title line.
- `GET /v1/cards/{name}/similar?format=&colors=`: filter to legal, on-color cards (alt-card suggestions).
- `GET /v1/meta/summary`: add `as_of`, per-archetype `last_seen` and `evidence` (`observed` / `template`).
- `GET /api/data-status`: add `cards_ingested_at` and `stale` (more than 45 days old).

## 2. Work items

Each item lists files, approach and tests. The ID is the review's ID, or the spec checklist number (§#n).

### Stream A: engine (backend, me)

**A1. Constraint persistence and refine (O-4, B-10, §17)** in `models.py` and `deck_generator.py`.
- Every generated deck carries `constraints`. Refine merges previous constraints with the intent:
  - budget: intent → scaled → previous
  - excludes: union
  - owned, mode, match type, bracket: carried over
- Refine returns `changes` (via `deck_diff`) and appends a "What changed" explanation line.
- Tests: a refine keeps the budget and excludes; the response carries `changes`.

**A2. Includes, excludes and budget everywhere (B-10, B-12, §14).**
- Builtin anchors are kept separate from user includes (anchor seeds stop going into `include_cards`).
- Commander honors `include_cards`.
- The sideboard honors excludes and budget.
- Every dropped include reports a reason (unknown, not legal, off-color, over budget) in `provenance.dropped_includes` and in warnings.
- Unpriced cards are counted as unknown cost and listed. Under a budget, priced cards are preferred.
- Over-budget anchors get a same-role cheaper substitute (similar-card retriever, filtered by legality, color and price), recorded in `budget_substitutions`.
- Tests: Commander include present; excluded card never in sideboard; dropped include reported; substitution recorded.

**A3. Sideboard to 15 from the full legal pool (B-11, §27).**
- Seed from the archetype/builtin sideboard, then fill by tag class (graveyard hate, artifact/enchantment removal, counters, sweepers, lifegain/anti-burn, hand disruption, creature removal). The candidates are on-color, legal and within budget, with copy limits shared with the mainboard.
- Bo1 gets no sideboard.
- Tests: constructed bo3 decks always have a 15-card sideboard across formats; bo1 has 0.

**A4. Deterministic intent parser fallback (B-9, §11A).** New `services/prompt_intent.py`.
- Parses guild/shard/wedge names, color words and "mono-X", budgets ("under $40", "$100 budget", "cheap"), formats, playstyle and theme keywords, and "no X".
- Used whenever the LLM is unavailable or returns nothing. LLM fields win when present.
- Tests: table-driven over phrases, plus a no-key generate that respects mono-green and $40.

**A5. Explanation grounding (B-3, §26).** New `services/grounding.py`.
- Drops any sentence in LLM-written text (strategy summary, blend/compose labels) that names a real card not in the final deck or commander.
- Card names are detected by n-gram lookup against the repository index.
- Tests: hallucinated "Mizzix"/"Grapeshot" sentences are removed; correct sentences stay.

**A6. Game plan / §11G explanation.** New `services/game_plan.py`.
- Win conditions from finisher/threat roles.
- Opening-hand guidance from the hypergeometric land distribution in 7 cards (reuse `sim/mana.py` math) and the archetype speed.
- Mulligan rules by archetype.
- Sideboard guide: every sideboard card maps to its class, its "bring in against" matchups, and a "take out" suggestion (lowest-impact main cards of the matching role).
- Matchup notes against the format's corpus archetypes (tags → strengths and risks).
- Commander gets a ramp/draw/removal/wipes/tutors/wincons package summary.
- Tests: present for every format; the sideboard guide covers every sideboard card.

**A7. Commander brackets (§13, §26).** New `data/game_changers.json` (versioned, with `as_of`) and `services/brackets.py`.
- Assesses game changers, mass land denial, extra turns, tutors, and two-card combos (from the existing `combos.json`). The estimate is 1–5 following the WotC bracket rules.
- Generation with `bracket` filters out game changers (≤2: none, 3: at most 3) and mass land denial / chained extra turns below 4.
- Tests: assessment on fixture lists; a bracket-2 build contains no game changers.

**A8. Mode and Bo1/Bo3 (§13, spec #13).**
- **fast-competitive:** corpus/builtin shells only, strict colors, no creative fill.
- **creative-but-viable:** lower corpus weight; flex slots come from the themed pool with deterministic novelty rotation. Safety floor: the validator and land floor still apply.
- **constraint-aware:** today's behavior.
- Tests: the modes produce different lists, and all are legal.

**A9. Alternatives (§11F).**
- `alternatives` comes from the retrieval candidates [1:3] (constructed) or the next commanders (Commander).
- `archetype_name` forces the base shell.
- Tests: 1–2 alternatives when candidates exist, and `archetype_name` builds that shell.

**A10. Retrieval quality (§11B, B-19).**
- Recency weighting via archetype `last_seen` (computed in `build_archetypes`).
- Evidence type (`observed` vs `template`), with the provenance `template` label.
- Titles built from actual deck colors: no "Control Azorius Control" stutter, and no "Boros" on a mono-R list.
- Tests: title cases; template label.

**A11. Commander corpus honesty (B-1).** `synthesize_tournament_corpus.py`:
- Commander records get a 37-land split across the commander's colors and no basic padding of nonland slots (the record is the seed list; ingest accepts it as a partial list, with the size recorded in metadata).
- One record per archetype (no duplicate "evidence").
- Rebuild the curated JSON, then ingest and rebuild archetypes into `var/` (backup first), then rebuild the test fixture.
- Tests: no archetype land package above 40.

**A12. Optimizer default path (B-13).** `optimizer_default_path.py`:
- Recipes come from the builtin/corpus retrieval.
- The real validator runs.
- Sideboard via A3.
- Falls back to legacy when the result is illegal, more than 10% over budget, or more than 25% of the list is alphabetical-fill.
- Tests with the flag on: legal, on-budget or fell back.

**A13. Name lookup (B-16).** `card_repository._normalize_name`:
- NFKD accent strip, Æ→ae, punctuation-insensitive.
- Index every DFC face name.
- Tests: "Lim-Dul's Vault", "Aether Vial", "Fable of the Mirror-Breaker".

**A14. MDFC and land counting (B-19).** A spell//land MDFC counts as a spell (front face decides) in the validator, generator and analysis, via `rules.is_land_card`. Tests: MDFC counting.

**A15. Analysis advice (B-18).** `deck_analysis.py`:
- Role targets by inferred style (aggro/burn: no ramp target).
- Never suggest cutting cards with ≥3 copies or core cards.
- Adds restricted to deck colors.
- Dominant-tag threshold scales with quantity and deck size.
- Untagged instant/sorcery role comes from oracle-text patterns.
- Tests: the burn list gets no ramp advice and no 4-of cuts.

**A16. Scorecard honesty and land floor (O-12, B-14).**
- Mana score penalizes requested colors with no sources and color pips without sources.
- Land warnings are archetype-aware (aggro 16–20, midrange 22–25, control 24–27, Commander 33–40).
- Generator invariant: never below the floor for its archetype.
- Tests: the Burn benchmark (19–20) produces no low-land warning; mana score drops when a requested color is unsupported.

**A17. Collection-aware (§10 #16).** `owned_cards` ranking boost, `cost_to_complete_usd`, and the budget applies to unowned cards only. Tests.

**A18. Meta summary (§15 #19, §26).** `as_of`, `last_seen`, evidence type and short tag-based matchup notes. Tests.

**A19. Similar-card filtering, Archidekt export, Arena fix (§21 #21, #25).** Tests.

**A20. Data freshness (B-19, §26).** `data_status` gets `cards_ingested_at` / `stale`; generate warns when stale. Run the set_type backfill if it works offline, otherwise document it. Tests.

**A21. Generation cache and observability (§25 #31, #32).**
- LRU+TTL cache of whole generate responses keyed by the normalized request.
- Per-stage timing logs (`gen_stage`), failure-category logging in route handlers, `LOG_LEVEL` honored.
- Tests: a cache hit is identical and fast.

**A22. Security remainder (S-4, S-6, S-7).**
- Gate generate/refine/analyze.
- General rate limiter on all public routes.
- `MTG_TRUST_FORWARDED` for `X-Forwarded-For`.
- Affiliate: exact host matching, single decode, tcgplayer-only destinations, table tests (RP-006).

**A23. Tooling (T-4, RP-005).**
- `api/pyproject.toml` with ruff (E9/F rules that pass) and a CI step.
- Upper-bound pins for `anthropic` / `openai` / `celery`.
- CI on Python 3.13 to match local.
- Complete `.env.example`; drop the unused variables.

### Stream B: frontend (agent, `web/` only)

**B1. API proxy.** `app/api/backend/[...path]/route.ts` forwards to `API_BASE` with the server-side `MTG_API_KEY`. `lib/api.ts` targets the same-origin proxy, and `NEXT_PUBLIC_API_KEY` is removed.

**B2. Expert controls.** Include/exclude card inputs (with autocomplete), mode selector, Bo1/Bo3, Commander bracket selector, owned-cards textarea, archetype "build this".

**B3. Generation progress.** Staged progress UI (parsing → retrieving → evaluating → tuning → writing), driven by elapsed time with `aria-live`.

**B4. Results.**
- Explanation tabs (Why / Game plan / Sideboard guide / Matchups / Bracket).
- `ManaCurveChart` wired in, plus a new color-source chart.
- Per-card "why" (`card_notes` reasons) in the decklist.
- Alternatives panel.
- Commander/sideboard column fix (no "note" placeholders).
- Provenance shows LLM-added cards, budget swaps and dropped includes.
- Beginner "How to play this deck" section.

**B5. Card modal.** Image skeleton, focus return, alt-card suggestions via filtered `/similar`.

**B6. Save / share / history.**
- Save button, share link (`?deck=<token>` hydrates the Analyze workflow).
- Revision history from the undo stack, with Undo, Compare (diff view) and Restore.
- Failed refine no longer pushes history.

**B7. Optimizer rationale.** Seeded with the displayed mainboard, reset on deck change, gated on `deck.format`. Tailwind classes replaced with `globals.css` classes and overflow wrappers. "Apply sim-optimized version" wired.

**B8. Stale-state fixes.**
- Format change marks the current deck as built for another format.
- Analysis gets a stale badge on edits.
- Export: abort or ignore stale responses, and disable the button while loading.
- Meta snapshot reset.
- Commander evaluation sends the commander.
- Analyze `AbortController`.
- Refine prompt draft persistence.
- `clearManualDraft` try/catch.
- Rationale poll job-id guard.
- Lift `useDataStatus` / `useCardDetail` to the shell.

**B9. Export.** Copy and download buttons, Archidekt option.

**B10. Landing.** Example prompt chips per format; the brief template follows the selected format.

**B11. Accessibility.**
- Result `role="status"` summary instead of a whole-section `aria-live`.
- Tablist arrow keys.
- Quantity buttons name their card.
- `<h1>` first on mobile.

**B12. Tooling.** ESLint (`next lint` config) plus a `lint` script and a CI step.

### Stream C: evaluation harness (agent, `qa/` plus one test)

**C1. `qa/benchmark.py`.**
- Deterministic scenario matrix (format × colors × playstyle × budget × mode × bracket × bo1/bo3, 100+).
- Runs in-process with no LLM.
- Metrics: legality rate, color fidelity (requested colors represented, no off-colors), budget adherence, land-count sanity, sideboard completeness, latency p50/p95, scripted-refine success, prompt-intent fidelity (with the A4 fallback).
- Writes `qa/artifacts/benchmark.json` and a Markdown summary.

**C2. `api/tests/test_benchmark_gate.py`.** A 40-scenario CI subset with regression thresholds (legality 100%, color fidelity ≥ 95%, budget adherence ≥ 90%, sideboard completeness 100% for bo3).

**C3.** `qa/README` and an update to `qa/REPORT.md`.

## 3. Sequencing

1. A1 + contract skeleton for every new field (models, export target, similar filters, meta and data-status fields), committed. Then the B and C agents start from that commit in their own worktrees.
2. A2–A22 in dependency order: A13, A14 → A2, A3 → A4, A5 → A6, A7, A8, A9 → A10, A11 → A12 → A15–A21 → A22, A23.
3. Merge B and C, resolve conflicts, run the full suite (fixture and full DB), `next build`, lint, and the benchmark.
4. Live browser QA of every user flow.
5. Rebuild the corpus (A11) and the fixture, update the README, Notion and memory.

## 4. Done when

- Every review item is fixed or explicitly deferred with a reason.
- Every spec checklist item is Done or has a written reason.
- The backend suite and benchmark gate are green on the fixture, and the suite is green on the full DB.
- `next build` and lint are clean.
- Live QA of generate (all 5 formats), Commander with a bracket, refine/chat apply, save → share link → hydrate, export (all targets) and mobile width.

---

## 5. Status (end of 2026-10-12)

All work is on `feat/spec-gaps`, which is stacked on `fix/review-quick-wins`; neither is merged or pushed.

Results:
- 456 backend tests pass on the fixture DB, and ruff is clean.
- `tsc`, `next lint` and `next build` are clean.
- `qa/benchmark.py` passes 100% of its 108 scenarios on all 10 metrics, on both the fixture and the full local DB ([qa/BENCHMARK.md](../qa/BENCHMARK.md), [qa/BENCHMARK-full-db.md](../qa/BENCHMARK-full-db.md)). The CI gate's floors are now 100%.
- Live browser QA passed for:
  - generate, with the progress stages, game plan, charts, "Why?" and alternatives;
  - Commander at bracket 2;
  - refine and revision history;
  - save, then share link, then the `?deck=` link opening in Analyze;
  - mobile at 375 px, with no console errors.

| Item | Status |
|---|---|
| A1 constraint persistence and refine diff | Done |
| A2 includes, excludes, budget, unpriced cards, substitutions, total-budget pass | Done |
| A3 15-card sideboards and Bo1 | Done |
| A4 deterministic brief and refine parsing | Done, including commander names and "add 4x X / cut Y / swap A for B" |
| A5 explanation grounding | Done |
| A6 game plan | Done |
| A7 Commander brackets | Done. The Game Changers list is versioned as of 2025-04-22; **verify it against WotC's current list** |
| A8 modes | Done. Fast-competitive and constraint-aware can pick the same shell when the best theme match is also the most played |
| A9 alternatives / `archetype_name` | Done |
| A10 retrieval and titles | Done: titles name the colors played, and curated seeds are preferred over borrowed shells. Recency weighting has `last_seen` stored, but the synthetic corpus has one date, so it has no effect yet |
| A11 corpus honesty | Done. `var/` was rebuilt; the backup is at `var/mtg_deck_builder.backup-2026-10-12.db` |
| A12 optimizer default path | Done. It is safe but seldom finds an improvement, and is slow (7–28 s); it stays opt-in |
| A13 name lookup | Done |
| A14 MDFC counting | Done |
| A15 analysis advice | Done |
| A16 land ranges | Done (curve-aware) |
| A17 collection-aware | Done |
| A18 meta `as_of` / matchups | Done. Matchup notes are in `game_plan` |
| A19 similar filters, Archidekt, Arena | Done |
| A20 data freshness | Done. The local data is 87 days old, so decks carry a "stale" note until `ingest_scryfall` is rerun |
| A21 cache, stage logs, warm-up | Done |
| A22 gating, limits, proxies, affiliate | Done |
| A23 tooling | Done |
| B1–B12 frontend | Done (agent stream, merged) |
| C1–C3 evaluation harness and gate | Done (agent stream, merged) |

Deferred, each with a reason:
- **Real observed tournament and Commander lists.** These need licensed data; the import path exists.
- **A learned embedding model.** Budget stand-ins are only as good as the feature-hash similarity.
- **Multi-tenant auth.** Spec phase 4.
- **Alembic migrations.** The one known schema drift is handled at startup.
- **Price coverage.** About 22% of cards have no price. This is a data issue: they are surfaced, not guessed.
- **`set_type` backfill.** The script needs network access to Scryfall.
- **Human-review rubric (§21).** This is not automatable.
- **Mono-color requests whose playstyle has no matching seed.** Mono-blue control, for example, still borrows a broader shell's name; the cards stay on-color.
- **Analysis provenance banner.** It shows "fallback" next to a retrieved shell; this is cosmetic.
