from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    CardDetailResponse,
    DeckResponse,
    ExportDeckRequest,
    FormatName,
    GenerateDeckRequest,
    MetaSummaryResponse,
    RefineDeckRequest,
    ValidateDeckRequest,
    ValidationResult,
)
from app.services.card_repository import CardRepository
from app.services.deck_generator import DeckGenerator
from app.services.deck_validator import DeckValidator


repository = CardRepository()
validator = DeckValidator(repository)
generator = DeckGenerator(repository, validator)

app = FastAPI(title="MTG Deck Builder API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/decks/generate", response_model=DeckResponse)
def generate_deck(request: GenerateDeckRequest) -> DeckResponse:
    return generator.generate(request)


@app.post("/v1/decks/refine", response_model=DeckResponse)
def refine_deck(request: RefineDeckRequest) -> DeckResponse:
    return generator.refine(request.deck, request.refinement_prompt)


@app.post("/v1/decks/validate", response_model=ValidationResult)
def validate_deck(request: ValidateDeckRequest) -> ValidationResult:
    return validator.validate(request)


@app.post("/v1/decks/export")
def export_deck(request: ExportDeckRequest) -> dict[str, str]:
    return {"target": request.target, "content": generator.export(request.deck, request.target)}


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
