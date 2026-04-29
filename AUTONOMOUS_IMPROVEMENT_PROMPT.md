# Autonomous MTG Deck Builder: Full Review & Improvement Session

## Operating Instructions

You are running autonomously for several hours. Follow these rules strictly:

- **Do NOT ask for input at any point.** If you are uncertain between two approaches, pick the more conservative one and document your choice in the commit message.
- **Commit after completing each numbered section** using `git commit` with a descriptive message and the trailer `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`.
- **Run the full test suite after every section.** If tests break, fix them before moving on. Never delete a failing test to make the suite pass. Never use `--no-verify`.
- **Test runner:** `python -m pytest api/tests/ -q` from the repo root (`/Users/jaredcohen/code/mtg-deck-builder`).
- **TypeScript check:** `cd web && npm run build` — must compile cleanly after any frontend changes.
- Work in order: bugs first, then tests, then improvements, then frontend, then final verification.

---

## Repo Context

**Stack:** FastAPI 0.115 + SQLAlchemy 2 + Pydantic v2 backend; Next.js 14 + TypeScript 5.6 frontend.

**No virtualenv** — Python deps installed globally. `anthropic` 0.94.0 is present. Tests use `fastapi.testclient.TestClient` with sample JSON data (no live DB required).

**Key files:**

| File | Purpose |
|------|---------|
| `api/app/services/deck_generator.py` | Core deck build logic (~945 lines) |
| `api/app/services/deck_analysis.py` | Deck analysis, health labels, swap recommendations |
| `api/app/services/deck_validator.py` | Legality checking, score calculation |
| `api/app/services/card_repository.py` | All data access, card/archetype lookups |
| `api/app/services/llm_service.py` | Claude API integration with fallbacks |
| `api/app/models.py` | All Pydantic request/response models |
| `api/app/constants.py` | ROLE_TAGS, ROLE_MAP, deck size constants |
| `api/app/main.py` | FastAPI routes, middleware, rate limiting |
| `api/tests/test_coverage.py` | Parametrized test suite — add new tests here |
| `api/tests/test_api.py` | Basic endpoint tests |
| `web/src/components/deck-workshop.tsx` | Entire frontend UI (~2000 lines) |
| `web/src/lib/types.ts` | TypeScript types mirroring API models |

**Before starting:** Read the files listed above. Do not rely on the descriptions here — read the actual current code so your changes are based on ground truth.

---

## SECTION 1: Bug Fixes

Read each file first. Implement all of the following fixes.

### BUG 1 — `include_cards` bypass budget check (`deck_generator.py`)

**Locate:** `_build_constructed_mainboard()` — the block that iterates `request.include_cards` and adds them to `counts` (around line 280).

**Problem:** These cards are added after checking color identity and legality, but `_fits_budget_request()` is never called. A user who sets `budget=$10` and forces `include_cards=["Oko, Thief of Crowns"]` gets a $50 card added while $1 cards are excluded by budget elsewhere.

**Fix:**
1. After the existing color/legality checks for each include card, also call `self._fits_budget_request(card, request.budget)`.
2. If the card fails the budget check, **still add it** (it's explicitly forced) but collect its name into a local `over_budget_includes: list[str]` list.
3. After deck construction completes, if `over_budget_includes` is non-empty, append this warning to the deck's warnings list before returning: `f"Forced card(s) exceed requested budget: {', '.join(over_budget_includes)}."`

### BUG 2 — Commander seed cards overwrite existing copies (`deck_generator.py`)

**Locate:** `_build_commander_mainboard()` — the block that seeds cards from a prior deck into `counts` (around line 425-434). Look for the line that does `counts[card.name] = 1`.

**Problem:** `counts[card.name] = 1` unconditionally assigns, even if the card was already added from archetype packages with count=1. This is harmless today but fragile — a future reordering could double-add cards, violating commander singleton rules.

**Fix:** Change `counts[card.name] = 1` to `if counts[card.name] == 0: counts[card.name] = 1`. Only add if not already present.

### BUG 3 — Unicode card name mismatch in analysis (`deck_analysis.py`)

**Locate:** `_rank_cut_candidates()` — the block that checks `card.name.lower() in off_plan` (around line 470). Also find where the `off_plan` set is constructed from `shell_comparison.off_plan_cards`.

**Problem:** MTG has cards with unicode characters ("Æther Vial", "Lim-Dûl's Vault"). `"æther vial".lower()` ≠ `"aether vial"` in Python string comparison, so some cards never match their off-plan entry.

**Fix:**
1. Add `import unicodedata` at the top of `deck_analysis.py`.
2. Add module-level helper: `def _norm(s: str) -> str: return unicodedata.normalize("NFKD", s).casefold()`
3. When building the `off_plan` set: wrap each name with `_norm()`.
4. In the comparison: use `_norm(card.name) in off_plan` instead of `card.name.lower() in off_plan`.
5. Apply the same `_norm()` wherever else card names are compared as strings in this file (search for `.lower()` usages on card names).

### BUG 4 — Duplicate swap categories in analysis (`deck_analysis.py`)

**Locate:** `_build_swap_recommendations()` — after the loop that builds swap entries, find the return statement (around line 449).

**Problem:** If `role_needs` somehow contains duplicate role keys (defensive case), the returned list can have two entries with the same `category` field, confusing the UI.

**Fix:** Before returning, deduplicate by category:
```python
seen: set[str] = set()
deduped = [s for s in swaps if s.category not in seen and not seen.add(s.category)]
return deduped
```

### BUG 5 — Health label "promising" for zero-similarity custom shells (`deck_analysis.py`)

**Locate:** `_infer_health_label()` — the `if score >= 72:` branch (around line 313).

**Problem:** A deck with score=72 but archetype similarity=0.0 (completely custom shell with no archetype match) gets labeled "promising but unfinished." That label implies it's close to a known strategy, which is false.

**Fix:**
1. Change the condition to `if score >= 72 and similarity >= 0.25:` — custom shells with score≥72 but no archetype match fall through to "coherent but underpowered" instead.
2. Refactor `_infer_health_label()` to return `tuple[str, str]` — `(label, explanation)`:
   - `"well-structured"` → explanation: `"Your deck has strong synergy and aligns closely with a known archetype strategy."`
   - `"promising but unfinished"` → explanation: `"Good foundation, but the deck could use more consistency or a tighter focus around its core plan."`
   - `"coherent but underpowered"` → explanation: `"The strategy is readable but individual card quality or synergy depth may limit results."`
   - `"structurally flawed"` → explanation: `"The deck has legality errors or significant construction problems that should be addressed first."`
3. Update every call site of `_infer_health_label()` to unpack the tuple.
4. Add `deck_health_explanation: str = ""` to `DeckAnalysisResponse` in `api/app/models.py`.
5. Populate `deck_health_explanation` in `analyze()` from the returned tuple.
6. Add `deck_health_explanation: string` to `DeckAnalysisResponse` in `web/src/lib/types.ts`.
7. In `web/src/components/deck-workshop.tsx`, find where `deck_health` label is displayed and add a `<p>` or `<div>` below it showing `analysis.deck_health_explanation` (only when non-empty).

### BUG 6 — Frontend keyboard nav index out of bounds (`deck-workshop.tsx`)

**Locate:** The `keydown` handler for the manual card search input — find the ArrowDown and ArrowUp branches that call `setManualSearchIndex`.

**Problem:** The index is incremented/decremented without bounds checking. After typing a new search query (which shrinks the results list), the stale index points past the end of the new list.

**Fix:**
1. ArrowDown: `setManualSearchIndex(i => Math.min(i + 1, manualSearchResults.length - 1))`
2. ArrowUp: `setManualSearchIndex(i => Math.max(i - 1, 0))`
3. Add a `useEffect` that resets the index to 0 whenever `manualSearchResults` changes:
   ```tsx
   useEffect(() => { setManualSearchIndex(0); }, [manualSearchResults]);
   ```

### BUG 7 — Export content stale after deck refinement (`deck-workshop.tsx`)

**Locate:** The success handler for the refine API call — the block that calls `setDeck(data)` and updates state after a successful `/v1/decks/refine` response.

**Problem:** `exportContent` is not cleared when a refined deck arrives. The user exports, then refines, and the export panel still shows the old pre-refinement deck.

**Fix:** Add `setExportContent("")` in the refine success block alongside the existing state updates.

---

**After completing Section 1:** Run `python -m pytest api/tests/ -q` and `cd web && npm run build`. Fix any failures before committing. Commit with message: `fix: 7 bugs — budget bypass, commander copy, unicode norm, dupe swaps, health label, keyboard nav, stale export`.

---

## SECTION 2: New Tests

Add all of the following tests to `api/tests/test_coverage.py`. Read the existing tests first to match their style (they use `fastapi.testclient.TestClient` with a module-level `client` fixture and `pytest.mark.parametrize`).

Read the sample card data at `api/app/data/cards.sample.json` to find real card names you can use in tests. All tests must use cards that exist in the sample data. Check legalities in the sample JSON to pick format-appropriate cards.

### TEST 1 — Reject mainboard with 59 cards

```python
def test_validate_constructed_deck_size_under() -> None:
    # Build a 59-card valid modern mainboard (use 59 copies of a basic land for simplicity).
    # POST to /v1/decks/validate with format=modern.
    # Assert response.status_code == 200.
    # Assert payload["is_legal"] is False.
    # Assert any error message contains "60".
```

### TEST 2 — Reject mainboard with 61 cards

```python
def test_validate_constructed_deck_size_over() -> None:
    # Same as above but 61 cards.
    # Assert is_legal is False and error mentions "60".
```

### TEST 3 — Color source warning fires when color demand is unmet

```python
def test_validate_insufficient_blue_sources() -> None:
    # Build a mainboard where 10+ cards require blue mana (pick real blue spells
    # from the sample data that appear legal in modern) but include zero Islands
    # or blue-producing lands. Fill remaining slots with basic Mountains.
    # POST to /v1/decks/validate with format=modern.
    # Assert response.status_code == 200.
    # Assert any warning mentions "U" or "blue" (the mana source warning).
```

### TEST 4 — Illegal card detected in sideboard even if mainboard is clean

```python
def test_validate_illegal_card_in_sideboard() -> None:
    # Build a legal 60-card standard mainboard (use basic lands + legal standard spells).
    # Add a card to the sideboard that is NOT legal in standard (pick one from sample
    # data whose legalities["standard"] == "not_legal").
    # POST to /v1/decks/validate with format=standard.
    # Assert is_legal is False.
    # Assert at least one error mentions the sideboard card's name.
```

### TEST 5 — Parser handles multiple double-faced cards

```python
def test_parse_multiple_dfc_cards() -> None:
    # Only run if "Fire // Ice" and at least one other DFC exist in sample data.
    # Otherwise use the single known DFC from existing tests and add a second line
    # with a different card.
    deck_text = "4 Fire // Ice\n2 Wear // Tear\n"  # adjust to real DFC names if needed
    response = client.post("/v1/decks/parse", json={"deck_text": deck_text, "format": "legacy"})
    assert response.status_code == 200
    payload = response.json()
    names = [c["name"] for c in payload["mainboard"]]
    assert len(names) == 2  # two distinct cards
    quantities = {c["name"]: c["quantity"] for c in payload["mainboard"]}
    # assert correct quantities for whatever cards you used
```

### TEST 6 — Refine with "cheapest possible" prompt does not crash

```python
def test_refine_zero_budget_floor_no_crash() -> None:
    # First generate a deck.
    gen = client.post("/v1/decks/generate", json={"format": "modern", "colors": ["R"], "playstyle_tags": ["aggro"], "theme_tags": []})
    assert gen.status_code == 200
    deck = gen.json()
    # Now refine with a strong budget-cutting prompt.
    refine = client.post("/v1/decks/refine", json={"deck": deck, "prompt": "make this as cheap as possible, free if you can"})
    assert refine.status_code == 200
    refined = refine.json()
    assert refined["format"] == "modern"
    total = sum(c["quantity"] for c in refined["mainboard"])
    assert total == 60
```

### TEST 7 — Analysis deck_health is always one of four valid values

```python
def test_analyze_deck_health_label_is_valid() -> None:
    VALID_LABELS = {"well-structured", "promising but unfinished", "coherent but underpowered", "structurally flawed"}
    gen = client.post("/v1/decks/generate", json={"format": "modern", "colors": ["U", "B"], "playstyle_tags": ["control"], "theme_tags": []})
    assert gen.status_code == 200
    deck = gen.json()
    analysis = client.post("/v1/decks/analyze", json={
        "format": deck["format"],
        "commander": deck.get("commander"),
        "mainboard": deck["mainboard"],
        "sideboard": deck["sideboard"],
    })
    assert analysis.status_code == 200
    payload = analysis.json()
    assert payload["deck_health"] in VALID_LABELS
    # Also assert explanation is present (non-empty string) after BUG 5 fix
    assert isinstance(payload.get("deck_health_explanation", ""), str)
```

### TEST 8 — Generate with nonexistent include card does not 500

```python
def test_generate_with_nonexistent_include_card() -> None:
    response = client.post("/v1/decks/generate", json={
        "format": "modern",
        "colors": ["R"],
        "playstyle_tags": ["aggro"],
        "theme_tags": [],
        "include_cards": ["Absolutely Fake Card Name That Does Not Exist 9999"],
    })
    assert response.status_code == 200
    payload = response.json()
    total = sum(c["quantity"] for c in payload["mainboard"])
    assert total == 60
    # The fake card should NOT appear in the deck
    names = [c["name"] for c in payload["mainboard"]]
    assert "Absolutely Fake Card Name That Does Not Exist 9999" not in names
    # A warning about the unresolved card should appear (after IMPROVEMENT 5 is applied)
    # This assertion can be commented out if IMPROVEMENT 5 isn't implemented yet:
    # assert any("Absolutely Fake" in w for w in payload.get("warnings", []))
```

---

**After completing Section 2:** Run `python -m pytest api/tests/ -q`. All original 71 tests plus your new ~8 tests must pass. Fix any failures. Commit with message: `test: add 8 tests — deck size, color sources, sideboard legality, DFC parser, budget floor, health label, include_cards`.

---

## SECTION 3: Analysis & Generation Improvements

### IMPROVEMENT 1 — Unify similarity thresholds (`deck_analysis.py`)

Add two module-level constants near the top of `deck_analysis.py` (after imports):
```python
SIMILARITY_HIGH = 0.60
SIMILARITY_MEDIUM = 0.35
```

Replace every hardcoded similarity threshold in the file (search for `0.65`, `0.45`, `0.35`, `0.40`) with these constants. Update comments to explain the thresholds.

The health label fix in BUG 5 should already use `SIMILARITY_MEDIUM` (0.35) for "promising" — verify it does.

### IMPROVEMENT 2 — Better primary role inference for untagged card types (`deck_analysis.py`)

**Locate:** `_primary_role()` method — find the fallback `return "flex"` at the end.

**Problem:** Cards with no tags but a clear type (Instant, Sorcery, Planeswalker, Artifact, Enchantment) are labeled "flex" instead of a meaningful role. Counterspell with no tags → "flex" is wrong.

**Fix:** Before the final `return "flex"`, insert type-line-based fallback inference:
```python
type_line = card.type_line or ""
if "Instant" in type_line or "Sorcery" in type_line:
    return "interaction"
if "Planeswalker" in type_line:
    return "threat"
if "Artifact" in type_line or "Enchantment" in type_line:
    return "engine"
return "flex"
```

### IMPROVEMENT 3 — Scale dominant-tag threshold with deck size (`deck_analysis.py`)

**Locate:** The `dominant_tags` calculation that uses `count >= 2` as its threshold.

**Problem:** In a 60-card deck, threshold=2 means any tag appearing on two cards "dominates." A single-copy counterspell and a cantrip both have "draw" → suddenly the deck is "a draw-matters strategy."

**Fix:** Change `count >= 2` to `count >= max(2, len(mainboard_refs) // 15)`. For a 60-card deck this raises the threshold to 4. For a 99-card commander deck it raises it to 6.

### IMPROVEMENT 4 — Warn when include_cards can't be resolved (`deck_generator.py`)

**Locate:** `generate()` — the section where `include_cards` are passed into the mainboard builder.

**Problem:** If a user requests `include_cards=["Lighting Blt"]` (typo), the card silently doesn't appear. No feedback is given.

**Fix:**
1. Before calling the mainboard builder, iterate `request.include_cards` and call `self.repository.get_card(name)` for each.
2. Collect names that return `None` into `unresolved: list[str]`.
3. After deck construction, if `unresolved` is non-empty, append to `warnings`: `f"Could not find card(s) to include: {', '.join(unresolved)}. Check spelling."`

---

**After completing Section 3:** Run `python -m pytest api/tests/ -q`. All tests must pass. Commit: `improve: better role inference, unified similarity thresholds, dominant-tag scaling, unresolved include warnings`.

---

## SECTION 4: Frontend Improvements

Read `web/src/components/deck-workshop.tsx` and `web/src/lib/types.ts` in full before making any changes.

### FRONTEND 1 — Card image loading skeleton (`deck-workshop.tsx`)

**Locate:** The card detail modal — find the `<img>` tag that displays `selectedCard.image_uri`.

**Problem:** While `cardLoading` is true, the image area is empty (no placeholder). On slow connections this looks broken.

**Fix:** Wrap the `<img>` in a conditional:
- When `cardLoading` is true OR `selectedCard?.image_uri` is falsy: render a placeholder `<div>` with the same approximate dimensions as a card (width: 265px, height: 370px) styled as `background: "#e5e7eb", borderRadius: "8px"`.
- When loaded: render the actual `<img>`.

Use the existing `cardLoading` state variable (it should already exist — grep for it).

### FRONTEND 2 — Card modal dialog accessibility (`deck-workshop.tsx`)

**Locate:** The card detail modal container element that has `role="dialog"` and `aria-modal="true"`.

**Fix:**
1. Add `aria-labelledby="card-detail-name"` to the dialog container.
2. Find the card name heading inside the modal and add `id="card-detail-name"`.
3. Find the oracle text element (the spell text / ability description) and add `id="card-detail-oracle"`.
4. Add `aria-describedby="card-detail-oracle"` to the dialog container.

### FRONTEND 3 — Commander badge: user pick vs auto-recommended (`deck-workshop.tsx`)

**Locate:** The area where the deck result is displayed — find where `deck.commander` is shown (likely near the deck title or a commander info section).

**Problem:** Users don't know if the displayed commander was one they explicitly chose or one Claude auto-selected.

**Fix:** Next to or below the commander name, add a small badge/chip:
- If `selectedCommanderName` state matches `deck.commander`: show `"Your pick"` badge (subtle, maybe outlined style).
- If they differ (auto-recommended): show `"Recommended"` badge.

Use whatever badge/chip styling pattern already exists in the component (grep for `className="chip"` or `className="badge"` to find existing patterns).

### FRONTEND 4 — Draft persistence: save regardless of builder mode (`deck-workshop.tsx`)

**Locate:** The `useEffect` that saves draft state to `localStorage` — find the effect that writes `manualMainboard`, `manualSideboard`, `manualCommander`, etc.

**Problem:** The save effect likely has a condition that skips saving when `builderMode === "analyze"`. This causes the user's manually-typed deck to be lost if they switch modes.

**Fix:** Remove the `builderMode !== "analyze"` (or similar) condition from the save effect. The effect should save draft state any time any of the draft fields change, regardless of the current mode.

### FRONTEND 5 — Show deck health explanation below label (`deck-workshop.tsx`)

**Locate:** Where `analysis.deck_health` is displayed (likely the health label badge in the analysis results panel).

**Fix:** Immediately below the health label badge, add:
```tsx
{analysis.deck_health_explanation && (
  <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "#6b7280" }}>
    {analysis.deck_health_explanation}
  </p>
)}
```

This surfaces the explanation string added in BUG 5. Ensure `types.ts` already has `deck_health_explanation: string` (from BUG 5 fix) — add it if missing.

### FRONTEND 6 — Meta summary: show archetype playstyle tags (`deck-workshop.tsx`)

**Locate:** The meta summary panel — find where archetypes are listed (each archetype shown with name and colors).

**Fix:**
1. Check `web/src/lib/types.ts` for `MetaArchetypeSummary`. If it doesn't have a `tags` field, add `tags?: string[]`.
2. Check `api/app/main.py` `meta_summary()` endpoint and `MetaSummaryResponse` model — if archetypes don't include tags, add them from the `ArchetypeRecord.tags` field.
3. In the frontend list, after the archetype name and colors, render the first 2 tags as small chips:
   ```tsx
   {archetype.tags?.slice(0, 2).map(tag => (
     <span key={tag} className="chip" style={{ fontSize: "0.75rem", marginLeft: "4px" }}>{tag}</span>
   ))}
   ```

---

**After completing Section 4:** Run `cd web && npm run build`. Fix all TypeScript errors. Then run `python -m pytest api/tests/ -q` to confirm backend is still clean. Commit: `improve: UI — card modal a11y, keyboard nav fix, health explanation, commander badge, draft persistence, meta tags`.

---

## SECTION 5: Final Verification

Run every verification step in order. Do not skip any.

### Step 1 — Full backend test suite
```bash
python -m pytest api/tests/ -q --tb=short
```
Expected: all tests pass. If any fail, fix before proceeding.

### Step 2 — New tests specifically
```bash
python -m pytest api/tests/test_coverage.py -v -k "deck_size or color_source or sideboard or dfc or zero_budget or health_label or include_card"
```
All new tests must be green.

### Step 3 — TypeScript build
```bash
cd web && npm run build
```
Must complete with zero errors.

### Step 4 — Smoke test via curl (run from repo root)

**Generate a Modern aggro deck:**
```bash
curl -s -X POST http://localhost:8000/v1/decks/generate \
  -H "Content-Type: application/json" \
  -d '{"format":"modern","colors":["R"],"playstyle_tags":["aggro"],"theme_tags":[]}' \
  | python -m json.tool | grep -E '"is_legal"|"total"|"score"'
```

**Generate a Commander ramp deck (verify is_legal=true):**
```bash
curl -s -X POST http://localhost:8000/v1/decks/generate \
  -H "Content-Type: application/json" \
  -d '{"format":"commander","colors":["G","U"],"playstyle_tags":["ramp"],"theme_tags":[]}' \
  | python -m json.tool | grep -E '"is_legal"|"commander"|"validation_errors"'
```

**Analyze a generated deck (verify deck_health_explanation present):**
Generate a deck first, capture the response, then POST its `mainboard`/`format` to `/v1/decks/analyze` and check that `deck_health_explanation` is a non-empty string in the response.

**Try the unresolved include_card warning:**
```bash
curl -s -X POST http://localhost:8000/v1/decks/generate \
  -H "Content-Type: application/json" \
  -d '{"format":"modern","colors":["R"],"playstyle_tags":["aggro"],"theme_tags":[],"include_cards":["Fake Card ZZZZ"]}' \
  | python -m json.tool | grep -A5 '"warnings"'
```
Should see a warning mentioning "Fake Card ZZZZ".

If the dev server isn't running, skip Step 4 and note it in the final commit message.

### Step 5 — Final commit
```bash
git add -A
git commit -m "$(cat <<'EOF'
chore: final verification pass — all tests green, TS build clean

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Summary of All Changes

| Section | Changes |
|---------|---------|
| Bug fixes | 7 bugs: budget bypass, commander copy guard, unicode norm, dupe swaps, health label threshold, keyboard nav bounds, stale export |
| New tests | 8 tests: deck size 59/61, color sources, sideboard legality, DFC batch, budget floor, health label enum, unresolved includes |
| Analysis improvements | Unified thresholds, better role inference, dominant-tag scaling, unresolved-include warnings |
| Frontend improvements | Card modal a11y, keyboard nav, health explanation display, commander badge, draft persistence, meta tags |

**Target test count:** 71 existing + 8 new = 79+ tests passing.
**TypeScript:** Zero errors from `npm run build`.
