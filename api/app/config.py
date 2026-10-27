import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]

load_dotenv(ROOT_DIR / ".env", override=False)
APP_DIR = Path(__file__).resolve().parent
# Versioned LLM system prompts. Resolved from the repo root so the API can be
# served from api/ (as documented) and still find them.
SKILLS_DIR = ROOT_DIR / ".claude" / "skills"
DATA_DIR = APP_DIR / "data"
CARD_CACHE_PATH = DATA_DIR / "cards.sample.json"
ARCHETYPE_PATH = DATA_DIR / "archetypes.sample.json"
# Prefer the curated/synthesized corpus when present (176 decks across 100+
# archetypes). Falls back to the 11-deck sample if the curated file hasn't
# been generated yet. Run `python -m app.scripts.synthesize_tournament_corpus`
# to (re)generate the curated file from BUILTIN_ARCHETYPES.
_CURATED_TOURNAMENT_PATH = DATA_DIR / "tournament_decks.curated.json"
_SAMPLE_TOURNAMENT_PATH = DATA_DIR / "tournament_decks.sample.json"
TOURNAMENT_DECK_PATH = _CURATED_TOURNAMENT_PATH if _CURATED_TOURNAMENT_PATH.exists() else _SAMPLE_TOURNAMENT_PATH
DEFAULT_SQLITE_PATH = ROOT_DIR / "var" / "mtg_deck_builder.db"
DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")
SCRYFALL_BULK_URL = os.getenv("SCRYFALL_BULK_DATA_URL", "https://api.scryfall.com/bulk-data")
SCRYFALL_USER_AGENT = os.getenv("SCRYFALL_USER_AGENT", "mtg-deck-builder/0.1")
_raw_cors = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
CORS_ORIGINS: list[str] = [o.strip() for o in _raw_cors.split(",") if o.strip()]
# TCGplayer affiliate deep-link prefix from Impact (impact.com), e.g.
# "https://tcgplayer.pxf.io/c/123456/789012/21018". When set, every
# TCGplayer purchase link served by the API is wrapped for attribution.
TCGPLAYER_AFFILIATE_URL = os.getenv("TCGPLAYER_AFFILIATE_URL", "").strip()
# LLM request timeouts (seconds). The SDK defaults (600 s, 2 retries) would let a
# provider stall pin a request thread for half an hour; every caller already has
# a deterministic fallback, so fail fast instead. Interactive calls (generate,
# refine, chat, analysis) use the short timeout; background jobs (critic loop,
# coach prose) produce longer outputs and get the long one.
LLM_TIMEOUT_SECONDS = float(os.getenv("MTG_LLM_TIMEOUT_SECONDS", "30"))
LLM_BACKGROUND_TIMEOUT_SECONDS = float(os.getenv("MTG_LLM_BACKGROUND_TIMEOUT_SECONDS", "120"))
LLM_MAX_RETRIES = int(os.getenv("MTG_LLM_MAX_RETRIES", "1"))


def env_or_default(name: str, default: str) -> str:
    """Env override, with a blank value treated as unset."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    return value or default


# Offline deck-quality judge (qa/run_eval.py). gpt-4.1-mini shuts down
# 2027-01-14; OpenAI's replacement is gpt-6-luna. The previous default,
# gpt-5-mini, shuts down 2026-12-11 (replacement gpt-5.6-terra, about 20x
# the token price). Luna is the cheap high-volume model and accepts the
# same low reasoning effort the runner already sends, so the provider
# spend cap stays in range. Override with OPENAI_EVAL_MODEL.
DEFAULT_OPENAI_EVAL_MODEL = "gpt-6-luna"
OPENAI_EVAL_MODEL = env_or_default("OPENAI_EVAL_MODEL", DEFAULT_OPENAI_EVAL_MODEL)


def responses_reasoning_controls(model: str) -> bool:
    """GPT-5 and GPT-6 accept reasoning.effort and text.verbosity on Responses.

    Older chat models reject those fields, so an env override to one of them
    must not send them.
    """
    name = model.strip().lower()
    return name.startswith(("gpt-5", "gpt-6"))
# Card/legality data older than this many days (by newest card release date)
# is reported as stale: sets and ban updates land every few weeks.
DATA_STALE_DAYS = int(os.getenv("MTG_DATA_STALE_DAYS", "60"))
