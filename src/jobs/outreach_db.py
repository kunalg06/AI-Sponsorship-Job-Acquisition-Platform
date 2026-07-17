"""SQLite storage for job contacts and generated outreach message history.

Lives in the same jobs.db file as the `jobs` table (contacts and messages
are always scoped to a job) but owns its own schema application - call
`ensure_schema(conn)` once on a connection opened via jobs.db.connect()
before using the functions here.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    title TEXT,
    linkedin_url TEXT,
    email TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_messages (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    contact_id INTEGER,
    contact_name TEXT NOT NULL,
    channel TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    write_failed_at TEXT
);
"""


def _ensure_outreach_messages_columns(conn: sqlite3.Connection) -> None:
    """Add any `outreach_messages` column added to `SCHEMA` after a DB was
    first created - `CREATE TABLE IF NOT EXISTS` is a no-op on a table that
    already exists, so a pre-existing DB would otherwise never get it.
    Mirrors `drop_legacy_message_column`'s own `PRAGMA table_info` + direct
    `ALTER TABLE` style rather than reusing `jobs.db._ensure_columns`: that
    function's paren-parsing assumes one `CREATE TABLE` per schema string,
    and `SCHEMA` here has two (`contacts` + `outreach_messages`)."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_messages)")}
    if "write_failed_at" not in existing:
        conn.execute("ALTER TABLE outreach_messages ADD COLUMN write_failed_at TEXT")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _ensure_outreach_messages_columns(conn)


def insert_contact(
    conn: sqlite3.Connection,
    job_id: int,
    name: str,
    *,
    title: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    email: Optional[str] = None,
) -> int:
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO contacts (job_id, name, title, linkedin_url, email, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, name, title, linkedin_url, email, datetime.now(timezone.utc).isoformat()),
        )
    return cursor.lastrowid


def get_contact(conn: sqlite3.Connection, contact_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()


def list_contacts(conn: sqlite3.Connection, job_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM contacts WHERE job_id = ? ORDER BY id DESC", (job_id,)
    ).fetchall()


def insert_outreach_message(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    contact_id: Optional[int],
    contact_name: str,
    channel: str,
    message: str,
) -> int:
    """`message` is never stored in the DB - the full drafted text now lives
    only as a file on disk (see `jobs.cli._outreach_message_path`), written
    by the caller right after this returns the new row id (needed for the
    filename). `message` stays a required parameter purely so `char_count`
    can be computed here, matching the value the caller is about to write
    to file."""
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO outreach_messages (job_id, contact_id, contact_name, channel, char_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, contact_id, contact_name, channel, len(message), datetime.now(timezone.utc).isoformat()),
        )
    return cursor.lastrowid


def mark_outreach_write_failed(conn: sqlite3.Connection, message_id: int) -> None:
    """Marks a row as a known write-failure - its metadata was committed by
    `insert_outreach_message`, but the drafted text's file write then failed
    (see `jobs.cli._draft_and_store_outreach`/`jobs.ui_actions.
    draft_and_save_outreach`), leaving it permanently orphaned - nothing
    retries a failed write for the same row, so this doesn't recover the
    lost text, only lets a caller distinguish this row later from one whose
    file is simply missing for some other reason (deleted externally,
    moved) instead of showing the same generic message for both.

    Callers marking a failure from inside their own except block should
    wrap this call in its own try/except: it runs after the file write has
    already failed, so a second failure here (e.g. the same full/read-only
    disk also backs this DB) must not replace the caller's own, more
    informative error - see the call sites for the pattern."""
    with conn:
        conn.execute(
            "UPDATE outreach_messages SET write_failed_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), message_id),
        )


def list_outreach_messages(conn: sqlite3.Connection, job_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM outreach_messages WHERE job_id = ? ORDER BY id DESC", (job_id,)
    ).fetchall()


def list_legacy_outreach_message_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Rows with pre-existing DB-resident message text from before this app
    stopped writing it. A fresh DB (created after this change) never gets
    the `message` column at all - it's no longer part of SCHEMA. Guard via
    `PRAGMA table_info` before querying it: querying a column that doesn't
    exist on a fresh DB is a hard sqlite3 error, not an empty result."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_messages)")}
    if "message" not in existing:
        return []
    return conn.execute(
        """
        SELECT om.id, om.job_id, om.channel, om.message, j.company_name
        FROM outreach_messages om
        LEFT JOIN jobs j ON j.id = om.job_id
        WHERE om.message IS NOT NULL
        """
    ).fetchall()


def drop_legacy_message_column(conn: sqlite3.Connection) -> None:
    """Drops the legacy `message` column once its text has been backed up
    to disk (see `jobs.cli._migrate_legacy_outreach_text`). Guarded via
    `PRAGMA table_info` the same way as `list_legacy_outreach_message_rows`
    - a safe no-op against a fresh DB that never had the column."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_messages)")}
    if "message" not in existing:
        return
    with conn:
        conn.execute("ALTER TABLE outreach_messages DROP COLUMN message")
