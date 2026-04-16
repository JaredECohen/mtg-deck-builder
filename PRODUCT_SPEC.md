# MTG Deck Builder Product Spec

## 1. Product Summary

Build a product-ready Magic: The Gathering deckbuilding application that generates competitive, legal, explainable decks from a small set of user inputs:

- format: `standard`, `modern`, `legacy`, `commander`
- optional colors or color identity
- optional playstyle preferences such as `aggressive`, `spells`, `lifegain`, `slivers`, `control`, `midrange`, `combo`, `tokens`
- optional budget, power level, wildcard ownership, collection constraints, and card exclusions

The system should generate:

- a complete main deck
- a sideboard for 60-card competitive formats
- a commander + 99 for Commander
- mana base and curve recommendations
- explanation of why the deck works
- mulligan guidance and gameplay plan
- swap suggestions and upgrades/downgrades

The product must serve two audiences well:

- beginners who need guidance, plain-English explanations, and safe defaults
- experts who want strong deck quality, metagame-aware logic, tuning controls, and transparency

The system should not rely on a single deckbuilding strategy. The correct backend is a hybrid:

- use results-based retrieval to anchor the system in real competitive decks
- use first-principles reasoning to adapt those ideas to user constraints
- use rules-based validators and scoring to enforce legality and deck quality

Pure “build from all cards from first principles” sounds compelling, but should not be the primary engine. The search space is too large, format metagames change, and “optimal” depends heavily on matchup spread, sideboarding plans, and current legality. The right product is a retrieval + reasoning + validation system.

## 2. Product Goals

### Primary goals

- Generate strong decks that are legal and coherent for the requested format
- Give users confidence in the result with explanations and evidence
- Support both fast generation and iterative tuning
- Feel premium, modern, and fun to use

### Non-goals for v1

- Full game simulation engine for exact matchup win rates
- Real-time tournament prediction with guaranteed optimality
- Native mobile apps
- Support for every MTG format on day one

## 3. Product Principles

- Legality first: never output illegal decks
- Explainability over black-box output
- Evidence-backed recommendations when possible
- Fast first result, then deeper tuning
- Beginner-friendly defaults, expert-level controls
- Every deck should have a clear plan to win

## 4. Target Users

### Beginner player

- Knows a format or favorite colors/archetypes but not the card pool
- Wants a playable deck quickly
- Needs help understanding mana curve, card roles, and sideboarding

### Intermediate grinder

- Knows archetypes and metagame basics
- Wants tuned lists for ladder or local events
- Cares about upgrades, budget substitutions, and matchup plans

### Expert competitive player

- Wants fast iteration on a shell
- Cares about metagame targeting, sideboard logic, and justification
- Wants visibility into why cards were chosen over alternatives

## 5. Core User Stories

- As a user, I can select a format and get a strong deck in under 30 seconds.
- As a user, I can specify colors, tribe, theme, or playstyle and get a deck that respects those constraints.
- As a user, I can set a budget cap and get legal substitutions.
- As a user, I can tell the system “I like aggressive red-white tokens” and receive a coherent deck plus explanation.
- As a user, I can refine the deck with follow-up prompts like “make this less weak to graveyard decks” or “reduce rares.”
- As an expert, I can inspect card roles, mana curve, sideboard plan, and candidate alternatives.
- As a Commander player, I can choose a commander or ask the system to suggest one matching my playstyle.
- As a user, I can export to common deck formats.

## 6. Recommended Product Scope

### v1 formats

- Standard
- Modern
- Legacy
- Commander

### v1 deck generation modes

- `Fast Competitive`: closest to successful meta archetypes
- `Constraint-Aware`: adapts to user colors/theme/budget constraints
- `Creative but Viable`: more novel builds with a safety floor

### v1 outputs

- decklist
- deck summary
- card role breakdown
- mana curve
- mana base explanation
- sideboard + matchup notes for 60-card formats
- commander package breakdown for EDH
- “why these cards” explanation
- alternatives and upgrade paths

## 7. Why Hybrid Logic Is The Correct Architecture

### Option 1: competition deck scraping only

Pros:

- grounded in proven lists
- easier to ship
- naturally metagame-aware

Cons:

- can only remix what already exists
- weak for novel constraints
- weak for Commander personalization
- overfits to public decks and stale metagame snapshots

### Option 2: first-principles only

Pros:

- flexible
- can generate novel ideas
- can adapt to niche constraints

Cons:

- likely to hallucinate card interactions, curve balance, or metagame positioning
- difficult to optimize across entire card pool
- hard to guarantee real competitiveness without retrieval or evaluation

### Recommended option: hybrid retrieval + reasoning + validation

Use a three-layer engine:

1. Retrieval layer
   - pull relevant decks, cards, archetypes, commanders, and meta context
2. Reasoning layer
   - adapt deck shell to user constraints and explain tradeoffs
3. Validation/scoring layer
   - enforce legality, mana quality, curve quality, role coverage, synergy, and matchup heuristics

This yields much better quality than either pure approach.

## 8. System Architecture

### Frontend

- Next.js app router
- TypeScript
- Tailwind + component system built specifically for the product
- motion library for polished transitions
- charts for mana curve and color distribution

### Backend

- Python FastAPI service or TypeScript NestJS service
- Strong recommendation: Python FastAPI for the deckbuilding engine because data processing, ranking, and future ML experiments are easier

### Storage

- Postgres for users, saved decks, prompts, tuning sessions, generated artifacts
- Redis for caching search/retrieval results and generation jobs
- Object storage for imported bulk data snapshots and analytics artifacts
- pgvector for embeddings and semantic retrieval

### Async jobs

- background worker for bulk card ingestion, tournament deck ingestion, embeddings, and offline evaluations

### AI stack

- LLM for orchestration, reasoning, explanation, and interactive refinement
- deterministic rules engine for legality and deck constraints
- retrieval pipeline over decklists, card oracle text, archetype summaries, and format knowledge
- optional reranker/scoring model for candidate deck selection

## 9. Data Sources

### Required source of truth

- Scryfall bulk data for card database, oracle text, legalities, types, mana costs, color identity, pricing, and images

### Official rules/format grounding

- Wizards format pages and banned/restricted information

### Competitive deck data

- tournament decklists from reputable sources
- league/challenge/event results where legally and operationally appropriate
- internal normalized deck corpus with event metadata, finishes, date, and archetype labels

### Commander-specific data

- commander deck prevalence and synergy-oriented sources
- internal commander archetype summaries derived from deck corpus

### Important implementation note

Do not build the system around live scraping during user requests. Ingest data offline into your own normalized dataset. User-time generation should query your database/vector store, not hit public sites directly.

## 10. Canonical Domain Model

### Card

- oracle_id
- name
- faces
- mana_cost
- mana_value
- colors
- color_identity
- type_line
- oracle_text
- keywords
- legalities by format
- price fields
- image uri
- set metadata

### Deck

- format
- archetype
- commander if applicable
- mainboard
- sideboard
- color profile
- mana curve
- derived tags
- source metadata

### DeckCandidate

- generated cards
- source inspirations
- score breakdown
- legality status
- warnings

### UserConstraint

- format
- colors/color identity
- playstyle tags
- tribe/theme tags
- budget
- owned cards
- cards to include/exclude
- power target
- novelty target

## 11. Deckbuilding Engine Design

### Stage A: intent parsing

Convert user input into structured constraints:

- format
- explicit color constraints
- inferred archetype tags
- speed preference
- synergy tags
- budget/power constraints

Example:

“Modern, I like aggressive spells and prowess, preferably Izzet, under $400”

Should become:

- format: modern
- colors: U/R
- archetype tags: aggro, spells-matter, prowess, tempo
- budget max: 400

### Stage B: candidate archetype retrieval

Retrieve top matching archetypes and deck shells from the internal corpus.

Ranking features:

- exact format match
- color match
- archetype/tag similarity
- recency weighting
- performance weighting
- card-overlap similarity to requested theme

Output:

- top 5-20 relevant archetypes or commanders

### Stage C: shell construction

Construct an initial shell:

- competitive formats: 60-card core + land count + sideboard skeleton
- commander: commander + ramp/draw/removal/wincon/template allocations

Use:

- deck corpus centroids
- staple frequency
- synergy packages
- mana requirements
- curve targets

### Stage D: reasoning-driven adaptation

Use the LLM to choose among candidate packages and modify the shell for user constraints:

- swap expensive cards for budget analogs
- bias for aggressive/control/combo play patterns
- enforce tribal or mechanic identity
- adjust removal/countermagic/interaction density
- adapt sideboard for target metagame assumptions

Important:

The LLM must not output final decks directly from raw prompt alone. It should operate as a planner over structured candidates and card pools.

### Stage E: deterministic validation

Run hard checks:

- format legality
- banned list compliance
- deck size
- copy-count limits
- commander color identity
- sideboard size
- companion constraints if relevant

### Stage F: scoring and reranking

Score deck candidates across:

- legality
- mana consistency
- curve balance
- role coverage
- synergy score
- meta alignment
- novelty score
- budget fit
- explainability confidence

Return the best candidate plus 1-2 alternatives.

### Stage G: explanation generation

Generate:

- what the deck is trying to do
- why the card packages were selected
- ideal opening patterns
- sideboard guide or commander game plan
- matchup strengths/risks

## 12. Deck Scoring Framework

Each generated deck should receive a transparent scorecard.

### Hard-pass criteria

- illegal card
- wrong deck size
- invalid sideboard
- commander color identity violation
- too few lands for minimum thresholds

### Soft scoring dimensions

- mana base quality
- curve efficiency
- threat density
- interaction density
- draw/selection support
- synergy coherence
- resilience/redundancy
- finisher clarity
- meta positioning
- budget adherence
- similarity to proven winning shells

### Example heuristics

- Aggro decks require sufficient one- and two-drop density
- Control decks require minimum interaction and card advantage counts
- Commander decks require baseline ramp/draw/removal package thresholds
- Multicolor decks require adequate untapped source counts by curve
- Tribal decks require enough tribal payoffs and member density

## 13. Format-Specific Logic

### Standard / Modern / Legacy

- built around archetype shells, matchup plans, and sideboard logic
- metagame weighting matters heavily
- should support best-of-one vs best-of-three preference where relevant

### Commander

- commander selection is a first-class step
- support both “pick my commander” and “suggest commanders for my style”
- deck should classify power band and table expectations
- include bracket/power-level guidance, not just raw optimization
- explanation should cover ramp, draw, removal, wipes, tutors, wincons, and flex slots

## 14. First-Principles Reasoning: Where It Helps

Use first-principles reasoning in constrained, auditable places:

- mapping card roles to required deck slots
- reasoning about mana curve and source counts
- selecting synergistic packages
- adjusting for budget and exclusions
- generating alternatives when exact staples are unavailable
- explaining tradeoffs

Do not use it as the sole source of truth for legality, card existence, or meta claims.

## 15. API Design

### `POST /v1/decks/generate`

Input:

- format
- colors
- theme_tags
- playstyle_tags
- budget
- collection constraints
- include/exclude cards
- mode
- experience level

Output:

- deck id
- decklist
- sideboard or commander package
- explanation
- score breakdown
- alternatives

### `POST /v1/decks/refine`

Input:

- deck id or current deck payload
- natural language refinement request

Output:

- revised deck
- diff against previous version
- updated explanation

### `GET /v1/cards/search`

- card lookup and autocomplete

### `GET /v1/meta/summary`

- format-level archetype summary and matchup context

### `POST /v1/decks/validate`

- validate legality and score a user-supplied decklist

### `POST /v1/decks/export`

- Arena, Moxfield, Archidekt, plain text, CSV

## 16. Frontend Product Spec

### Design direction

The UI should feel premium, strategic, and alive. Avoid generic SaaS styling. This product should look like a serious strategy tool, not a chatbot wrapper.

### Visual language

- strong editorial typography
- textured or gradient backgrounds with subtle fantasy-tech feel
- card art used intentionally, not cluttered everywhere
- data-dense but elegant panels
- smooth transitions between deck generation states

### Key screens

#### Landing page

- clear value proposition
- choose format quickly
- examples of prompts and generated archetypes
- trust markers: legality, meta-aware, explainable

#### Deck builder input screen

- format selector
- color selector
- playstyle/theme chips
- advanced controls drawer
- “build my deck” primary CTA
- prompt box for natural language preferences

#### Generation experience

- animated progress states:
  - parsing constraints
  - retrieving deck shells
  - evaluating candidates
  - tuning mana base
  - writing explanation

#### Deck results screen

- decklist panel
- mana curve chart
- color source chart
- role breakdown
- explanation tabs
- sideboard guide / commander package
- alt-card suggestions
- save/export/share actions

#### Refinement chat/panel

- focused on deck edits, not open-ended chat
- examples:
  - “make it cheaper”
  - “shift toward control”
  - “improve the mirror”
  - “less vulnerable to board wipes”

#### Saved decks / workspace

- version history
- compare revisions
- duplicate/edit/export

### UX principles

- beginner mode and expert mode should be explicit
- every card should show why it is in the deck
- deck diffs should be visual and easy to scan
- generation should feel guided, not opaque

## 17. Beginner vs Expert Experience

### Beginner mode

- simpler form
- prebuilt playstyle options
- extra educational copy
- safer defaults
- prominent “how to play this deck” section

### Expert mode

- richer controls
- meta-targeting options
- card-level include/exclude rules
- sideboard heuristics visibility
- score breakdown and shell provenance

## 18. Recommended Tech Stack

### Frontend

- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui or custom component primitives
- Framer Motion
- Recharts or Visx

### Backend

- FastAPI
- Pydantic
- SQLAlchemy
- Celery or Dramatiq for jobs

### Data / infra

- Postgres + pgvector
- Redis
- object storage
- hosted background worker

### AI integration

- one high-quality reasoning model for orchestration
- optional smaller model for tagging or classification
- structured outputs everywhere possible

## 19. Retrieval Strategy

Use a blended retrieval layer:

- lexical search over card names, oracle text, archetype labels
- vector search over deck summaries, archetype descriptions, and user intent
- metadata filters for format, colors, recency, performance, and budget

Retrieved items:

- tournament deck shells
- archetype summaries
- card packages
- commander packages
- matchup notes

## 20. Offline Pipelines

### Card ingestion job

- fetch Scryfall bulk data
- normalize cards
- compute derived tags
- store searchable records

### Deck ingestion job

- ingest tournament decklists
- normalize names and versions
- label archetypes
- calculate deck metrics

### Embedding job

- generate embeddings for cards, decks, archetypes, and strategy summaries

### Evaluation job

- run benchmark prompts
- compare generated decks against baseline heuristics
- track regressions

## 21. Evaluation Framework

This is critical. Do not ship “AI deckbuilding” without a measurable evaluation harness.

### Gold-standard benchmark set

Create 100-300 benchmark prompts across:

- each supported format
- beginner and expert intents
- budget and non-budget requests
- tribal/theme constraints
- competitive and casual commander requests

### Metrics

- legality pass rate
- average generation latency
- budget adherence rate
- human deck quality rating
- archetype relevance
- explanation quality
- refinement success rate

### Human review rubric

Reviewers should score:

- legality
- coherence
- competitiveness
- mana quality
- sideboard quality
- faithfulness to prompt
- clarity of explanation

### Failure categories

- illegal deck
- theme drift
- weak mana base
- insufficient interaction
- incoherent win condition
- bad sideboard
- unsupported meta claims

## 22. Launch Plan

### Phase 1: foundation

- card ingestion
- format rules and legality engine
- deck corpus ingestion
- deck generation API
- basic UI

### Phase 2: quality

- hybrid retrieval + reasoning
- scoring engine
- explanations
- refinement workflow
- saved decks

### Phase 3: product polish

- premium UI
- exports/sharing
- onboarding
- analytics
- evaluation dashboard

### Phase 4: advanced

- collection-aware building
- metagame targeting
- matchup guides
- team testing workspace

## 23. Build Order For Codex

Give Codex this implementation order:

1. Initialize monorepo with `web/` and `api/`
2. Build card ingestion pipeline around Scryfall bulk data
3. Implement format legality engine and deck validator
4. Define DB schema for cards, decks, archetypes, and generated sessions
5. Build deck corpus ingestion and normalization
6. Implement candidate retrieval by format/colors/tags
7. Implement initial shell generator
8. Implement scoring engine and hard validation
9. Add LLM orchestration for shell adaptation and explanations
10. Build `generate`, `refine`, `validate`, and `export` APIs
11. Build premium frontend flows
12. Add benchmarks, regression tests, and admin evaluation tools

## 24. Engineering Constraints

- All AI outputs must flow through schema-validated structured outputs
- All final decks must pass deterministic legality validation
- All external sources should be ingested offline when possible
- All generation steps should be logged for auditability
- Every user-visible deck should retain provenance:
  - source archetypes consulted
  - cards added by reasoning
  - cards swapped due to budget/theme constraints

## 25. Security / Reliability

- rate limit generation endpoints
- cache repeated generations
- store prompt and deck version history
- add observability for latency and failure categories
- ensure deterministic fallback when AI step fails

Fallback behavior:

- if LLM step fails, return best validated retrieved shell with a reduced explanation instead of failing completely

## 26. Risks

### Risk: “optimal” is undefined

Mitigation:

- define output modes like competitive, creative, budget, or power-banded commander

### Risk: stale metagame data

Mitigation:

- timestamp all meta claims
- recency-weight tournament data
- schedule frequent ingest jobs

### Risk: hallucinated interactions

Mitigation:

- never let the LLM invent cards
- only reason over retrieved/validated card pools

### Risk: Commander optimization conflicts with social expectations

Mitigation:

- include power-band and play-pattern labeling
- allow users to target bracket/power level explicitly

## 27. Acceptance Criteria For v1

- User can generate legal decks for all 4 supported formats
- System respects colors/theme/playstyle constraints in most benchmark cases
- Deck output includes explanation, curve, and role breakdown
- Competitive formats include sideboards and matchup notes
- Commander output includes commander rationale and package breakdown
- Median generation time is acceptable for consumer use
- UI is polished enough to feel like a real product, not an internal tool
- Evaluation harness exists and blocks obvious regressions

## 28. Concrete Instructions To Codex

Implement this as a production-oriented monorepo with:

- `web/`: Next.js frontend
- `api/`: FastAPI backend
- `packages/shared/`: shared types/schemas if needed
- `infra/`: local dev infra and deployment scaffolding

Prioritize correctness of legality, data modeling, retrieval quality, and explainable deck generation over flashy AI behavior. The deckbuilding engine must be hybrid, not prompt-only. Use Scryfall as the canonical card source, ingest deck data into internal storage, and ensure every final deck passes deterministic validation before it is shown to users.

For UX, build a premium deck workshop experience with strong visual design, fast interactions, and a focused refinement workflow. The primary differentiator should be: “strong decks with transparent reasoning,” not “chat with an LLM.”

## 29. Suggested First Deliverable

Ask Codex to produce this in four initial deliverables:

1. architecture.md
   - system architecture, domain model, API surface
2. implementation_plan.md
   - milestone-based task plan with dependencies
3. monorepo scaffold
   - Next.js + FastAPI + Postgres dev setup
4. v1 backend foundation
   - Scryfall ingestion, legality engine, and `/v1/decks/validate`

## 30. Sources To Anchor The Build

- Scryfall recommends bulk data for large-scale card access rather than high-volume live API usage: [Scryfall API FAQ](https://scryfall.com/docs/faqs/i-m-having-trouble-accessing-the-scryfall-api-or-i-m-blocked-17)
- Official format rules and deck construction details: [MTG Formats Hub](https://magic.wizards.com/en/formats), [Standard](https://magic.wizards.com/en/formats/standard), [Modern](https://magic.wizards.com/en/formats/modern), [Legacy](https://magic.wizards.com/en/formats/legacy), [Commander](https://magic.wizards.com/en/content/commander-format)
- Commander ecosystem signal example: [EDHREC About](https://edhrec.com/about-us)
