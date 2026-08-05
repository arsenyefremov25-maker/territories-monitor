from __future__ import annotations

import hashlib
import re
from collections import deque
from datetime import date, datetime
from io import BytesIO
from typing import Iterator

import pandas as pd
from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from src.config import (
    CATEGORY_ACTIVE,
    CATEGORY_OCCUPIED,
    CATEGORY_POSSIBLE,
    FALLBACK_CATEGORY_BY_TABLE_INDEX,
)

OUTPUT_COLUMNS = [
    "record_key",
    "full_code",
    "hromada_code_7",
    "territory_name",
    "hromada_name",
    "settlement_name",
    "oblast",
    "rayon",
    "category",
    "systems_functioning",
    "status_from",
    "status_to",
]


def normalize_whitespace(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def clean_heading(value: object) -> str:
    cleaned = normalize_whitespace(value)
    cleaned = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", cleaned)
    return cleaned.strip(" .")


def normalize_date(value: object) -> date | None:
    cleaned = normalize_whitespace(value).strip(" .")
    if not cleaned or cleaned.lower() in {"none", "nan", "-", "—", "–"}:
        return None

    match = re.search(r"(\d{2})[.](\d{2})[.](\d{4})", cleaned)
    if match:
        day, month, year = match.groups()
        return datetime(int(year), int(month), int(day)).date()

    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", cleaned)
    if match:
        year, month, day = match.groups()
        return datetime(int(year), int(month), int(day)).date()

    return None


def normalize_code(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def is_territory_code(value: object) -> bool:
    code = normalize_code(value)
    return bool(re.fullmatch(r"UA\d{7,}", code))


def hromada_code_7(full_code: str) -> str | None:
    match = re.match(r"UA(\d{7})", full_code)
    return match.group(1) if match else None


def normalize_yes_no(value: object) -> bool | None:
    cleaned = normalize_whitespace(value).lower().strip(" .")
    if cleaned in {"так", "yes", "true", "1"}:
        return True
    if cleaned in {"ні", "нi", "no", "false", "0"}:
        return False
    return None


def is_oblast_row(value: object) -> bool:
    cleaned = clean_heading(value).lower()
    return (
        "область" in cleaned
        or "автономна республіка крим" in cleaned
        or cleaned in {"м. київ", "місто київ", "м. севастополь", "місто севастополь"}
    )


def is_rayon_row(value: object) -> bool:
    cleaned = clean_heading(value).lower()
    return "район" in cleaned and not is_territory_code(cleaned)


def normalize_administrative_name(value: object) -> str | None:
    cleaned = clean_heading(value)
    if not cleaned:
        return None
    if cleaned.isupper():
        return cleaned.title()
    return cleaned[0].upper() + cleaned[1:]


def normalize_category(value: object) -> str | None:
    lowered = normalize_whitespace(value).lower()
    if "тимчасово окупован" in lowered:
        return CATEGORY_OCCUPIED
    if "можливих бойових дій" in lowered:
        return CATEGORY_POSSIBLE
    if "активних бойових дій" in lowered:
        return CATEGORY_ACTIVE
    return None


def infer_category(context_text: str, table_index: int) -> str:
    category = normalize_category(context_text)
    if category:
        return category

    fallback = FALLBACK_CATEGORY_BY_TABLE_INDEX.get(table_index)
    if not fallback:
        raise ValueError(
            f"Не вдалося визначити категорію для таблиці {table_index}. "
            "Структура офіційного DOCX могла змінитися."
        )
    return fallback


def make_record_key(
    full_code: str,
    category: str,
    status_from: date | None,
    identity_hint: str = "",
) -> str:
    # status_to and systems_functioning intentionally do not participate: when
    # only these fields change, the event is classified as MODIFIED.
    # identity_hint contains the administrative path. It is needed because the
    # official source currently contains a repeated KATOTTG code for different
    # settlement labels.
    raw = "|".join(
        [
            full_code,
            normalize_whitespace(category).lower(),
            status_from.isoformat() if status_from else "",
            normalize_whitespace(identity_hint).lower(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def iter_block_items(document: DocumentObject) -> Iterator[Paragraph | Table]:
    parent_element = document.element.body
    for child in parent_element.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _table_preview(table: Table, max_rows: int = 5) -> str:
    parts: list[str] = []
    for row in table.rows[:max_rows]:
        parts.extend(normalize_whitespace(cell.text) for cell in row.cells)
    return " ".join(parts)


def _direct_nine_column_row(cells: list[str]) -> dict[str, object] | None:
    """Parse the consolidated nine-column layout used in the current DOCX."""
    if len(cells) < 9 or not is_territory_code(cells[4]):
        return None

    full_code = normalize_code(cells[4])
    category = normalize_category(cells[5])
    if not category:
        return None

    oblast = normalize_administrative_name(cells[0])
    rayon = normalize_administrative_name(cells[1])
    hromada_name = clean_heading(cells[2]) or None
    settlement_name = clean_heading(cells[3]) or None
    territory_name = settlement_name or hromada_name or rayon or oblast
    if not territory_name:
        return None

    status_from = normalize_date(cells[6])
    status_to = normalize_date(cells[7])
    identity_hint = "|".join(
        value or "" for value in (oblast, rayon, hromada_name, settlement_name)
    )

    return {
        "record_key": make_record_key(
            full_code,
            category,
            status_from,
            identity_hint=identity_hint,
        ),
        "full_code": full_code,
        "hromada_code_7": hromada_code_7(full_code),
        "territory_name": territory_name,
        "hromada_name": hromada_name,
        "settlement_name": settlement_name,
        "oblast": oblast,
        "rayon": rayon,
        "category": category,
        "systems_functioning": normalize_yes_no(cells[8]),
        "status_from": status_from,
        "status_to": status_to,
    }


def extract_rows(docx_content: bytes) -> pd.DataFrame:
    document = Document(BytesIO(docx_content))
    if not document.tables:
        raise ValueError("У DOCX не знайдено таблиць.")

    rows: list[dict[str, object]] = []
    recent_paragraphs: deque[str] = deque(maxlen=8)
    table_index = 0

    for block in iter_block_items(document):
        if isinstance(block, Paragraph):
            text = normalize_whitespace(block.text)
            if text:
                recent_paragraphs.append(text)
            continue

        table_index += 1
        context = " ".join([*recent_paragraphs, _table_preview(block)])
        legacy_category: str | None = None
        current_oblast: str | None = None
        current_rayon: str | None = None

        for table_row in block.rows:
            cells = [normalize_whitespace(cell.text) for cell in table_row.cells]
            if not cells or all(not cell for cell in cells):
                continue

            direct_row = _direct_nine_column_row(cells)
            if direct_row:
                rows.append(direct_row)
                continue

            # Backward compatibility with the former four-column layout.
            first = cells[0]
            second = cells[1] if len(cells) > 1 else ""
            heading_candidate = first or second

            if is_oblast_row(heading_candidate) and not is_territory_code(heading_candidate):
                current_oblast = normalize_administrative_name(heading_candidate)
                current_rayon = None
                continue

            if is_rayon_row(heading_candidate) and not is_territory_code(heading_candidate):
                current_rayon = normalize_administrative_name(heading_candidate)
                continue

            if len(cells) < 4 or not is_territory_code(first):
                continue

            if legacy_category is None:
                legacy_category = infer_category(context, table_index)

            full_code = normalize_code(first)
            territory_name = clean_heading(second)
            if not territory_name:
                continue

            status_from = normalize_date(cells[2])
            status_to = normalize_date(cells[3])
            identity_hint = "|".join(
                value or "" for value in (current_oblast, current_rayon, territory_name)
            )
            rows.append(
                {
                    "record_key": make_record_key(
                        full_code,
                        legacy_category,
                        status_from,
                        identity_hint=identity_hint,
                    ),
                    "full_code": full_code,
                    "hromada_code_7": hromada_code_7(full_code),
                    "territory_name": territory_name,
                    "hromada_name": territory_name,
                    "settlement_name": None,
                    "oblast": current_oblast,
                    "rayon": current_rayon,
                    "category": legacy_category,
                    "systems_functioning": None,
                    "status_from": status_from,
                    "status_to": status_to,
                }
            )

    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if frame.empty:
        raise ValueError(
            "Парсер не отримав жодного запису. Запис у базу заблоковано."
        )

    return frame.sort_values(
        [
            "oblast",
            "rayon",
            "hromada_name",
            "territory_name",
            "category",
            "status_from",
        ],
        na_position="last",
    ).reset_index(drop=True)
