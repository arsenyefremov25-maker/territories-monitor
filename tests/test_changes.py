from __future__ import annotations

from datetime import date

import pandas as pd

from src.database import calculate_changes


def base_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_key": "same-key",
                "full_code": "UA14120010010000123",
                "hromada_code_7": "1412001",
                "territory_name": "с. Тестове",
                "hromada_name": "Тестова територіальна громада",
                "settlement_name": "с. Тестове",
                "oblast": "Донецька",
                "rayon": "Краматорський",
                "category": "Території активних бойових дій",
                "systems_functioning": False,
                "status_from": date(2025, 1, 1),
                "status_to": None,
            }
        ]
    )


def test_status_to_update_is_modified() -> None:
    previous = base_frame()
    current = previous.copy()
    current.loc[0, "status_to"] = date(2025, 2, 1)
    changes = calculate_changes(previous, current)
    assert len(changes) == 1
    assert changes[0]["change_type"] == "MODIFIED"


def test_system_flag_update_is_modified() -> None:
    previous = base_frame()
    current = previous.copy()
    current.loc[0, "systems_functioning"] = True
    changes = calculate_changes(previous, current)
    assert len(changes) == 1
    assert changes[0]["change_type"] == "MODIFIED"
