"""SQLite storage for the cleaned sponsor register."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS sponsors (
    id INTEGER PRIMARY KEY,
    organisation_name TEXT NOT NULL,
    trading_name TEXT,
    match_key TEXT NOT NULL,
    town_city TEXT,
    county TEXT,
    rating TEXT,
    route TEXT NOT NULL,
    source_updated TEXT
);
CREATE INDEX IF NOT EXISTS idx_sponsors_match_key ON sponsors(match_key);

CREATE TABLE IF NOT EXISTS sponsor_overrides (
    id INTEGER PRIMARY KEY,
    organisation_name TEXT NOT NULL,
    match_key TEXT NOT NULL UNIQUE,
    town_city TEXT,
    county TEXT,
    rating TEXT,
    route TEXT,
    status TEXT NOT NULL,
    notes TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sponsor_overrides_match_key ON sponsor_overrides(match_key);
"""

# The register is only as fresh as its last download, and being on it never
# meant "still sponsoring anyone" (see LICENCE_CAVEAT in jobs.sponsor_check).
# This table is the user's own, persistent, company-level notes on top of
# that snapshot - separate from `sponsors` so re-ingesting the CSV (which
# wipes and reloads `sponsors` only) never touches it.
OVERRIDE_ACTIVE = "active"
OVERRIDE_INACTIVE = "inactive"
OVERRIDE_LAPSED = "lapsed"
OVERRIDE_UNCONFIRMED = "unconfirmed"
OVERRIDE_STATUSES = (OVERRIDE_ACTIVE, OVERRIDE_INACTIVE, OVERRIDE_LAPSED, OVERRIDE_UNCONFIRMED)

# replace_all() wipes and reloads the full ~142k-row register in one
# transaction; a one-off manual measurement against the real local register
# (not committed anywhere - see spec-register-busy-timeout-tuning) found its
# worst of 3 trials at 635ms. 15000ms is ~24x that worst-case trial - a
# concurrent reader/writer waiting on replace_all()'s write lock gets a
# comfortable margin for slower/virtualized disk I/O on an unmeasured deploy
# target (e.g. Streamlit Cloud), at the cost of a real (if rare) tradeoff:
# any *other* kind of lock contention (a hung/long transaction, not just a
# normal replace_all()) now blocks up to 3x longer before failing.
BUSY_TIMEOUT_MS = 15000


@dataclass(frozen=True)
class SponsorRecord:
    organisation_name: str
    trading_name: str | None
    match_key: str
    town_city: str
    county: str
    rating: str
    route: str
    source_updated: str


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the sponsor register database."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.executescript(SCHEMA)
    return conn


def replace_all(conn: sqlite3.Connection, records: list[SponsorRecord]) -> int:
    """Wipe and reload the sponsors table.

    The register is a periodic full snapshot, not an incremental feed, so
    replace-all on each ingest run is the correct model, not a diff.
    """
    with conn:
        conn.execute("DELETE FROM sponsors")
        conn.executemany(
            """
            INSERT INTO sponsors
                (organisation_name, trading_name, match_key, town_city, county, rating, route, source_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.organisation_name,
                    r.trading_name,
                    r.match_key,
                    r.town_city,
                    r.county,
                    r.rating,
                    r.route,
                    r.source_updated,
                )
                for r in records
            ],
        )
    return len(records)


def lookup(conn: sqlite3.Connection, match_key: str) -> list[sqlite3.Row]:
    """Find sponsors whose match_key matches exactly. A company can have more
    than one register entry (different routes/ratings), so this can return
    multiple rows."""
    cursor = conn.execute("SELECT * FROM sponsors WHERE match_key = ?", (match_key,))
    return cursor.fetchall()


def lookup_contains(conn: sqlite3.Connection, match_key: str) -> list[sqlite3.Row]:
    """Fallback fuzzy lookup for when an exact match_key lookup finds nothing.

    Finds sponsors whose match_key *contains* the query as a substring - e.g.
    a job posting names the parent/brand ("Bending Spoons") while the
    register lists the full legal entity ("Bending Spoons Operations S.p.A.
    (UK Branch)"). Confirmed real (~1,900 of 142k register rows carry an
    extended corporate suffix like this), so this isn't a rare edge case.
    """
    escaped = match_key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    cursor = conn.execute(
        "SELECT * FROM sponsors WHERE match_key LIKE ? ESCAPE '\\'",
        (f"%{escaped}%",),
    )
    return cursor.fetchall()


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM sponsors").fetchone()[0]


def get_current_source_updated(conn: sqlite3.Connection) -> Optional[str]:
    """The `source_updated` of the currently loaded snapshot, or None if empty.

    Every row from one ingest run shares the same `source_updated` (see
    `register.ingest.build_records`), so any single row is representative.
    Lets a caller detect a no-op refresh (same snapshot re-fetched) before
    deciding how to report the result.
    """
    row = conn.execute("SELECT source_updated FROM sponsors LIMIT 1").fetchone()
    return row["source_updated"] if row else None


def is_noop_refresh(previous_source_updated: Optional[str], new_source_updated: Optional[str]) -> bool:
    """True when a refresh's fetched snapshot date matches what was already loaded.

    Both sides are normalized (empty string treated the same as None) before
    comparing, since `ingest()` can return a raw `None` for an unparseable
    source date while a DB round-trip stores/returns `""` for the same case
    (`register.ingest.build_records` writes `source_updated or ""`). Without
    normalizing, `None != ""` would report every unparseable-date refresh as
    "new" even when it's a re-fetch of the exact same source. When the date
    can't be determined on either side, this stays conservative and reports
    "not a no-op" (never claims two unknown-date snapshots are the same one).
    """
    previous = previous_source_updated or None
    current = new_source_updated or None
    return bool(previous and current and previous == current)


def upsert_override(
    conn: sqlite3.Connection,
    *,
    organisation_name: str,
    match_key: str,
    status: str,
    town_city: Optional[str] = None,
    county: Optional[str] = None,
    rating: Optional[str] = None,
    route: Optional[str] = None,
    notes: Optional[str] = None,
) -> int:
    """Create or update the single override entry for this match_key - one
    company, one current status, so re-flagging just updates it in place."""
    if status not in OVERRIDE_STATUSES:
        raise ValueError(f"Unknown override status '{status}' - expected one of {OVERRIDE_STATUSES}")

    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            """
            INSERT INTO sponsor_overrides
                (organisation_name, match_key, town_city, county, rating, route, status, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_key) DO UPDATE SET
                organisation_name = excluded.organisation_name,
                town_city = excluded.town_city,
                county = excluded.county,
                rating = excluded.rating,
                route = excluded.route,
                status = excluded.status,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (organisation_name, match_key, town_city, county, rating, route, status, notes, now),
        )
    row = conn.execute("SELECT id FROM sponsor_overrides WHERE match_key = ?", (match_key,)).fetchone()
    return row["id"]


def lookup_override(conn: sqlite3.Connection, match_key: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM sponsor_overrides WHERE match_key = ?", (match_key,)).fetchone()


def list_overrides(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM sponsor_overrides ORDER BY organisation_name").fetchall()
