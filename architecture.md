# Architecture

## Overview

The product is implemented as a monorepo with a separated frontend and backend:

- `web/`: Next.js application that provides the deck workshop UI
- `api/`: FastAPI application for deck generation, validation, refinement, and export
- `packages/shared/`: reserved for shared contracts as the system matures

## Current Backend Design

### API layer

FastAPI exposes:

- `GET /api/health`
- `POST /v1/decks/generate`
- `POST /v1/decks/refine`
- `POST /v1/decks/validate`
- `POST /v1/decks/export`

### Domain models

Pydantic models define:

- request/response contracts
- deck, card, and archetype records
- score breakdown and validation results

### Services

- `CardRepository`: loads card and archetype data from local JSON files
- `DeckValidator`: enforces hard format/deck-size/copy-count rules and computes a scorecard
- `DeckGenerator`: retrieves candidate archetypes, adapts them to user constraints, validates the result, and produces explanations

### Data strategy

The current implementation uses sample JSON data as a local bootstrap dataset. The ingestion path is already separated so this can be replaced by:

- Scryfall bulk card data
- normalized tournament deck corpus
- commander package datasets
- Postgres + pgvector persistence

## Current Frontend Design

### Application shape

The homepage combines:

- landing hero
- input controls for format/colors/playstyle/budget/prompt
- result panes for decklist, explanation, and refinement

### State flow

- user configures deck constraints
- UI calls `/v1/decks/generate`
- returned deck payload renders in the workshop
- user submits refinement prompt
- UI calls `/v1/decks/refine`

## Planned Evolution

### Backend next steps

- replace sample card store with Postgres-backed repository
- ingest Scryfall bulk data into normalized tables
- add tournament deck ingestion pipeline
- add semantic retrieval and reranking
- integrate structured LLM planning over retrieved card packages

### Frontend next steps

- add richer charts for mana curve and color sources
- add deck diff visualization
- add save/share/export flows
- add beginner vs expert modes
- add loading progress stages that map to backend generation phases

