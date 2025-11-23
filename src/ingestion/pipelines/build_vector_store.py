"""Build a Chroma vector store from every table in the ingested SQLite database."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Sequence

try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError as exc:  # pragma: no cover - dependency is required at runtime.
    raise SystemExit(
        "chromadb is required for vector store ingestion. "
        "Install project dependencies via `pip install -e .`"
    ) from exc

VECTOR_BATCH_SIZE = 128
LANG_SUFFIX_MAP: Dict[str, Sequence[str]] = {
    "en": ("_en", "_english"),
    "fr": ("_fr", "_french"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a Chroma vector store from SQLite content.")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/processed/accessibility_ai.db"),
        help="Path to the SQLite database produced by the CSV ETL.",
    )
    parser.add_argument(
        "--persist-dir",
        type=Path,
        default=Path("data/vectorstore"),
        help="Directory for the persistent Chroma store (default: data/vectorstore).",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="accessible_services",
        help="Chroma collection name (default: accessible_services).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="SentenceTransformer model to use for embeddings.",
    )
    parser.add_argument(
        "--tables",
        nargs="*",
        help="Optional subset of tables to ingest (defaults to every table in the database, excluding metadata tables).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop the existing collection before ingesting.",
    )
    return parser.parse_args()


def ensure_database(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"SQLite database not found at {path}. Run the CSV ETL first.")


def ensure_persist_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def clean_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def get_all_tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    tables = [row[0] for row in rows if row[0] != "data_sources"]
    return tables


def get_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    pragma_rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [row[1] for row in pragma_rows]


def partition_language_columns(columns: Sequence[str]) -> tuple[Dict[str, List[str]], List[str]]:
    lang_columns: Dict[str, List[str]] = {lang: [] for lang in LANG_SUFFIX_MAP}
    shared: List[str] = []
    for column in columns:
        matched = False
        for lang, suffixes in LANG_SUFFIX_MAP.items():
            if any(column.endswith(suffix) for suffix in suffixes):
                lang_columns[lang].append(column)
                matched = True
                break
        if not matched:
            shared.append(column)
    return lang_columns, shared


def candidate_identifier_columns(columns: Sequence[str]) -> List[str]:
    return [column for column in columns if column.endswith("id")]


def build_text(row: Dict[str, object], fields: Sequence[str]) -> str | None:
    parts: List[str] = []
    for field in fields:
        if field not in row:
            continue
        value = clean_text(row[field])
        if value:
            parts.append(f"{field}: {value}")
    if not parts:
        return None
    return "\n".join(parts)


def ingest_table(
    conn: sqlite3.Connection,
    collection: chromadb.api.models.Collection.Collection,
    table_name: str,
) -> int:
    columns = get_columns(conn, table_name)
    lang_columns, shared_columns = partition_language_columns(columns)
    identifier_columns = candidate_identifier_columns(columns)

    select_clause = ", ".join(f'"{column}"' for column in columns)
    query = f'SELECT rowid AS internal_row_id, {select_clause} FROM "{table_name}"'
    cursor = conn.execute(query)

    docs: List[str] = []
    ids: List[str] = []
    metadatas: List[Dict[str, str]] = []
    added = 0

    for row in cursor:
        row_dict = {key: row[key] for key in row.keys()}
        shared_text = build_text(row_dict, shared_columns)
        row_identifier = f"{table_name}:{row_dict['internal_row_id']}"

        def add_document(language: str, content: str) -> None:
            metadata: Dict[str, str] = {
                "table_name": table_name,
                "language": language,
                "row_identifier": row_identifier,
                "column_count": str(len(columns)),
            }
            for column in identifier_columns[:3]:
                value = clean_text(row_dict.get(column))
                if value:
                    metadata[column] = value
            docs.append(content)
            ids.append(f"{row_identifier}:{language}")
            metadatas.append(metadata)

        language_added = False
        for language, lang_fields in lang_columns.items():
            lang_text = build_text(row_dict, lang_fields)
            if not lang_text and not shared_text:
                continue
            content_parts = [part for part in [lang_text, shared_text] if part]
            if not content_parts:
                continue
            add_document(language, "\n\n".join(content_parts))
            added += 1
            language_added = True

            if len(ids) >= VECTOR_BATCH_SIZE:
                collection.upsert(ids=ids, documents=docs, metadatas=metadatas)
                docs.clear()
                ids.clear()
                metadatas.clear()

        if not language_added and shared_text:
            add_document("unknown", shared_text)
            added += 1

            if len(ids) >= VECTOR_BATCH_SIZE:
                collection.upsert(ids=ids, documents=docs, metadatas=metadatas)
                docs.clear()
                ids.clear()
                metadatas.clear()

    if ids:
        collection.upsert(ids=ids, documents=docs, metadatas=metadatas)

    print(f"Ingested {added} documents from table '{table_name}'.")
    return added


def ingest_specific_tables(
    conn: sqlite3.Connection,
    collection: chromadb.api.models.Collection.Collection,
    tables: Sequence[str],
) -> int:
    total_docs = 0
    for table in tables:
        total_docs += ingest_table(conn, collection, table)
    return total_docs


def main() -> None:
    args = parse_args()
    ensure_database(args.database)
    ensure_persist_dir(args.persist_dir)

    conn = sqlite3.connect(args.database)
    conn.row_factory = sqlite3.Row

    available_tables = get_all_tables(conn)
    if args.tables:
        tables = [table for table in available_tables if table in set(args.tables)]
        missing = set(args.tables) - set(tables)
        if missing:
            raise SystemExit(f"Table(s) not found in database: {', '.join(sorted(missing))}")
    else:
        tables = available_tables

    embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=args.model)
    client = chromadb.PersistentClient(path=str(args.persist_dir))
    if args.reset:
        try:
            client.delete_collection(args.collection)
        except ValueError:
            pass
    collection = client.get_or_create_collection(
        name=args.collection,
        metadata={"hnsw:space": "cosine"},
        embedding_function=embedding_function,
    )

    try:
        total_docs = ingest_specific_tables(conn, collection, tables)
    finally:
        conn.close()

    print(
        f"Vector store ready at {args.persist_dir} (collection '{args.collection}'). "
        f"Total documents ingested: {total_docs}."
    )


if __name__ == "__main__":
    main()
