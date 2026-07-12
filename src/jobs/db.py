"""SQLite storage for pasted job postings and their extracted fields."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jobs.extract import JobExtraction

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    raw_text TEXT NOT NULL,
    job_title TEXT NOT NULL,
    company_name TEXT,
    is_agency_posting INTEGER NOT NULL,
    agency_name TEXT,
    client_name TEXT,
    recruiter_name TEXT,
    recruiter_contact TEXT,
    location TEXT,
    salary_raw TEXT,
    employer_name_for_sponsor_check TEXT,
    sponsor_status TEXT,
    sponsor_reason TEXT,
    sponsor_matched_name TEXT,
    sponsor_rating TEXT,
    sponsor_route TEXT,
    sponsor_matched_town_city TEXT,
    sponsor_matched_county TEXT,
    sponsor_checked_at TEXT,
    salary_status TEXT,
    salary_reason TEXT,
    salary_offered INTEGER,
    salary_threshold INTEGER,
    salary_soc_code TEXT,
    salary_soc_job_type TEXT,
    salary_checked_at TEXT,
    match_score INTEGER,
    match_verdict TEXT,
    match_matched_skills TEXT,
    match_missing_skills TEXT,
    match_reasoning TEXT,
    match_checked_at TEXT,
    tailor_hash TEXT,
    tailor_evidence_notes TEXT,
    tailor_portfolio_gaps TEXT,
    tailor_page_risk_warning TEXT,
    tailored_at TEXT,
    applied_status TEXT,
    applied_at TEXT,
    reminder_3_sent_at TEXT,
    reminder_7_sent_at TEXT,
    reminder_14_sent_at TEXT,
    created_at TEXT NOT NULL
);
"""


def _ensure_columns(conn: sqlite3.Connection, table: str, schema_sql: str) -> None:
    """Add any columns present in `schema_sql`'s CREATE TABLE but missing from
    an already-existing table on disk. `CREATE TABLE IF NOT EXISTS` is a
    no-op on a table that already exists, so a db created before a column
    was added would otherwise never get it. Safe because every column added
    after initial creation here is nullable."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    body = schema_sql.split("(", 1)[1].rsplit(")", 1)[0]
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        name, _, definition = line.partition(" ")
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_columns(conn, "jobs", SCHEMA)
    return conn


def insert_job(conn: sqlite3.Connection, raw_text: str, extraction: JobExtraction) -> int:
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO jobs
                (raw_text, job_title, company_name, is_agency_posting, agency_name,
                 client_name, recruiter_name, recruiter_contact, location, salary_raw,
                 employer_name_for_sponsor_check, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_text,
                extraction.job_title,
                extraction.company_name,
                int(extraction.is_agency_posting),
                extraction.agency_name,
                extraction.client_name,
                extraction.recruiter_name,
                extraction.recruiter_contact,
                extraction.location,
                extraction.salary_raw,
                extraction.employer_name_for_sponsor_check,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return cursor.lastrowid


def get_job(conn: sqlite3.Connection, job_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def list_jobs(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, job_title, company_name, is_agency_posting, sponsor_status,
               salary_status, match_score, match_verdict, applied_status, created_at
        FROM jobs ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()


def update_employer_name(conn: sqlite3.Connection, job_id: int, employer_name: str) -> None:
    """Manually set the employer to check (case c: you found the real employer
    yourself, e.g. via LinkedIn, after an agency posting redacted it). Clears
    any previous sponsor verdict since it no longer applies."""
    with conn:
        conn.execute(
            """
            UPDATE jobs
            SET employer_name_for_sponsor_check = ?,
                sponsor_status = NULL, sponsor_reason = NULL, sponsor_matched_name = NULL,
                sponsor_rating = NULL, sponsor_route = NULL, sponsor_checked_at = NULL
            WHERE id = ?
            """,
            (employer_name, job_id),
        )


def update_sponsor_verdict(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    status: str,
    reason: Optional[str],
    matched_name: Optional[str],
    rating: Optional[str],
    route: Optional[str],
    town_city: Optional[str] = None,
    county: Optional[str] = None,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE jobs
            SET sponsor_status = ?, sponsor_reason = ?, sponsor_matched_name = ?,
                sponsor_rating = ?, sponsor_route = ?, sponsor_matched_town_city = ?,
                sponsor_matched_county = ?, sponsor_checked_at = ?
            WHERE id = ?
            """,
            (
                status,
                reason,
                matched_name,
                rating,
                route,
                town_city,
                county,
                datetime.now(timezone.utc).isoformat(),
                job_id,
            ),
        )


def update_salary_verdict(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    status: str,
    reason: Optional[str],
    offered: Optional[int],
    threshold: Optional[int],
    soc_code: Optional[str],
    soc_job_type: Optional[str],
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE jobs
            SET salary_status = ?, salary_reason = ?, salary_offered = ?, salary_threshold = ?,
                salary_soc_code = ?, salary_soc_job_type = ?, salary_checked_at = ?
            WHERE id = ?
            """,
            (
                status,
                reason,
                offered,
                threshold,
                soc_code,
                soc_job_type,
                datetime.now(timezone.utc).isoformat(),
                job_id,
            ),
        )


def update_match_verdict(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    score: int,
    verdict: str,
    matched_skills: list[str],
    missing_skills: list[str],
    reasoning: str,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE jobs
            SET match_score = ?, match_verdict = ?, match_matched_skills = ?,
                match_missing_skills = ?, match_reasoning = ?, match_checked_at = ?
            WHERE id = ?
            """,
            (
                score,
                verdict,
                json.dumps(matched_skills),
                json.dumps(missing_skills),
                reasoning,
                datetime.now(timezone.utc).isoformat(),
                job_id,
            ),
        )


def update_tailoring(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    tailor_hash: str,
    evidence_notes: list[str],
    portfolio_gaps: list[str],
    page_risk_warning: Optional[str],
) -> None:
    """Stores only the small, cheap-to-keep-in-the-DB tailoring metadata -
    the actual tailored resume/cover-letter text lives only as files on disk
    now (cv/generated_cv/<company>/{job_id}_resume.docx etc.), never here.
    `page_risk_warning` is computed once at generation time (see
    `jobs.cli._tailor_docx_for_job`) and read back verbatim on a docx cache
    hit - never recomputed by diffing files."""
    with conn:
        conn.execute(
            """
            UPDATE jobs
            SET tailor_hash = ?, tailor_evidence_notes = ?, tailor_portfolio_gaps = ?,
                tailor_page_risk_warning = ?, tailored_at = ?
            WHERE id = ?
            """,
            (
                tailor_hash,
                json.dumps(evidence_notes),
                json.dumps(portfolio_gaps),
                page_risk_warning,
                datetime.now(timezone.utc).isoformat(),
                job_id,
            ),
        )


def list_legacy_tailored_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Rows with pre-existing DB-resident tailored text from before this app
    stopped writing it. A fresh DB (created after this change) never gets
    the `tailored_resume`/`cover_letter` columns at all - they're no longer
    part of SCHEMA, so `_ensure_columns()` won't add them either. Guard via
    `PRAGMA table_info` before querying those columns: querying a column
    that doesn't exist on a fresh DB is a hard sqlite3 error, not an empty
    result."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "tailored_resume" not in existing or "cover_letter" not in existing:
        return []
    return conn.execute(
        """
        SELECT id, company_name, tailored_resume, cover_letter
        FROM jobs
        WHERE tailored_resume IS NOT NULL OR cover_letter IS NOT NULL
        """
    ).fetchall()


def list_job_ids_and_company_names(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Small helper for the legacy-docx-rename matcher in `jobs.cli` - keeps
    that raw lookup behind this module's own DB access boundary instead of
    an ad-hoc `conn.execute(...)` in cli.py."""
    return conn.execute("SELECT id, company_name FROM jobs").fetchall()


def mark_applied(conn: sqlite3.Connection, job_id: int) -> None:
    """Mark a job applied and start its reminder clock. Clears any prior
    discard/reminder state, so re-applying after a discard starts fresh."""
    with conn:
        conn.execute(
            """
            UPDATE jobs
            SET applied_status = 'applied', applied_at = ?,
                reminder_3_sent_at = NULL, reminder_7_sent_at = NULL, reminder_14_sent_at = NULL
            WHERE id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), job_id),
        )


def mark_discarded(conn: sqlite3.Connection, job_id: int) -> None:
    with conn:
        conn.execute("UPDATE jobs SET applied_status = 'discarded' WHERE id = ?", (job_id,))


def mark_reminders_sent_through(conn: sqlite3.Connection, job_id: int, milestone: int) -> None:
    """Mark every reminder milestone up to and including `milestone` as sent -
    one follow-up covers any earlier milestones you missed."""
    now = datetime.now(timezone.utc).isoformat()
    columns = [f"reminder_{d}_sent_at" for d in (3, 7, 14) if d <= milestone]
    if not columns:
        return
    set_clause = ", ".join(f"{col} = ?" for col in columns)
    with conn:
        conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", (*([now] * len(columns)), job_id))


def list_applied_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs WHERE applied_status = 'applied'").fetchall()
