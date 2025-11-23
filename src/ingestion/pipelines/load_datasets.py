"""ETL pipeline that ingests CSV datasets into a SQLite database.

The script scans the datasets directory, reads each CSV, normalizes the
column/table identifiers, and loads the records into SQLite. Metadata about
each ingestion (source file, columns, row counts) is recorded in the
`data_sources` table for traceability.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Sequence, Union
import unicodedata

BATCH_SIZE = 500


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load CSV files from a directory into a SQLite database."
    )
    parser.add_argument(
        "--datasets",
        type=Path,
        default=Path("datasets"),
        help="Directory containing CSV datasets (default: ./datasets)",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/processed/accessibility_ai.db"),
        help="Path to the SQLite database file (default: ./data/processed/accessibility_ai.db)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed progress information.",
    )
    return parser.parse_args()


def ensure_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def normalize_identifier(name: str) -> str:
    """Convert column or table names to SQLite-friendly identifiers."""
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.strip().lower()
    normalized = re.sub(r"[^0-9a-z]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = "field"
    if normalized[0].isdigit():
        normalized = f"_{normalized}"
    return normalized


def coerce_value(value: Union[str, None]) -> Union[str, int, float, None]:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed or trimmed.lower() in {"na", "n/a", "null", "none"}:
        return None
    if re.fullmatch(r"-?\d+", trimmed):
        try:
            return int(trimmed)
        except ValueError:
            return trimmed
    if re.fullmatch(r"-?\d+\.\d+", trimmed):
        try:
            return float(trimmed)
        except ValueError:
            return trimmed
    return trimmed


def gather_csv_files(datasets_dir: Path) -> List[Path]:
    return sorted(
        path
        for path in datasets_dir.glob("*.csv")
        if path.is_file()
    )


def create_metadata_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_sources (
            table_name TEXT PRIMARY KEY,
            source_file TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            original_columns TEXT NOT NULL,
            normalized_columns TEXT NOT NULL,
            ingested_at TEXT NOT NULL
        )
        """
    )


def insert_metadata(
    conn: sqlite3.Connection,
    table_name: str,
    source_file: str,
    row_count: int,
    original_columns: Sequence[str],
    normalized_columns: Sequence[str],
) -> None:
    conn.execute(
        """
        INSERT INTO data_sources (table_name, source_file, row_count, original_columns, normalized_columns, ingested_at)
        VALUES (:table_name, :source_file, :row_count, :original_columns, :normalized_columns, :ingested_at)
        ON CONFLICT(table_name) DO UPDATE SET
            source_file=excluded.source_file,
            row_count=excluded.row_count,
            original_columns=excluded.original_columns,
            normalized_columns=excluded.normalized_columns,
            ingested_at=excluded.ingested_at
        """,
        {
            "table_name": table_name,
            "source_file": source_file,
            "row_count": row_count,
            "original_columns": json.dumps(list(original_columns), ensure_ascii=False),
            "normalized_columns": json.dumps(list(normalized_columns), ensure_ascii=False),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def ingest_file(
    conn: sqlite3.Connection,
    csv_path: Path,
    table_name: str,
    verbose: bool = False,
) -> int:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            raw_headers = next(reader)
        except StopIteration:
            raise ValueError(f"{csv_path} is empty.")
        normalized_headers = [normalize_identifier(col) for col in raw_headers]
        conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        schema_cols = ", ".join(f'"{name}" TEXT' for name in normalized_headers)
        conn.execute(f'CREATE TABLE "{table_name}" ({schema_cols})')
        column_list = ", ".join(f'"{h}"' for h in normalized_headers)
        placeholder_list = ", ".join("?" for _ in normalized_headers)
        insert_sql = f'INSERT INTO "{table_name}" ({column_list}) VALUES ({placeholder_list})'

        row_count = 0
        batch: List[Sequence[Union[str, int, float, None]]] = []
        for row in reader:
            if not row or all((value is None or not value.strip()) for value in row):
                # Skip blank lines that may appear at the end of a file.
                continue
            if len(row) != len(raw_headers):
                raise ValueError(
                    f"Row length mismatch in {csv_path} at row {row_count + 2}: "
                    f"expected {len(raw_headers)} values but found {len(row)}"
                )
            values = [coerce_value(value) for value in row]
            batch.append(values)
            row_count += 1
            if len(batch) >= BATCH_SIZE:
                conn.executemany(insert_sql, batch)
                batch.clear()
        if batch:
            conn.executemany(insert_sql, batch)

    if verbose:
        print(f'Loaded {row_count:,} rows into "{table_name}" from {csv_path.name}')
    insert_metadata(
        conn,
        table_name=table_name,
        source_file=str(csv_path),
        row_count=row_count,
        original_columns=raw_headers,
        normalized_columns=normalized_headers,
    )
    return row_count


def main() -> None:
    args = parse_args()
    datasets_dir: Path = args.datasets
    database_path: Path = args.database

    if not datasets_dir.exists() or not datasets_dir.is_dir():
        print(f"Dataset directory not found: {datasets_dir}", file=sys.stderr)
        raise SystemExit(1)

    csv_files = gather_csv_files(datasets_dir)
    if not csv_files:
        print(f"No CSV files found in {datasets_dir}", file=sys.stderr)
        raise SystemExit(1)

    ensure_directory(database_path)
    conn = sqlite3.connect(database_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=OFF;")
        create_metadata_table(conn)
        total_rows = 0
        for csv_file in csv_files:
            table_name = normalize_identifier(csv_file.stem)
            total_rows += ingest_file(conn, csv_file, table_name, verbose=args.verbose)
        conn.commit()
    finally:
        conn.close()

    print(
        f"Ingested {len(csv_files)} file(s) into {database_path} "
        f"with an aggregate of {total_rows:,} rows."
    )


if __name__ == "__main__":
    main()
