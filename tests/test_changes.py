from __future__ import annotations

from datetime import date

import pandas as pd

from src.database import calculate_changes


def test_status_to_update_is_modified() -> None:
    previous = pd.DataFrame(
        [
            {
                "record_key": "same-key",
                "full_code": "UA14120010010000123",
                "hromada_code_7": "1412001",
                "territory_name": "Тестова громада",
                "oblast": "Донецька область",
                "rayon": "Краматорський район",
                "category": "Території активних бойових дій",
                "status_from": date(2025, 1, 1),
                "status_to": None,
            }
        ]
    )
    current = previous.copy()
    current.loc[0, "status_to"] = date(2025, 2, 1)

    changes = calculate_changes(previous, current)
    assert len(changes) == 1
    assert changes[0]["change_type"] == "MODIFIED"
