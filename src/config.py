from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date


SOURCE_NAME = "Верховна Рада України / zakon.rada.gov.ua"
SOURCE_PAGE_URL = "https://zakon.rada.gov.ua/laws/show/z0380-25"
SOURCE_PRINT_URL = "https://zakon.rada.gov.ua/laws/show/z0380-25/print"
BASE_DOCUMENT_NUMBER = "376"
BASE_DOCUMENT_DATE = date(2025, 2, 28)

CATEGORY_POSSIBLE = "Території можливих бойових дій"
CATEGORY_ACTIVE = "Території активних бойових дій"
CATEGORY_ACTIVE_DIGITAL = (
    "Території активних бойових дій, на яких функціонують "
    "державні електронні інформаційні ресурси"
)
CATEGORY_OCCUPIED = "Тимчасово окуповані території"

EXPECTED_CATEGORIES = {
    CATEGORY_POSSIBLE,
    CATEGORY_ACTIVE,
    CATEGORY_ACTIVE_DIGITAL,
    CATEGORY_OCCUPIED,
}

# The official DOCX has historically contained five data tables. The final two
# may both belong to the temporarily occupied territories section.
FALLBACK_CATEGORY_BY_TABLE_INDEX = {
    1: CATEGORY_POSSIBLE,
    2: CATEGORY_ACTIVE,
    3: CATEGORY_ACTIVE_DIGITAL,
    4: CATEGORY_OCCUPIED,
    5: CATEGORY_OCCUPIED,
}


@dataclass(frozen=True)
class RuntimeSettings:
    database_url: str | None
    min_rows: int = 100
    min_previous_ratio: float = 0.65
    request_timeout_seconds: int = 60


def load_settings(require_database: bool = False) -> RuntimeSettings:
    database_url = os.getenv("DATABASE_URL", "").strip() or None
    if require_database and not database_url:
        raise RuntimeError(
            "Не задано DATABASE_URL. Додайте його до змінних середовища або GitHub Actions Secrets."
        )

    return RuntimeSettings(
        database_url=database_url,
        min_rows=int(os.getenv("MIN_EXPECTED_ROWS", "100")),
        min_previous_ratio=float(os.getenv("MIN_PREVIOUS_ROW_RATIO", "0.65")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "60")),
    )
