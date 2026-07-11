"""Fetch, parse, normalize, and load the UK sponsor register."""

from __future__ import annotations

import csv
import io
import re
import urllib.request
from pathlib import Path

from register.db import SponsorRecord, connect, count, replace_all
from register.normalize import normalize_name

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

REQUIRED_COLUMNS = {"Organisation Name", "Town/City", "County", "Type & Rating", "Route"}


def fetch_csv_text(source: str) -> str:
    """Read CSV text from a URL or a local file path."""
    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=60) as response:
            raw = response.read()
    else:
        raw = Path(source).read_bytes()
    return raw.decode("utf-8-sig")


def guess_source_updated(source: str) -> str | None:
    """The register filename/URL usually embeds the publish date (YYYY-MM-DD)."""
    match = _DATE_RE.search(source)
    return match.group(1) if match else None


def parse_rows(csv_text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = {name.strip() for name in (reader.fieldnames or [])}
    missing = REQUIRED_COLUMNS - fieldnames
    if missing:
        raise ValueError(f"Register CSV is missing expected columns: {sorted(missing)}")
    return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def build_records(rows: list[dict[str, str]], source_updated: str | None) -> list[SponsorRecord]:
    records = []
    for row in rows:
        normalized = normalize_name(row["Organisation Name"])
        records.append(
            SponsorRecord(
                organisation_name=normalized.original,
                trading_name=normalized.trading_name,
                match_key=normalized.match_key,
                town_city=row.get("Town/City", ""),
                county=row.get("County", ""),
                rating=row.get("Type & Rating", ""),
                route=row.get("Route", ""),
                source_updated=source_updated or "",
            )
        )
    return records


def ingest(source: str, db_path: str) -> dict:
    """Full pipeline: fetch -> parse -> normalize -> replace-all load.

    The register is a periodic full snapshot, so every ingest run replaces
    the table wholesale rather than diffing against the previous load.
    """
    csv_text = fetch_csv_text(source)
    source_updated = guess_source_updated(source)
    rows = parse_rows(csv_text)
    records = build_records(rows, source_updated)

    conn = connect(db_path)
    try:
        loaded = replace_all(conn, records)
        total = count(conn)
    finally:
        conn.close()

    return {
        "source": source,
        "source_updated": source_updated,
        "rows_loaded": loaded,
        "rows_in_db": total,
    }
