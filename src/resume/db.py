"""SQLite storage for candidate resume/profile versions.

Insert-only, like the jobs table: pasting an updated resume adds a new
version rather than overwriting, and match scoring always uses the latest.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from resume.extract import ResumeProfile

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY,
    raw_resume_text TEXT NOT NULL,
    full_name TEXT,
    years_experience REAL,
    seniority TEXT NOT NULL,
    core_skills TEXT NOT NULL,
    domains TEXT NOT NULL,
    past_roles TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS narrative_core (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(SCHEMA)
    return conn


def insert_profile(conn: sqlite3.Connection, raw_resume_text: str, profile: ResumeProfile) -> int:
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO profiles
                (raw_resume_text, full_name, years_experience, seniority,
                 core_skills, domains, past_roles, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_resume_text,
                profile.full_name,
                profile.years_experience,
                profile.seniority,
                json.dumps(profile.core_skills),
                json.dumps(profile.domains),
                json.dumps(profile.past_roles),
                profile.summary,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return cursor.lastrowid


def get_latest_profile(conn: sqlite3.Connection) -> Optional[ResumeProfile]:
    row = conn.execute("SELECT * FROM profiles ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return ResumeProfile(
        full_name=row["full_name"],
        years_experience=row["years_experience"],
        seniority=row["seniority"],
        core_skills=json.loads(row["core_skills"]),
        domains=json.loads(row["domains"]),
        past_roles=json.loads(row["past_roles"]),
        summary=row["summary"],
    )


def get_latest_raw_resume_text(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT raw_resume_text FROM profiles ORDER BY id DESC LIMIT 1").fetchone()
    return row["raw_resume_text"] if row else None


def insert_narrative(conn: sqlite3.Connection, text: str) -> int:
    with conn:
        cursor = conn.execute(
            "INSERT INTO narrative_core (text, created_at) VALUES (?, ?)",
            (text, datetime.now(timezone.utc).isoformat()),
        )
    return cursor.lastrowid


def get_latest_narrative(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT text FROM narrative_core ORDER BY id DESC LIMIT 1").fetchone()
    return row["text"] if row else None
