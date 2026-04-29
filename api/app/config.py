import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
CARD_CACHE_PATH = DATA_DIR / "cards.sample.json"
ARCHETYPE_PATH = DATA_DIR / "archetypes.sample.json"
TOURNAMENT_DECK_PATH = DATA_DIR / "tournament_decks.sample.json"
DEFAULT_SQLITE_PATH = ROOT_DIR / "var" / "mtg_deck_builder.db"
DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")
SCRYFALL_BULK_URL = os.getenv("SCRYFALL_BULK_DATA_URL", "https://api.scryfall.com/bulk-data")
SCRYFALL_USER_AGENT = os.getenv("SCRYFALL_USER_AGENT", "mtg-deck-builder/0.1")
_raw_cors = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
CORS_ORIGINS: list[str] = [o.strip() for o in _raw_cors.split(",") if o.strip()]
