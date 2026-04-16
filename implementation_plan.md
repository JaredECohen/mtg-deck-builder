# Implementation Plan

## Milestone 1: Foundation

- scaffold monorepo
- stand up FastAPI application
- stand up Next.js application
- define core domain models and API contracts
- implement local sample data repository

## Milestone 2: Deck Correctness

- implement deterministic validation engine
- enforce format legality and copy-count rules
- add score breakdown
- build baseline generation and refinement flow
- add export path

## Milestone 3: Data Ingestion

- wire Scryfall bulk-data ingestion to persistent storage
- normalize card legalities, type data, and prices
- add offline tournament deck ingestion and archetype labeling
- compute derived tags and package metadata

## Milestone 4: Hybrid Intelligence

- implement lexical + vector retrieval
- retrieve archetype shells and card packages
- use structured LLM planning for shell adaptation
- preserve provenance for retrieved vs generated decisions

## Milestone 5: Product Polish

- add persistent deck history
- add charts and deck diff UX
- add export targets and sharing
- add observability and regression benchmarks
- add authentication and user workspaces

## Immediate Next Tasks

1. Install backend and frontend dependencies.
2. Run API tests and launch the FastAPI service.
3. Replace sample archetype/card JSON with richer seeded datasets.
4. Add database models and persistence.
5. Add mana-curve, source-count, and role-balance heuristics beyond the current baseline validator.

