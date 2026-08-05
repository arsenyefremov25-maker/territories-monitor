from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from src.config import load_settings
from src.database import TerritoryRepository, create_database_engine
from src.document_source import download_current_document, load_local_document
from src.parser import extract_rows
from src.validation import validate_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Завантаження та збереження актуального переліку територій."
    )
    parser.add_argument("--file", help="Локальний DOCX замість завантаження з сайту.")
    parser.add_argument(
        "--edition-date",
        help="Дата редакції локального DOCX у форматі YYYY-MM-DD.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Розібрати та перевірити файл без запису в базу.",
    )
    parser.add_argument(
        "--output",
        default="artifacts/territories_preview.csv",
        help="CSV для результату dry-run.",
    )
    parser.add_argument(
        "--allow-large-drop",
        action="store_true",
        help="Дозволити значне скорочення кількості записів після ручної перевірки.",
    )
    return parser.parse_args()


def write_github_summary(lines: list[str]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as summary:
        summary.write("\n".join(lines) + "\n")


def main() -> int:
    args = parse_args()
    settings = load_settings(require_database=not args.dry_run)

    edition_date = None
    if args.edition_date:
        edition_date = datetime.strptime(args.edition_date, "%Y-%m-%d").date()

    print("1/4 Отримання документа...")
    source = (
        load_local_document(args.file, edition_date=edition_date)
        if args.file
        else download_current_document(timeout=settings.request_timeout_seconds)
    )
    print(f"SHA-256: {source.file_hash}")
    print(f"Джерело: {source.source_file_url}")
    print(f"Дата редакції: {source.edition_date or 'не визначена автоматично'}")

    repository = None
    previous_row_count = None
    if settings.database_url:
        engine = create_database_engine(settings.database_url)
        repository = TerritoryRepository(engine)
        existing = repository.find_document_by_hash(source.file_hash)
        if existing and not args.dry_run:
            print("Цю редакцію вже завантажено. Оновлення не потрібне.")
            write_github_summary(
                [
                    "## Оновлення переліку територій",
                    "Документ не змінився; запис у базу пропущено.",
                    f"- SHA-256: `{source.file_hash}`",
                ]
            )
            return 0
        latest = repository.latest_document()
        previous_row_count = int(latest["row_count"]) if latest else None

    print("2/4 Розбір DOCX...")
    frame = extract_rows(source.content)
    print(f"Отримано записів: {len(frame)}")

    print("3/4 Перевірка якості...")
    report = validate_snapshot(
        frame,
        min_rows=settings.min_rows,
        previous_row_count=previous_row_count,
        min_previous_ratio=settings.min_previous_ratio,
        allow_large_drop=args.allow_large_drop,
    )
    print(json.dumps(report.metrics, ensure_ascii=False, indent=2, default=str))
    for warning in report.warnings:
        print(f"WARNING: {warning}")
    report.raise_for_errors()

    if args.dry_run:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"Dry-run завершено. CSV: {output_path}")
        return 0

    if repository is None:
        raise RuntimeError("Репозиторій бази не ініціалізовано.")

    print("4/4 Транзакційний запис у базу...")
    result = repository.save_snapshot(source, frame)
    print(
        f"Готово: document_id={result.document_id}, rows={result.row_count}, "
        f"changes={result.changes_count}, skipped={result.skipped}"
    )
    write_github_summary(
        [
            "## Оновлення переліку територій",
            f"- Нова редакція: **{'ні' if result.skipped else 'так'}**",
            f"- Записів: **{result.row_count}**",
            f"- Зафіксованих змін: **{result.changes_count}**",
            f"- Document ID: `{result.document_id}`",
            f"- SHA-256: `{source.file_hash}`",
        ]
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        write_github_summary(
            [
                "## Оновлення переліку територій — помилка",
                f"```text\n{exc}\n```",
            ]
        )
        raise
