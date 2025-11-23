#!/usr/bin/env python3
"""
sample_datasets.py - emit headers + a few records from each dataset under a folder.

Usage:
    python sample_datasets.py /path/to/datasets --rows 5 --lines 8 --output dataset_samples.txt
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from itertools import islice
from pathlib import Path
from typing import Iterable, TextIO

STRUCTURED_EXTS = {".csv", ".tsv", ".psv"}
JSONL_EXTS = {".jsonl", ".ndjson"}


def open_text(path: Path) -> TextIO:
    if path.suffixes and path.suffixes[-1].lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore")  # type: ignore[arg-type]
    return path.open("r", encoding="utf-8", errors="ignore")


def base_extension(path: Path) -> str:
    suffixes = [s.lower() for s in path.suffixes]
    if suffixes and suffixes[-1] == ".gz":
        suffixes = suffixes[:-1]
    return suffixes[-1] if suffixes else ""


def sample_csv(path: Path, rows: int) -> str:
    with open_text(path) as fh:
        head = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(head)
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(fh, dialect)
        header = next(reader, [])
        chunks = [" | ".join(header) or "[no header detected]"]
        for row in islice(reader, rows):
            chunks.append(" | ".join(row))
    return "\n".join(chunks) if chunks else "[empty file]"


def sample_jsonl(path: Path, rows: int) -> str:
    snippets: list[str] = []
    with open_text(path) as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                snippets.append(json.dumps(obj, ensure_ascii=False, indent=2))
            except json.JSONDecodeError:
                snippets.append(line.rstrip())
            if len(snippets) >= rows:
                break
    return "\n---\n".join(snippets) if snippets else "[empty file]"


def sample_text(path: Path, lines: int) -> str:
    with open_text(path) as fh:
        grabbed = list(islice(fh, lines))
    return "".join(grabbed).rstrip() or "[empty file]"


def iter_files(root: Path) -> Iterable[Path]:
    for file_path in sorted(root.rglob("*")):
        if file_path.is_file():
            yield file_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Print headers and sample records from datasets.")
    parser.add_argument("root", type=Path, help="Folder containing datasets")
    parser.add_argument("--rows", type=int, default=5, help="Rows/records to show for CSV/JSONL (default: 5)")
    parser.add_argument("--lines", type=int, default=8, help="Lines to show for plain text/JSON files (default: 8)")
    parser.add_argument("--output", type=Path, help="Optional output file (defaults to STDOUT)")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"{root} is not a directory")

    out: TextIO
    if args.output:
        out = args.output.open("w", encoding="utf-8")
    else:
        out = sys.stdout  # type: ignore[name-defined]

    try:
        for path in iter_files(root):
            rel = path.relative_to(root)
            out.write(f"\n===== {rel} =====\n")
            ext = base_extension(path)
            try:
                if ext in STRUCTURED_EXTS:
                    snippet = sample_csv(path, args.rows)
                elif ext in JSONL_EXTS:
                    snippet = sample_jsonl(path, args.rows)
                else:
                    snippet = sample_text(path, args.lines)
            except Exception as exc:  # pragma: no cover
                snippet = f"[error reading file: {exc}]"
            out.write(f"{snippet}\n")
    finally:
        if args.output:
            out.close()


if __name__ == "__main__":
    import sys  # lazy import to keep sys out of the hot path

    main()
