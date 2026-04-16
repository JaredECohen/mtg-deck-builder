import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
CARD_CACHE_PATH = DATA_DIR / "cards.sample.json"
ARCHETYPE_PATH = DATA_DIR / "archetypes.sample.json"
TOURNAMENT_DECK_PATH = DATA_DIR / "tournament_decks.sample.json"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/mtg_deck_builder")
SCRYFALL_BULK_URL = os.getenv("SCRYFALL_BULK_DATA_URL", "https://api.scryfall.com/bulk-data")
SCRYFALL_USER_AGENT = os.getenv("SCRYFALL_USER_AGENT", "mtg-deck-builder/0.1")
