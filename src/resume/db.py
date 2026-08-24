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


# A profile row is only a candidate for "the current CV" if extraction actually
# got skills out of it. Both readers below share this predicate so they can
# never disagree about which row is current - one answering with the real
# resume while the other answers with a placeholder is how you get a tailored
# CV built from the wrong document.
_USABLE_PROFILE = "core_skills NOT IN ('[]', '') AND core_skills IS NOT NULL"


def get_latest_profile(conn: sqlite3.Connection) -> Optional[ResumeProfile]:
    """The most recent *usable* profile, skipping ones with no core_skills.

    The skip is the whole point. A profile row with `core_skills = []` carries
    no signal for match scoring, but it is not inert: jobs.match_score feeds it
    to the LLM, which then correctly scores a blank candidate 0/100 against
    every job. That failure is silent - no error, no NULL, just a wall of
    plausible-looking zeros that reads as "you match nothing" rather than "the
    profile is empty". It happened for real: a test wrote a placeholder row
    (raw_resume_text='current resume text') into the production profile db on
    2026-07-29, and because this query was ORDER BY id DESC it won over the
    real resume and zeroed 86 jobs before anyone noticed.

    Fixing the row that caused it is not enough - any future stray insert
    re-arms the same trap - so the guard lives here, at the read. If *every*
    profile is empty we return None, which callers already handle by skipping
    scoring and leaving match_score NULL; per
    jobs.match_score.partition_discovery_queue a NULL is an absence of
    information and keeps the row in the queue for a human, whereas a 0 is a
    verdict that silently discards it.
    """
    row = conn.execute(
        f"SELECT * FROM profiles WHERE {_USABLE_PROFILE} ORDER BY id DESC LIMIT 1"
    ).fetchone()
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
    """Raw text of the same row get_latest_profile() would return.

    Skips skill-less rows for the same reason - jobs.cli feeds this straight
    into resume/cover-letter tailoring, so a placeholder row winning here means
    generating an application from text like 'current resume text'.
    """
    row = conn.execute(
        f"SELECT raw_resume_text FROM profiles WHERE {_USABLE_PROFILE} ORDER BY id DESC LIMIT 1"
    ).fetchone()
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
