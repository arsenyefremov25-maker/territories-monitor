from __future__ import annotations

from pathlib import Path

from src.config import load_settings
from src.database import apply_schema, create_database_engine


def main() -> None:
    settings = load_settings(require_database=True)
    assert settings.database_url is not None
    engine = create_database_engine(settings.database_url)
    schema_path = Path(__file__).parent / "sql" / "schema.sql"
    apply_schema(engine, schema_path)
    print("Схему бази даних успішно створено або оновлено.")


if __name__ == "__main__":
    main()
