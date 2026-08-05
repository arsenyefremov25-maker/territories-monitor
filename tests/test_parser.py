from __future__ import annotations

from io import BytesIO

from docx import Document

from src.config import (
    CATEGORY_ACTIVE,
    CATEGORY_ACTIVE_DIGITAL,
    CATEGORY_OCCUPIED,
    CATEGORY_POSSIBLE,
)
from src.parser import extract_rows, make_record_key, normalize_date


def build_test_docx() -> bytes:
    document = Document()
    sections = [
        ("1. Території можливих бойових дій", "UA14120010010000123", "Перша громада"),
        ("2. Території активних бойових дій", "UA14120020010000123", "Друга громада"),
        (
            "3. Території активних бойових дій, на яких функціонують державні електронні інформаційні ресурси",
            "UA14120030010000123",
            "Третя громада",
        ),
        ("4. Тимчасово окуповані території", "UA14120040010000123", "Четверта громада"),
        ("Продовження тимчасово окупованих територій", "UA14120050010000123", "П'ята громада"),
    ]

    for heading, code, name in sections:
        document.add_paragraph(heading)
        table = document.add_table(rows=4, cols=4)
        table.rows[0].cells[0].text = "ДОНЕЦЬКА ОБЛАСТЬ"
        table.rows[1].cells[0].text = "Краматорський район"
        table.rows[2].cells[0].text = "Код"
        table.rows[2].cells[1].text = "Найменування"
        table.rows[2].cells[2].text = "Дата початку"
        table.rows[2].cells[3].text = "Дата завершення"
        table.rows[3].cells[0].text = code
        table.rows[3].cells[1].text = name
        table.rows[3].cells[2].text = "01.01.2025"
        table.rows[3].cells[3].text = ""

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_extract_rows_detects_all_categories() -> None:
    frame = extract_rows(build_test_docx())
    assert len(frame) == 5
    assert set(frame["category"]) == {
        CATEGORY_POSSIBLE,
        CATEGORY_ACTIVE,
        CATEGORY_ACTIVE_DIGITAL,
        CATEGORY_OCCUPIED,
    }
    assert frame["oblast"].notna().all()
    assert frame["rayon"].notna().all()


def test_record_key_does_not_depend_on_end_date() -> None:
    start = normalize_date("01.01.2025")
    first = make_record_key("UA14120010010000123", CATEGORY_ACTIVE, start)
    second = make_record_key("UA14120010010000123", CATEGORY_ACTIVE, start)
    assert first == second
