from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from src.config import BASE_DOCUMENT_DATE, BASE_DOCUMENT_NUMBER, SOURCE_NAME
from src.document_source import SourceDocument


def normalize_database_url(database_url: str) -> str:
    value = database_url.strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://") :]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://") :]
    return value


def create_database_engine(database_url: str) -> Engine:
    return create_engine(
        normalize_database_url(database_url),
        pool_pre_ping=True,
        pool_recycle=300,
    )


def apply_schema(engine: Engine, schema_path: str | Path) -> None:
    sql = Path(schema_path).read_text(encoding="utf-8")
    raw_connection = engine.raw_connection()
    try:
        with raw_connection.cursor() as cursor:
            cursor.execute(sql)
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()


def _json_safe(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    return value


def _record_for_json(record: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_safe(value) for key, value in record.items()}


def calculate_changes(
    previous: pd.DataFrame,
    current: pd.DataFrame,
) -> list[dict[str, Any]]:
    if previous.empty:
        return [
            {
                "change_type": "ADDED",
                "record_key": row["record_key"],
                "before_data": None,
                "after_data": _record_for_json(row.to_dict()),
            }
            for _, row in current.iterrows()
        ]

    previous_by_key = previous.set_index("record_key", drop=False).to_dict("index")
    current_by_key = current.set_index("record_key", drop=False).to_dict("index")

    previous_keys = set(previous_by_key)
    current_keys = set(current_by_key)
    changes: list[dict[str, Any]] = []

    for key in sorted(current_keys - previous_keys):
        changes.append(
            {
                "change_type": "ADDED",
                "record_key": key,
                "before_data": None,
                "after_data": _record_for_json(current_by_key[key]),
            }
        )

    for key in sorted(previous_keys - current_keys):
        changes.append(
            {
                "change_type": "REMOVED",
                "record_key": key,
                "before_data": _record_for_json(previous_by_key[key]),
                "after_data": None,
            }
        )

    comparison_fields = (
        "full_code",
        "hromada_code_7",
        "territory_name",
        "oblast",
        "rayon",
        "category",
        "status_from",
        "status_to",
    )
    for key in sorted(previous_keys & current_keys):
        before = _record_for_json(previous_by_key[key])
        after = _record_for_json(current_by_key[key])
        if any(before.get(field) != after.get(field) for field in comparison_fields):
            changes.append(
                {
                    "change_type": "MODIFIED",
                    "record_key": key,
                    "before_data": before,
                    "after_data": after,
                }
            )

    return changes


@dataclass(frozen=True)
class SaveResult:
    document_id: int
    previous_document_id: int | None
    row_count: int
    changes_count: int
    skipped: bool = False


class TerritoryRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def find_document_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        query = text(
            """
            select id, file_hash, row_count, loaded_at
            from documents
            where file_hash = :file_hash
            limit 1
            """
        )
        with self.engine.connect() as connection:
            row = connection.execute(query, {"file_hash": file_hash}).mappings().first()
        return dict(row) if row else None

    def latest_document(self) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("select * from latest_document limit 1")
            ).mappings().first()
        return dict(row) if row else None

    def load_snapshot(self, document_id: int | None) -> pd.DataFrame:
        if not document_id:
            return pd.DataFrame()
        query = text(
            """
            select
                record_key, full_code, hromada_code_7, territory_name,
                oblast, rayon, category, status_from, status_to
            from territory_status_history
            where source_document_id = :document_id
            order by territory_name, category, status_from
            """
        )
        return pd.read_sql(query, self.engine, params={"document_id": document_id})

    def save_snapshot(
        self,
        source: SourceDocument,
        frame: pd.DataFrame,
    ) -> SaveResult:
        existing = self.find_document_by_hash(source.file_hash)
        if existing:
            return SaveResult(
                document_id=int(existing["id"]),
                previous_document_id=None,
                row_count=int(existing["row_count"]),
                changes_count=0,
                skipped=True,
            )

        latest = self.latest_document()
        previous_document_id = int(latest["id"]) if latest else None
        previous = self.load_snapshot(previous_document_id)
        changes = calculate_changes(previous, frame)

        territory_insert = text(
            """
            insert into territory_status_history (
                source_document_id, record_key, full_code, hromada_code_7,
                territory_name, oblast, rayon, category, status_from, status_to
            ) values (
                :source_document_id, :record_key, :full_code, :hromada_code_7,
                :territory_name, :oblast, :rayon, :category, :status_from, :status_to
            )
            """
        )
        change_insert = text(
            """
            insert into territory_changes (
                source_document_id, previous_document_id, change_type,
                record_key, before_data, after_data
            ) values (
                :source_document_id, :previous_document_id, :change_type,
                :record_key, cast(:before_data as jsonb), cast(:after_data as jsonb)
            )
            """
        )

        with self.engine.begin() as connection:
            duplicate = connection.execute(
                text("select id from documents where file_hash = :file_hash"),
                {"file_hash": source.file_hash},
            ).scalar_one_or_none()
            if duplicate:
                return SaveResult(
                    document_id=int(duplicate),
                    previous_document_id=previous_document_id,
                    row_count=len(frame),
                    changes_count=0,
                    skipped=True,
                )

            document_id = int(
                connection.execute(
                    text(
                        """
                        insert into documents (
                            source_name, source_page_url, source_file_url,
                            base_document_number, base_document_date,
                            edition_date, file_hash, row_count
                        ) values (
                            :source_name, :source_page_url, :source_file_url,
                            :base_document_number, :base_document_date,
                            :edition_date, :file_hash, :row_count
                        )
                        returning id
                        """
                    ),
                    {
                        "source_name": SOURCE_NAME,
                        "source_page_url": source.source_page_url,
                        "source_file_url": source.source_file_url,
                        "base_document_number": BASE_DOCUMENT_NUMBER,
                        "base_document_date": BASE_DOCUMENT_DATE,
                        "edition_date": source.edition_date,
                        "file_hash": source.file_hash,
                        "row_count": len(frame),
                    },
                ).scalar_one()
            )

            records = []
            for row in frame.to_dict("records"):
                prepared = {key: _json_safe(value) for key, value in row.items()}
                prepared["source_document_id"] = document_id
                records.append(prepared)
            connection.execute(territory_insert, records)

            if changes:
                change_records = []
                for change in changes:
                    change_records.append(
                        {
                            "source_document_id": document_id,
                            "previous_document_id": previous_document_id,
                            "change_type": change["change_type"],
                            "record_key": change["record_key"],
                            "before_data": (
                                json.dumps(change["before_data"], ensure_ascii=False)
                                if change["before_data"] is not None
                                else None
                            ),
                            "after_data": (
                                json.dumps(change["after_data"], ensure_ascii=False)
                                if change["after_data"] is not None
                                else None
                            ),
                        }
                    )
                connection.execute(change_insert, change_records)

        return SaveResult(
            document_id=document_id,
            previous_document_id=previous_document_id,
            row_count=len(frame),
            changes_count=len(changes),
            skipped=False,
        )
