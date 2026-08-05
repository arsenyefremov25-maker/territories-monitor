from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.config import EXPECTED_CATEGORIES
from src.parser import OUTPUT_COLUMNS


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, object] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            details = "\n- ".join(self.errors)
            raise ValueError(f"Перевірка даних не пройдена:\n- {details}")


def validate_snapshot(
    frame: pd.DataFrame,
    *,
    min_rows: int = 100,
    previous_row_count: int | None = None,
    min_previous_ratio: float = 0.65,
    allow_large_drop: bool = False,
) -> ValidationReport:
    report = ValidationReport()
    report.metrics["row_count"] = len(frame)

    missing_columns = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    if missing_columns:
        report.errors.append("Відсутні колонки: " + ", ".join(missing_columns))
        return report

    if len(frame) < min_rows:
        report.errors.append(
            f"Отримано лише {len(frame)} записів; мінімальний поріг — {min_rows}."
        )

    duplicated = int(frame["record_key"].duplicated().sum())
    report.metrics["duplicate_record_keys"] = duplicated
    if duplicated:
        report.errors.append(f"Виявлено {duplicated} дублікатів record_key.")

    valid_code_mask = frame["full_code"].astype(str).str.fullmatch(r"UA\d{7,}", na=False)
    invalid_codes = int((~valid_code_mask).sum())
    report.metrics["invalid_codes"] = invalid_codes
    if invalid_codes:
        report.errors.append(f"Виявлено {invalid_codes} некоректних кодів територій.")

    required_nulls = {
        column: int(frame[column].isna().sum())
        for column in ("record_key", "full_code", "territory_name", "category")
    }
    report.metrics["required_nulls"] = required_nulls
    for column, count in required_nulls.items():
        if count:
            report.errors.append(f"Колонка {column} містить {count} порожніх значень.")

    missing_oblast_share = float(frame["oblast"].isna().mean())
    report.metrics["missing_oblast_share"] = round(missing_oblast_share, 4)
    if missing_oblast_share > 0.05:
        report.errors.append(
            f"Область не визначена для {missing_oblast_share:.1%} записів."
        )
    elif missing_oblast_share > 0:
        report.warnings.append(
            f"Область не визначена для {missing_oblast_share:.1%} записів."
        )

    categories = set(frame["category"].dropna().astype(str))
    report.metrics["categories"] = sorted(categories)
    if len(categories) < 3:
        report.errors.append(
            f"Виявлено лише {len(categories)} категорії; очікується щонайменше 3."
        )

    unexpected_categories = categories - EXPECTED_CATEGORIES
    if unexpected_categories:
        report.errors.append(
            "Невідомі категорії: " + ", ".join(sorted(unexpected_categories))
        )

    invalid_date_order = frame[
        frame["status_from"].notna()
        & frame["status_to"].notna()
        & (frame["status_to"] < frame["status_from"])
    ]
    report.metrics["invalid_date_order"] = len(invalid_date_order)
    if not invalid_date_order.empty:
        report.errors.append(
            f"Для {len(invalid_date_order)} записів кінцева дата раніше початкової."
        )

    if previous_row_count:
        ratio = len(frame) / previous_row_count
        report.metrics["previous_row_count"] = previous_row_count
        report.metrics["previous_ratio"] = round(ratio, 4)
        if ratio < min_previous_ratio:
            message = (
                f"Кількість записів скоротилася з {previous_row_count} до {len(frame)} "
                f"({ratio:.1%} від попереднього знімка)."
            )
            if allow_large_drop:
                report.warnings.append(message + " Перевірку примусово дозволено.")
            else:
                report.errors.append(message)

    return report
