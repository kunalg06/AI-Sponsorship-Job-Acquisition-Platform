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
    message TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


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
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO outreach_messages (job_id, contact_id, contact_name, channel, message, char_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, contact_id, contact_name, channel, message, len(message), datetime.now(timezone.utc).isoformat()),
        )
    return cursor.lastrowid


def list_outreach_messages(conn: sqlite3.Connection, job_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM outreach_messages WHERE job_id = ? ORDER BY id DESC", (job_id,)
    ).fetchall()
