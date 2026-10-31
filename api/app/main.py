import logging
import os
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.auth import is_valid_key, require_api_key
from app.config import CORS_ORIGINS
from app.models import (
    AnalyzeDeckRequest,
    CardDetailResponse,
    CardSearchResponse,
    ChatDeckRequest,
    ChatDeckResponse,
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
    MagicLinkRequest,
    MetaSummaryResponse,
    ParseDecklistRequest,
    ParsedDecklistResponse,
    PreconSearchResponse,
    PreconUpgradeRequest,
    PreconUpgradeResponse,
    RefineDeckRequest,
    SaveDeckRequest,
    UpdateDeckRequest,
    ValidateDeckRequest,
    ValidationResult,
    VerifyLinkRequest,
)
from app.rate_limiter import (
    deck_rate_limiter,
    evaluate_rate_limiter,
    prose_rate_limiter,
    public_rate_limiter,
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


import app.services.auth_service as auth_module
from app.services.auth_service import log_auth_debug_configuration, normalize_email, valid_preauth
from app.services.deck_history_service import DeckHistoryService, owner_id
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

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
log_auth_debug_configuration()

# Behind a reverse proxy (the Next.js /api/backend proxy, a load balancer)
# every request arrives from the proxy's address, so per-client rate limits
# collapse into one bucket. X-Forwarded-For is trusted when:
#   - MTG_TRUST_FORWARDED=1 (the API is reachable only through such a proxy), or
#   - the request carries a valid X-API-Key. Only the web proxy holds the key,
#     so a public API (e.g. Fly behind Vercel) can't be spoofed by direct callers.
TRUST_FORWARDED = os.getenv("MTG_TRUST_FORWARDED", "").lower() in {"1", "true", "yes"}


# On Fly.io the edge proxy sets Fly-Client-IP to the real caller (callers
# can't override it), while req.client is Fly's internal proxy address.
ON_FLY = bool(os.getenv("FLY_APP_NAME"))

_last_ip_fallback_log: dict[str, float] = {}
_IP_FALLBACK_LOG_SECONDS = 60.0


def _note_client_ip_fallback(reason: str) -> None:
    """Warn when a production request has no platform client IP. At most once a minute per reason."""
    production = bool(os.getenv("FLY_APP_NAME", "").strip()) or os.getenv("ENV", "").strip().lower() == "production"
    if not production:
        return
    now = time.monotonic()
    previous = _last_ip_fallback_log.get(reason, 0.0)
    if previous and now - previous < _IP_FALLBACK_LOG_SECONDS:
        return
    _last_ip_fallback_log[reason] = now
    logger.warning("client IP fell back to %s; rate limits may share one bucket", reason)


def client_key(req: Request) -> str:
    """Rate-limit identity.

    A client-supplied ``X-Forwarded-For`` is ignored unless this process is
    explicitly configured to trust it, or the request presents a valid API key.
    Only the web proxy holds that key, and it sets the header from the
    platform client IP (``x-vercel-forwarded-for`` or ``x-real-ip``), not from
    the browser's header. Direct callers are limited by ``Fly-Client-IP`` or
    the socket peer.
    """
    if TRUST_FORWARDED or is_valid_key(req.headers.get("x-api-key")):
        forwarded = req.headers.get("x-forwarded-for", "")
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    if ON_FLY and req.headers.get("fly-client-ip"):
        _note_client_ip_fallback("fly-client-ip")
        return req.headers["fly-client-ip"]
    if req.client and req.client.host:
        return req.client.host
    _note_client_ip_fallback("missing")
    return "unknown"


# Whole-response cache for identical generate requests (spec §25 "cache
# repeated generations"). Generation is deterministic for a given request
# without an LLM, and LLM sub-results are cached anyway; this skips the
# rebuild entirely. Small and short-lived: it's a burst/refresh absorber.
_GENERATE_CACHE_TTL = float(os.getenv("MTG_GENERATE_CACHE_TTL", "600"))
_GENERATE_CACHE_MAX = 256
_generate_cache: "OrderedDict[str, tuple[float, DeckResponse]]" = OrderedDict()
_generate_cache_lock = threading.Lock()


def _cache_get(key: str) -> DeckResponse | None:
    with _generate_cache_lock:
        hit = _generate_cache.get(key)
        if hit is None:
            return None
        stored_at, deck = hit
        if time.monotonic() - stored_at > _GENERATE_CACHE_TTL:
            del _generate_cache[key]
            return None
        _generate_cache.move_to_end(key)
        return deck.model_copy(deep=True)


def _cache_put(key: str, deck: DeckResponse) -> None:
    with _generate_cache_lock:
        _generate_cache[key] = (time.monotonic(), deck.model_copy(deep=True))
        _generate_cache.move_to_end(key)
        while len(_generate_cache) > _GENERATE_CACHE_MAX:
            _generate_cache.popitem(last=False)

def _card_profile_coverage() -> dict[str, int | float | str]:
    """Compare card count vs card_profiles count.

    A full ingest (about 35k cards) is stale under 90% coverage. The CI
    fixture is a couple thousand cards and stays on the 60% bar. An empty
    database is not stale — there is nothing to be stale about.
    """
    from sqlalchemy import func, select
    from app.db import session_scope
    from app.db_models import Card, CardProfile
    from app.services.profile_coverage import coverage_report
    try:
        with session_scope() as session:
            card_total = session.scalar(select(func.count()).select_from(Card)) or 0
            profile_total = session.scalar(select(func.count()).select_from(CardProfile)) or 0
    except Exception:
        return {"status": "unknown", "cards": 0, "profiles": 0, "coverage": 0.0, "target": 0.0}
    return coverage_report(int(card_total), int(profile_total))


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Bootstrap any tables added since last ingest run (e.g. saved_decks)
    # without disturbing existing data.
    from app.services.database_bootstrap import create_schema
    try:
        create_schema()
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
                "Run: python -m app.scripts.build_card_profiles --all",
                float(coverage["coverage"]) * 100,
                int(coverage["profiles"]),
                int(coverage["cards"]),
            )
    except Exception:
        logger.warning("card_profile coverage check failed", exc_info=True)
    card_refresh_service.start()
    # Build the per-format sideboard pools and the bracket scans (oracle-text
    # passes over the whole card pool) off the request path; the first
    # generation otherwise pays ~10 s for them on the full dataset.
    if os.getenv("MTG_WARM_CACHES", "1").lower() not in {"0", "false", "no"}:
        threading.Thread(target=generator.warm_caches, name="warm-caches", daemon=True).start()
    try:
        yield
    finally:
        card_refresh_service.stop()


app = FastAPI(title="MTG Deck Builder API", version="0.1.0", lifespan=_lifespan)


_LIMITED_ELSEWHERE = (
    "/v1/decks/generate",
    "/v1/decks/refine",
    "/v1/decks/chat",
    "/v1/decks/evaluate",
    "/v1/jobs/",
    "/v1/commander/precon-upgrade",
)


@app.middleware("http")
async def log_requests(request: Request, call_next: object) -> Response:
    start = time.monotonic()
    path = request.url.path
    if (path.startswith("/v1/") or path.startswith("/api/")) and not path.startswith(_LIMITED_ELSEWHERE):
        if not public_rate_limiter.is_allowed(f"public:{client_key(request)}"):
            return JSONResponse(status_code=429, content={"detail": "Too many requests. Please slow down."})
    try:
        response: Response = await call_next(request)  # type: ignore[operator]
    except Exception:
        # Failure category for observability; never leak the traceback.
        logger.exception("request failed category=internal method=%s path=%s", request.method, path)
        return JSONResponse(status_code=500, content={"detail": "Internal error. It has been logged."})
    elapsed_ms = (time.monotonic() - start) * 1000
    category = (
        "ok" if response.status_code < 400
        else "rate_limited" if response.status_code == 429
        else "auth" if response.status_code in (401, 403)
        else "client_error" if response.status_code < 500
        else "server_error"
    )
    logger.info("%s %s → %d (%.0fms) category=%s", request.method, path, response.status_code, elapsed_ms, category)
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
def generate_deck(
    request: GenerateDeckRequest,
    req: Request,
    _key: str | None = Depends(require_api_key),
) -> DeckResponse:
    """Generate a deck.

    By default routes to the legacy heuristic generator. When
    ``MTG_USE_OPTIMIZER_DEFAULT=true`` is set, routes to the
    simulator-driven optimizer with a synchronous wrapper that returns
    the same ``DeckResponse`` shape. Falls back to legacy on optimizer
    errors so users never see a stack trace.
    """
    client_ip = client_key(req)
    if not deck_rate_limiter.is_allowed(f"generate:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many generation requests. Please wait before trying again.")

    use_optimizer = os.getenv("MTG_USE_OPTIMIZER_DEFAULT", "").lower() in {"1", "true", "yes"}
    cache_key = f"{int(use_optimizer)}:{request.model_dump_json()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    deck = _generate_uncached(request, use_optimizer)
    _cache_put(cache_key, deck)
    return deck


def _generate_uncached(request: GenerateDeckRequest, use_optimizer: bool) -> DeckResponse:
    if use_optimizer and request.format != "commander":
        try:
            from app.services.optimizer_default_path import generate_via_optimizer
            return generate_via_optimizer(request, repository=repository, validator=validator, generator=generator)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("optimizer-default path failed (%s); falling back to legacy", exc)

    try:
        return generator.generate(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/decks/refine", response_model=DeckResponse)
def refine_deck(
    request: RefineDeckRequest,
    req: Request,
    _key: str | None = Depends(require_api_key),
) -> DeckResponse:
    client_ip = client_key(req)
    if not deck_rate_limiter.is_allowed(f"refine:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many refinement requests. Please wait before trying again.")
    try:
        return generator.refine(request.deck, request.refinement_prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/decks/chat", response_model=ChatDeckResponse)
def chat_deck(
    request: ChatDeckRequest,
    req: Request,
    # Spends LLM tokens on every call, so it is gated like optimize/prose/save.
    # A no-op while MTG_API_KEY is unset (auth disabled).
    _key: str | None = Depends(require_api_key),
) -> ChatDeckResponse:
    client_ip = client_key(req)
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


@app.post("/v1/decks/validate", response_model=ValidationResult)
def validate_deck(request: ValidateDeckRequest) -> ValidationResult:
    try:
        return validator.validate(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/decks/analyze", response_model=DeckAnalysisResponse)
def analyze_deck(
    request: AnalyzeDeckRequest,
    _key: str | None = Depends(require_api_key),
) -> DeckAnalysisResponse:
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
    client_ip = client_key(req)
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


def _extra_secrets(session_token: str | None, api_key: str | None) -> list[str]:
    """Request-scoped secrets to strip from deck text before it is stored."""
    return [value for value in (session_token, api_key) if value]


def _session_header(x_user_session: str | None) -> str:
    return (x_user_session or "").strip()


def current_owner(
    key: str | None = Depends(require_api_key),
    x_user_session: str | None = Header(default=None),
) -> str | None:
    """Personal library when a session is present, otherwise the API-key owner.

    A presented session that is missing, unknown, or expired is a 401. It must
    not fall back to the shared API-key owner: that owner is every anonymous
    save on the public site.
    """
    token = _session_header(x_user_session)
    if token:
        account = auth_module.owner_for_session(token)
        if not account:
            raise HTTPException(status_code=401, detail="Sign in required.")
        return account
    return owner_id(key)


def require_signed_in_user(
    _key: str | None = Depends(require_api_key),
    x_user_session: str | None = Header(default=None),
) -> str:
    """History, rename, and publish belong to a real account, not the shared key."""
    account = auth_module.owner_for_session(_session_header(x_user_session))
    if not account:
        raise HTTPException(status_code=401, detail="Sign in required.")
    return account


@app.post("/v1/decks/save")
def save_deck(
    request: SaveDeckRequest,
    x_user_session: str | None = Header(default=None),
    key: str | None = Depends(require_api_key),
    owner: str | None = Depends(current_owner),
) -> dict:
    """Persist a deck and mint a share token.

    With no user session, the owner is a hash of the API key (or unset when
    API-key auth is off) — the anonymous flow. With a session, the deck goes
    into that person's library.
    """
    return deck_history.save(
        name=request.name,
        format_id=request.format,
        mainboard=[c.model_dump() for c in request.mainboard],
        sideboard=[c.model_dump() for c in request.sideboard],
        commander=request.commander,
        notes=request.notes,
        evaluation=request.evaluation,
        owner=owner,
        visibility=request.visibility,
        colors=list(request.colors),
        price_usd=request.price_usd,
        card_notes=[note.model_dump() for note in request.card_notes],
        mana_curve=[point.model_dump() for point in request.mana_curve],
        card_types=dict(request.card_types),
        key_cards=list(request.key_cards),
        secret_values=_extra_secrets(x_user_session, key),
    )


@app.get("/v1/decks/history")
def deck_history_list(
    limit: int = 50,
    owner: str = Depends(require_signed_in_user),
) -> dict:
    """The signed-in library only. Anonymous decks are not listed, so their ids stay put."""
    return {"decks": deck_history.history(owner=owner, limit=max(1, min(limit, 200)))}


@app.get("/v1/decks/public")
def list_public_decks(limit: int = 500, offset: int = 0) -> dict:
    """Indexable share tokens for the sitemap. Unlisted decks are omitted,
    and the payload is only the token plus a timestamp — no list, notes,
    owner, or account data."""
    return {"decks": deck_history.public_index(limit=limit, offset=offset)}


@app.get("/v1/decks/saved/{deck_id}")
def get_saved_deck(
    deck_id: str,
    owner: str | None = Depends(current_owner),
) -> dict:
    """Owner-only read by id. Public reads go through the share token."""
    deck = deck_history.get(deck_id, owner=owner)
    if deck is None:
        raise HTTPException(status_code=404, detail="saved deck not found")
    return deck


@app.patch("/v1/decks/saved/{deck_id}")
def update_saved_deck(
    deck_id: str,
    request: UpdateDeckRequest,
    x_user_session: str | None = Header(default=None),
    key: str | None = Depends(require_api_key),
    owner: str = Depends(require_signed_in_user),
) -> dict:
    """Rename a deck or change whether its page is indexable."""
    if request.name is None and request.visibility is None:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    updated = deck_history.update(
        deck_id,
        owner=owner,
        name=request.name,
        visibility=request.visibility,
        secret_values=_extra_secrets(x_user_session, key),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="saved deck not found")
    return updated


@app.get("/v1/decks/shared/{token}")
def get_shared_deck(token: str) -> dict:
    deck = deck_history.get_by_share_token(token)
    if deck is None:
        raise HTTPException(status_code=404, detail="shared deck not found")
    return deck


@app.delete("/v1/decks/saved/{deck_id}")
def delete_saved_deck(
    deck_id: str,
    owner: str | None = Depends(current_owner),
    x_deck_edit_secret: str | None = Header(default=None),
) -> dict:
    """User libraries delete with the session. Anonymous decks need the edit secret."""
    if not deck_history.delete(deck_id, owner=owner, edit_secret=x_deck_edit_secret):
        raise HTTPException(status_code=404, detail="saved deck not found")
    return {"deleted": deck_id}


@app.post("/v1/auth/magic-link")
def request_magic_link(
    request: MagicLinkRequest,
    req: Request,
    x_preauth: str | None = Header(default=None),
    _key: str | None = Depends(require_api_key),
) -> dict:
    """Email a one-time sign-in link. The response does not reveal whether
    the address already has an account. The link itself is only included
    when MTG_AUTH_DEBUG is set, and never when this process is production.

    ``X-Preauth`` is the cookie the web server set for this browser. The link
    will not sign anyone in without it. Budgets are stored in the database.
    """
    limited = "Too many sign-in requests. Wait a bit and try again."
    if not auth_module.auth_service.consume_ip(client_key(req)):
        raise HTTPException(status_code=429, detail=limited)
    email = normalize_email(request.email)
    if email is None:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if not valid_preauth(x_preauth):
        raise HTTPException(status_code=400, detail="Sign-in could not be started. Try again.")
    if not auth_module.auth_service.consume_email_send(email, client_key(req)):
        # Budgets are checked before a new link is stored, so a throttle
        # cannot delete a link that is still waiting to be confirmed.
        raise HTTPException(status_code=429, detail=limited)
    return auth_module.auth_service.request_magic_link(email, x_preauth or "")


@app.post("/v1/auth/verify")
def verify_magic_link(
    request: VerifyLinkRequest,
    _key: str | None = Depends(require_api_key),
) -> dict:
    result = auth_module.auth_service.verify(request.token, request.preauth, request.previous_session)
    if result == auth_module.PREAUTH_MISMATCH:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "preauth_mismatch",
                "message": (
                    "This sign-in link was requested on another device. "
                    "Request a new link from this browser."
                ),
            },
        )
    if not isinstance(result, dict):
        raise HTTPException(status_code=400, detail="That sign-in link is invalid or expired.")
    return result


@app.get("/v1/auth/me")
def auth_me(
    x_user_session: str | None = Header(default=None),
    _key: str | None = Depends(require_api_key),
) -> dict:
    user = auth_module.auth_service.user_for_session(x_user_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    return {"user": user}


@app.post("/v1/auth/logout")
def auth_logout(
    x_user_session: str | None = Header(default=None),
    _key: str | None = Depends(require_api_key),
) -> dict:
    auth_module.auth_service.revoke(x_user_session)
    return {"ok": True}


@app.delete("/v1/auth/me")
def delete_account(
    x_user_session: str | None = Header(default=None),
    _key: str | None = Depends(require_api_key),
) -> dict:
    """Delete the signed-in account and every deck in that library."""
    user = auth_module.auth_service.user_for_session(x_user_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    deck_history.delete_all_for_owner(f"user:{user['id']}")
    auth_module.auth_service.delete_user(user["id"])
    return {"deleted": True}


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
    client_ip = client_key(req)
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
    client_ip = client_key(req)
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
    dates = [a.metadata.last_seen for a in archetypes if a.metadata.last_seen]
    return MetaSummaryResponse(format=format, archetypes=archetypes, as_of=max(dates) if dates else None)


@app.get("/v1/cards", response_model=CardSearchResponse)
def card_search(query: str, format: FormatName | None = None, limit: int = 12) -> CardSearchResponse:
    return CardSearchResponse(cards=repository.search_cards(query=query, format_name=format, limit=max(1, min(limit, 50))))


@app.get("/v1/cards/{card_name}/similar")
def similar_cards(
    card_name: str,
    k: int = 10,
    format: FormatName | None = None,
    colors: str | None = None,
) -> dict:
    """Semantic-ish nearest neighbours for a card (pgvector when wired,
    deterministic lexical-feature cosine otherwise).

    With ``format`` / ``colors`` (comma-separated, e.g. ``U,R``) only cards
    legal in that format and inside those colors come back, which is what an
    "alternatives for this slot" suggestion needs."""
    if repository.get_card(card_name) is None:
        raise HTTPException(status_code=404, detail="Card not found")
    k = max(1, min(k, 50))
    allowed_colors = {c for c in (colors or "").split(",") if c and c != "C"} if colors is not None else None
    filtered = format is not None or allowed_colors is not None
    hits = card_retriever.similar_to(card_name, k=k * 6 if filtered else k)
    if filtered:
        kept = []
        for hit in hits:
            card = repository.get_card(hit.name)
            if card is None:
                continue
            if format is not None and card.legalities.get(format) not in {"legal", "restricted"}:
                continue
            if allowed_colors is not None and not set(card.color_identity or card.colors) <= allowed_colors:
                continue
            kept.append(hit)
        hits = kept[:k]
    return {
        "card": card_name,
        "mode": card_retriever.mode,
        "similar": [h.to_dict() for h in hits],
    }


# Registered last: the `:path` converter is greedy and would otherwise
# swallow more specific subpaths like `/v1/cards/{name}/similar`.
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


@app.get("/v1/commander/precons", response_model=PreconSearchResponse)
def search_precons(q: str = "", limit: int = 20) -> PreconSearchResponse:
    """Official Commander precons from the MTGJSON snapshot. ``q`` matches the
    deck name, a commander, or the set code."""
    from app.services.precon_upgrade import search_precons as _search

    return PreconSearchResponse(precons=_search(q, limit=max(1, min(limit, 50))))


@app.post("/v1/commander/precon-upgrade", response_model=PreconUpgradeResponse)
def precon_upgrade(
    request: PreconUpgradeRequest,
    req: Request,
    _key: str | None = Depends(require_api_key),
) -> PreconUpgradeResponse:
    """Ranked swaps that upgrade a Commander precon without going over a budget."""
    client_ip = client_key(req)
    if not deck_rate_limiter.is_allowed(f"precon-upgrade:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many upgrade requests. Please wait before trying again.")
    from app.services.precon_upgrade import PreconNotFound, upgrade_precon

    try:
        return upgrade_precon(request, repository=repository, validator=validator)
    except PreconNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        limit=max(1, min(limit, 100)),
    )
    return CommanderSearchResponse(commanders=commanders)


@app.get("/v1/commanders/{commander_name}", response_model=CommanderProfileResponse)
def commander_detail(commander_name: str) -> CommanderProfileResponse:
    commander = repository.get_commander_profile(commander_name)
    if not commander:
        raise HTTPException(status_code=404, detail="Commander not found")
    return CommanderProfileResponse(commander=commander)
