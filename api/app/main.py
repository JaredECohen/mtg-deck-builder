import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.auth import require_api_key
from app.config import CORS_ORIGINS
from app.models import (
    AnalyzeDeckRequest,
    CardDetailResponse,
    CardSearchResponse,
    CommanderProfileResponse,
    CommanderSearchResponse,
    DataStatusResponse,
    DeckAnalysisResponse,
    DeckResponse,
    DiffDeckRequest,
    EvaluateDeckRequest,
    ExportDeckRequest,
    FormatName,
    GenerateDeckRequest,
    MetaSummaryResponse,
    ParseDecklistRequest,
    ParsedDecklistResponse,
    RefineDeckRequest,
    SaveDeckRequest,
    ValidateDeckRequest,
    ValidationResult,
)
from app.optimizer import AnnealConfig, OptimizerConstraints
from app.rate_limiter import (
    deck_rate_limiter,
    evaluate_rate_limiter,
    prose_rate_limiter,
)
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


from app.services.deck_history_service import DeckHistoryService
from app.services.vector_retrieval import CardVectorRetriever

repository = CardRepository()
card_retriever = CardVectorRetriever(repository)
deck_history = DeckHistoryService()
validator = DeckValidator(repository)
generator = DeckGenerator(repository, validator)
analysis_service = DeckAnalysisService(repository, validator)
parser_service = DeckParserService(repository)
card_refresh_service = CardRefreshService(repository)
repository.refresh_service = card_refresh_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

@asynccontextmanager
async def _lifespan(app: FastAPI):
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
def health() -> dict[str, str]:
    status = repository.data_status()
    return {"status": "ok", "card_source": status.card_source, "archetype_source": status.archetype_source}


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


@app.post("/v1/decks/evaluate")
def evaluate_deck(
    request: EvaluateDeckRequest,
    req: Request,
    _key: str | None = Depends(require_api_key),
) -> dict:
    """Run the multi-signal evaluation engine on a concrete decklist.

    Returns flood/screw resistance, interaction resilience, inevitability,
    consistency, card-advantage density, and a Wilson-interval win rate —
    the same battery the optimizer's deep-eval uses, exposed directly.
    """
    client_ip = req.client.host if req.client else "unknown"
    if not evaluate_rate_limiter.is_allowed(f"evaluate:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many evaluation requests. Please wait before trying again.")
    from app.services.deck_evaluation_service import evaluate_decklist
    try:
        return evaluate_decklist(
            format_id=request.format,
            mainboard=request.mainboard,
            repository=repository,
            games=request.games,
            seed=request.seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/decks/diff")
def diff_deck(request: DiffDeckRequest) -> dict:
    """Card-by-card diff between two decklists (before → after)."""
    from app.services.deck_diff import diff_decks
    return diff_decks(request.before, request.after).to_dict()


@app.post("/v1/decks/save")
def save_deck(
    request: SaveDeckRequest,
    key: str | None = Depends(require_api_key),
) -> dict:
    """Persist a deck to history and mint a share token. When auth is
    enabled the API key becomes the deck's owner."""
    return deck_history.save(
        name=request.name,
        format_id=request.format,
        mainboard=[c.model_dump() for c in request.mainboard],
        sideboard=[c.model_dump() for c in request.sideboard],
        commander=request.commander,
        notes=request.notes,
        evaluation=request.evaluation,
        owner=key,
    )


@app.get("/v1/decks/history")
def deck_history_list(
    limit: int = 50,
    key: str | None = Depends(require_api_key),
) -> dict:
    return {"decks": deck_history.history(owner=key, limit=max(1, min(limit, 200)))}


@app.get("/v1/decks/saved/{deck_id}")
def get_saved_deck(deck_id: str) -> dict:
    deck = deck_history.get(deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail="saved deck not found")
    return deck


@app.get("/v1/decks/shared/{token}")
def get_shared_deck(token: str) -> dict:
    deck = deck_history.get_by_share_token(token)
    if deck is None:
        raise HTTPException(status_code=404, detail="shared deck not found")
    return deck


@app.delete("/v1/decks/saved/{deck_id}")
def delete_saved_deck(
    deck_id: str,
    key: str | None = Depends(require_api_key),
) -> dict:
    if not deck_history.delete(deck_id, owner=key):
        raise HTTPException(status_code=404, detail="saved deck not found")
    return {"deleted": deck_id}


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
def submit_optimize(
    request: OptimizerJobRequest,
    req: Request,
    _key: str | None = Depends(require_api_key),
) -> OptimizerJobResponse:
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
def get_job_prose(
    job_id: str,
    req: Request,
    _key: str | None = Depends(require_api_key),
) -> Response:
    """Lazily produce LLM-narrated coach prose for a completed
    optimizer job.

    Gated by optional API-key auth and a tighter rate limit than the
    deterministic endpoints, since it fans out to an LLM.

    * 200 — prose ready (or null when LLM is disabled / no API key)
    * 202 — job still running; client should poll the prose endpoint
            again after the parent job completes
    * 404 — unknown job, or job has no rationale
    * 409 — job failed
    * 429 — prose rate limit exceeded
    """
    from fastapi.responses import JSONResponse
    from app.services.deck_rationale import prose_for_rationale_dict
    client_ip = req.client.host if req.client else "unknown"
    if not prose_rate_limiter.is_allowed(f"prose:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many prose requests. Please wait before trying again.")
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


@app.get("/v1/cards/{card_name}", response_model=CardDetailResponse)
def card_detail(card_name: str) -> CardDetailResponse:
    card = repository.get_card(card_name)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return CardDetailResponse(card=card)


@app.get("/v1/cards", response_model=CardSearchResponse)
def card_search(query: str, format: FormatName | None = None, limit: int = 12) -> CardSearchResponse:
    return CardSearchResponse(cards=repository.search_cards(query=query, format_name=format, limit=limit))


@app.get("/v1/cards/{card_name}/similar")
def similar_cards(card_name: str, k: int = 10) -> dict:
    """Semantic-ish nearest neighbours for a card (pgvector when wired,
    deterministic lexical-feature cosine otherwise)."""
    if repository.get_card(card_name) is None:
        raise HTTPException(status_code=404, detail="Card not found")
    hits = card_retriever.similar_to(card_name, k=max(1, min(k, 50)))
    return {
        "card": card_name,
        "mode": "pgvector" if card_retriever.use_pgvector else "lexical",
        "similar": [h.to_dict() for h in hits],
    }


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
