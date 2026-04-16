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
- heuristic deck generation for the supported formats
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

- tournament deck ingestion
- persistent database storage
- pgvector retrieval
- live LLM orchestration
- authentication
