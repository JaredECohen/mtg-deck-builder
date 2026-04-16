from __future__ import annotations

from app.db import get_engine
from app.db_models import Base


def create_schema() -> None:
    Base.metadata.create_all(bind=get_engine())
