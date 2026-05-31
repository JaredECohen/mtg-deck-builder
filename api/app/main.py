import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.config import CORS_ORIGINS
from app.models import (
    AnalyzeDeckRequest,
    CardDetailResponse,
    CardSearchResponse,
    ChatDeckRequest,
    ChatDeckResponse,
    ChatMessage,
    CommanderProfileResponse,
    CommanderSearchResponse,
    DataStatusResponse,
    DeckAnalysisResponse,
    DeckResponse,
    ExportDeckRequest,
    FormatName,
    GenerateDeckRequest,
    MetaSummaryResponse,
    ParseDecklistRequest,
    ParsedDecklistResponse,
    RefineDeckRequest,
    SaveDeckRequest,
    SavedDeckResponse,
    SavedDeckSummary,
    SavedDecksResponse,
    ValidateDeckRequest,
    ValidationResult,
)
from app.optimizer import AnnealConfig, OptimizerConstraints
from app.rate_limiter import deck_rate_limiter
from app.services.card_refresh import CardRefreshService
from app.services.card_repository import CardRepository
from app.services.deck_analysis import DeckAnalysisService
from app.services.deck_generator import DeckGenerator
from app.services.deck_parser import DeckParserService
from app.services.deck_validator import DeckValidator
from app.services.optimizer_service import (
    OptimizerJobRequest,
    OptimizerJobResponse,
    submit_optimize_job,
)
from app.workers import JobNotFound, get_job_queue


repository = CardRepository()
validator = DeckValidator(repository)
generator = DeckGenerator(repository, validator)
analysis_service = DeckAnalysisService(repository, validator)
parser_service = DeckParserService(repository)
card_refresh_service = CardRefreshService(repository)
repository.refresh_service = card_refresh_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

def _card_profile_coverage() -> dict[str, int | float | str]:
    """Compare card count vs card_profiles count. Surfaces the stale-profile
    case where the optimizer's _build_pool silently returns nothing because
    no profiles exist. Threshold is 60%.
    """
    from sqlalchemy import func, select
    from app.db import session_scope
    from app.db_models import Card, CardProfile
    try:
        with session_scope() as session:
            card_total = session.scalar(select(func.count()).select_from(Card)) or 0
            profile_total = session.scalar(select(func.count()).select_from(CardProfile)) or 0
    except Exception:
        return {"status": "unknown", "cards": 0, "profiles": 0, "coverage": 0.0}
    coverage = (profile_total / card_total) if card_total else 0.0
    status = "ok" if coverage >= 0.60 else "stale"
    return {
        "status": status,
        "cards": int(card_total),
        "profiles": int(profile_total),
        "coverage": round(coverage, 4),
    }


def _ensure_saved_deck_chat_column() -> None:
    """SQLite-only inline migration: add chat_history JSON column to
    saved_decks if it doesn't exist. Idempotent — safe to call every boot.
    """
    from sqlalchemy import inspect, text
    from app.db import get_engine
    eng = get_engine()
    inspector = inspect(eng)
    try:
        cols = {c["name"] for c in inspector.get_columns("saved_decks")}
    except Exception:
        return
    if "chat_history" in cols:
        return
    with eng.begin() as conn:
        conn.execute(text("ALTER TABLE saved_decks ADD COLUMN chat_history JSON DEFAULT '[]'"))


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Bootstrap any tables added since last ingest run (e.g. saved_decks)
    # without disturbing existing data.
    from app.services.database_bootstrap import create_schema
    try:
        create_schema()
        _ensure_saved_deck_chat_column()
    except Exception:
        logger.warning("schema bootstrap on startup failed", exc_info=True)
    # Warn loudly when card_profiles is stale: the optimizer silently
    # returns an empty pool ("optimizer pool is empty") when profiles
    # are missing, which is hard to diagnose without this check.
    try:
        coverage = _card_profile_coverage()
        if coverage["status"] == "stale":
            logger.warning(
                "card_profiles coverage is %.0f%% (%d/%d). Optimizer will return empty pools. "
                "Run: python -m app.scripts.build_card_profiles",
                float(coverage["coverage"]) * 100,
                int(coverage["profiles"]),
                int(coverage["cards"]),
            )
    except Exception:
        logger.warning("card_profile coverage check failed", exc_info=True)
    card_refresh_service.start()
    try:
        yield
    finally:
        card_refresh_service.stop()


app = FastAPI(title="MTG Deck Builder API", version="0.1.0", lifespan=_lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next: object) -> Response:
    start = time.monotonic()
    response: Response = await call_next(request)  # type: ignore[operator]
    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info("%s %s → %d (%.0fms)", request.method, request.url.path, response.status_code, elapsed_ms)
    return response
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, object]:
    status = repository.data_status()
    profile_coverage = _card_profile_coverage()
    overall = "ok" if profile_coverage["status"] == "ok" else "degraded"
    return {
        "status": overall,
        "card_source": status.card_source,
        "archetype_source": status.archetype_source,
        "card_profiles": profile_coverage,
    }


@app.get("/api/data-status", response_model=DataStatusResponse)
def data_status() -> DataStatusResponse:
    return repository.data_status()


@app.post("/v1/decks/generate", response_model=DeckResponse)
def generate_deck(request: GenerateDeckRequest, req: Request) -> DeckResponse:
    """Generate a deck.

    By default routes to the legacy heuristic generator. When
    ``MTG_USE_OPTIMIZER_DEFAULT=true`` is set, routes to the
    simulator-driven optimizer with a synchronous wrapper that returns
    the same ``DeckResponse`` shape. Falls back to legacy on optimizer
    errors so users never see a stack trace.
    """
    import os
    client_ip = req.client.host if req.client else "unknown"
    if not deck_rate_limiter.is_allowed(f"generate:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many generation requests. Please wait before trying again.")

    use_optimizer = os.getenv("MTG_USE_OPTIMIZER_DEFAULT", "").lower() in {"1", "true", "yes"}
    if use_optimizer and request.format == "modern":
        try:
            from app.services.optimizer_default_path import generate_via_optimizer
            return generate_via_optimizer(request, repository=repository, validator=validator)
        except Exception as exc:  # noqa: BLE001
            logger.warning("optimizer-default path failed (%s); falling back to legacy", exc)

    try:
        return generator.generate(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/decks/refine", response_model=DeckResponse)
def refine_deck(request: RefineDeckRequest, req: Request) -> DeckResponse:
    client_ip = req.client.host if req.client else "unknown"
    if not deck_rate_limiter.is_allowed(f"refine:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many refinement requests. Please wait before trying again.")
    try:
        return generator.refine(request.deck, request.refinement_prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/decks/chat", response_model=ChatDeckResponse)
def chat_deck(request: ChatDeckRequest, req: Request) -> ChatDeckResponse:
    client_ip = req.client.host if req.client else "unknown"
    if not deck_rate_limiter.is_allowed(f"chat:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many chat requests. Please wait before trying again.")

    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")

    deck = request.deck
    main_lines = "\n".join(f"  {c.quantity}x {c.name}" for c in deck.mainboard)
    side_lines = "\n".join(f"  {c.quantity}x {c.name}" for c in deck.sideboard) or "  (empty)"
    archetype_line = deck.selected_archetype.name if deck.selected_archetype else "none"
    warnings_text = "; ".join(deck.warnings[:6]) or "none"
    deck_summary = (
        f"Title: {deck.title}\n"
        f"Format: {deck.format} | Colors: {','.join(deck.colors) or '—'} | Commander: {deck.commander or 'n/a'}\n"
        f"Selected archetype: {archetype_line}\n"
        f"Strategy summary: {deck.strategy_summary}\n"
        f"Warnings: {warnings_text}\n"
        f"\nMainboard ({sum(c.quantity for c in deck.mainboard)}):\n{main_lines}\n"
        f"\nSideboard ({sum(c.quantity for c in deck.sideboard)}):\n{side_lines}"
    )

    from app.services.llm_service import chat_about_deck
    result = chat_about_deck(
        deck_summary=deck_summary,
        history=[m.model_dump() for m in request.history],
        user_message=message,
    )
    if result is None:
        raise HTTPException(status_code=503, detail="Deck chat is unavailable (LLM not configured or call failed).")
    return ChatDeckResponse(reply=result["reply"], suggested_refinement=result.get("suggested_refinement"))


@app.post("/v1/decks/save", response_model=SavedDeckSummary)
def save_deck(request: SaveDeckRequest) -> SavedDeckSummary:
    import uuid
    from datetime import datetime, timezone
    from app.db import session_scope
    from app.db_models import SavedDeck

    deck_id = uuid.uuid4().hex[:16]
    created_at = datetime.now(timezone.utc).isoformat()
    chat_payload = [m.model_dump() for m in request.chat_history]
    with session_scope() as session:
        row = SavedDeck(
            id=deck_id,
            session_id=request.session_id,
            title=request.deck.title or "Untitled Deck",
            format=request.deck.format,
            deck_json=request.deck.model_dump(),
            chat_history=chat_payload,
            created_at=created_at,
        )
        session.add(row)
    return SavedDeckSummary(
        id=deck_id,
        title=request.deck.title or "Untitled Deck",
        format=request.deck.format,
        created_at=created_at,
    )


@app.get("/v1/decks/saved", response_model=SavedDecksResponse)
def list_saved_decks(session_id: str) -> SavedDecksResponse:
    from sqlalchemy import select
    from app.db import session_scope
    from app.db_models import SavedDeck

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    with session_scope() as session:
        rows = session.scalars(
            select(SavedDeck).where(SavedDeck.session_id == session_id).order_by(SavedDeck.created_at.desc())
        ).all()
        decks = [
            SavedDeckSummary(id=row.id, title=row.title, format=row.format, created_at=row.created_at)
            for row in rows
        ]
    return SavedDecksResponse(decks=decks)


@app.get("/v1/decks/saved/{deck_id}", response_model=SavedDeckResponse)
def get_saved_deck(deck_id: str) -> SavedDeckResponse:
    from app.db import session_scope
    from app.db_models import SavedDeck

    with session_scope() as session:
        row = session.get(SavedDeck, deck_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Saved deck not found")
        chat_payload = row.chat_history or []
        return SavedDeckResponse(
            id=row.id,
            title=row.title,
            format=row.format,
            created_at=row.created_at,
            deck=DeckResponse.model_validate(row.deck_json),
            chat_history=[ChatMessage.model_validate(m) for m in chat_payload],
        )


@app.delete("/v1/decks/saved/{deck_id}")
def delete_saved_deck(deck_id: str, session_id: str) -> dict[str, str]:
    from app.db import session_scope
    from app.db_models import SavedDeck

    with session_scope() as session:
        row = session.get(SavedDeck, deck_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Saved deck not found")
        if row.session_id != session_id:
            raise HTTPException(status_code=403, detail="Not authorized to delete this deck")
        session.delete(row)
    return {"status": "deleted", "id": deck_id}


@app.post("/v1/decks/validate", response_model=ValidationResult)
def validate_deck(request: ValidateDeckRequest) -> ValidationResult:
    try:
        return validator.validate(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/decks/analyze", response_model=DeckAnalysisResponse)
def analyze_deck(request: AnalyzeDeckRequest) -> DeckAnalysisResponse:
    try:
        return analysis_service.analyze(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/decks/parse", response_model=ParsedDecklistResponse)
def parse_deck(request: ParseDecklistRequest) -> ParsedDecklistResponse:
    try:
        return parser_service.parse(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/decks/export")
def export_deck(request: ExportDeckRequest) -> dict[str, str]:
    try:
        return {"target": request.target, "content": generator.export(request.deck, request.target)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/jobs/optimize", response_model=OptimizerJobResponse)
def submit_optimize(request: OptimizerJobRequest, req: Request) -> OptimizerJobResponse:
    client_ip = req.client.host if req.client else "unknown"
    if not deck_rate_limiter.is_allowed(f"optimize:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many optimizer submissions. Wait before retrying.")
    try:
        return submit_optimize_job(request, repository=repository)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        job = get_job_queue().get(job_id)
    except (JobNotFound, KeyError) as exc:
        raise HTTPException(status_code=404, detail=f"job {job_id!r} not found") from exc
    return job.to_dict()


@app.post("/v1/jobs/{job_id}/prose")
def get_job_prose(job_id: str) -> Response:
    """Lazily produce LLM-narrated coach prose for a completed
    optimizer job.

    * 200 — prose ready (or null when LLM is disabled / no API key)
    * 202 — job still running; client should poll the prose endpoint
            again after the parent job completes
    * 404 — unknown job, or job has no rationale
    * 409 — job failed
    """
    from fastapi.responses import JSONResponse
    from app.services.deck_rationale import prose_for_rationale_dict
    try:
        job = get_job_queue().get(job_id)
    except (JobNotFound, KeyError) as exc:
        raise HTTPException(status_code=404, detail=f"job {job_id!r} not found") from exc
    if job.status == "failed":
        raise HTTPException(status_code=409, detail=f"job failed: {job.error or 'unknown'}")
    if job.status not in {"succeeded", "cached"}:
        return JSONResponse(
            status_code=202,
            content={"job_id": job_id, "status": job.status, "prose": None},
        )
    result = job.result or {}
    rationale = result.get("rationale")
    if rationale is None:
        raise HTTPException(status_code=404, detail="no rationale on this job")
    prose = prose_for_rationale_dict(rationale)
    return JSONResponse(
        status_code=200,
        content={"job_id": job_id, "prose": prose.to_dict() if prose else None},
    )


@app.get("/v1/meta/summary", response_model=MetaSummaryResponse)
def meta_summary(format: FormatName) -> MetaSummaryResponse:
    archetypes = repository.archetypes_for_format(format)
    return MetaSummaryResponse(format=format, archetypes=archetypes)


@app.get("/v1/cards/{card_name:path}", response_model=CardDetailResponse)
def card_detail(card_name: str) -> CardDetailResponse:
    # Use `:path` so URL-encoded `/` in DFC names (e.g. "Tamiyo, Inquisitive
    # Student // Tamiyo, Seasoned Scholar") doesn't break route matching.
    # On any miss, fall back to the front-face name (split on " // ") so
    # decks that reference the canonical full DFC name still resolve when
    # the DB only has the front-face entry.
    card = repository.get_card(card_name)
    if not card and " // " in card_name:
        card = repository.get_card(card_name.split(" // ", 1)[0])
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return CardDetailResponse(card=card)


@app.get("/v1/cards", response_model=CardSearchResponse)
def card_search(query: str, format: FormatName | None = None, limit: int = 12) -> CardSearchResponse:
    return CardSearchResponse(cards=repository.search_cards(query=query, format_name=format, limit=limit))


@app.get("/v1/commanders", response_model=CommanderSearchResponse)
def commander_search(
    colors: str | None = None,
    playstyle_tags: str | None = None,
    theme_tags: str | None = None,
    search: str | None = None,
    sort: str = "match",
    limit: int = 25,
) -> CommanderSearchResponse:
    commanders = repository.rank_commanders(
        colors=[color for color in (colors or "").split(",") if color],
        playstyle_tags=[tag for tag in (playstyle_tags or "").split(",") if tag],
        theme_tags=[tag for tag in (theme_tags or "").split(",") if tag],
        search=search,
        sort=sort,
        limit=limit,
    )
    return CommanderSearchResponse(commanders=commanders)


@app.get("/v1/commanders/{commander_name}", response_model=CommanderProfileResponse)
def commander_detail(commander_name: str) -> CommanderProfileResponse:
    commander = repository.get_commander_profile(commander_name)
    if not commander:
        raise HTTPException(status_code=404, detail="Commander not found")
    return CommanderProfileResponse(commander=commander)
