from __future__ import annotations

import pandas as pd

from src.config import CATEGORY_ACTIVE, CATEGORY_OCCUPIED, CATEGORY_POSSIBLE
from src.parser import make_record_key
from src.validation import validate_snapshot


def valid_frame() -> pd.DataFrame:
    categories = [CATEGORY_POSSIBLE, CATEGORY_ACTIVE, CATEGORY_OCCUPIED]
    rows = []
    for index, category in enumerate(categories, start=1):
        full_code = f"UA{index:07d}0010000123"
        territory_name = f"с. Тестове {index}"
        rows.append(
            {
                "record_key": make_record_key(
                    full_code,
                    category,
                    None,
                    identity_hint=f"Донецька|Краматорський|{territory_name}",
                ),
                "full_code": full_code,
                "hromada_code_7": f"{index:07d}",
                "territory_name": territory_name,
                "hromada_name": f"Громада {index}",
                "settlement_name": territory_name,
                "oblast": "Донецька",
                "rayon": "Краматорський",
                "category": category,
                "systems_functioning": True,
                "status_from": pd.Timestamp("2025-01-01").date(),
                "status_to": None,
            }
        )
    return pd.DataFrame(rows)


def test_valid_snapshot() -> None:
    report = validate_snapshot(valid_frame(), min_rows=1)
    assert report.is_valid


def test_large_drop_is_blocked() -> None:
    report = validate_snapshot(
        valid_frame(),
        min_rows=1,
        previous_row_count=100,
        min_previous_ratio=0.65,
    )
    assert not report.is_valid
    assert any("скоротилася" in message for message in report.errors)
