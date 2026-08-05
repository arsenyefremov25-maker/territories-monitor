from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine, text


def load_latest_document(engine: Engine) -> pd.DataFrame:
    return pd.read_sql(text("select * from latest_document limit 1"), engine)


def load_current_territories(engine: Engine) -> pd.DataFrame:
    frame = pd.read_sql(
        text(
            """
            select
                source_document_id,
                full_code,
                hromada_code_7,
                territory_name,
                oblast,
                rayon,
                category,
                status_from,
                status_to,
                loaded_at
            from current_territory_status
            order by territory_name, category, status_from
            """
        ),
        engine,
    )
    for column in ("status_from", "status_to", "loaded_at"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def load_latest_changes(engine: Engine) -> pd.DataFrame:
    frame = pd.read_sql(
        text(
            """
            select
                c.change_type,
                c.record_key,
                c.before_data,
                c.after_data,
                c.created_at,
                d.edition_date,
                d.loaded_at
            from territory_changes c
            join latest_document d on d.id = c.source_document_id
            order by c.change_type, c.created_at, c.record_key
            """
        ),
        engine,
    )
    for column in ("created_at", "edition_date", "loaded_at"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def load_document_history(engine: Engine) -> pd.DataFrame:
    frame = pd.read_sql(
        text(
            """
            select
                id,
                base_document_number,
                base_document_date,
                edition_date,
                row_count,
                loaded_at,
                source_page_url,
                source_file_url
            from documents
            order by loaded_at desc
            """
        ),
        engine,
    )
    for column in ("base_document_date", "edition_date", "loaded_at"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame
