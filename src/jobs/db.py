"""SQLite storage for pasted job postings and their extracted fields."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from jobs.extract import JobExtraction

BUSY_TIMEOUT_MS = 5000

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
    tailoring_lock_started_at TEXT,
    tailoring_lock_token TEXT,
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
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
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


def try_claim_tailoring_lock(
    conn: sqlite3.Connection, job_id: int, *, stale_after_seconds: int = 300
) -> Optional[str]:
    """Atomically claim `job_id`'s advisory tailoring lock, so two concurrent
    callers of `jobs.cli._tailor_docx_for_job` (e.g. two browser tabs, or a
    CLI run overlapping a UI click) can't both reach the LLM/file-write step
    for the same job and race each other's output. The claim is a single
    conditional `UPDATE` (not a read-then-write check), since a separate
    check-and-set would reopen the same race this exists to close.

    Returns a caller-private ownership token on success, to be passed to
    `release_tailoring_lock` - or `None` if someone else already holds a
    live lock (claimed less than `stale_after_seconds` ago). A lock older
    than that is still claimable even though nothing explicitly released it,
    protecting against a crashed/killed process leaving the lock set
    forever - but that reclaim is exactly why the token exists: without it,
    a slow original holder finally finishing (and releasing) *after* its own
    lock went stale and was reclaimed by someone else would clobber the new
    holder's live lock. `release_tailoring_lock` only clears the lock when
    the token still matches, so a delayed release from a since-superseded
    holder is a safe no-op instead.

    Assumes `job_id` refers to an existing row - like a claim against a
    stale lock, an `UPDATE` against a nonexistent `job_id` also matches zero
    rows and returns `None` indistinguishably from "lock held by someone
    else"; callers must already have validated the job exists (as both
    `jobs.cli._cmd_tailor_docx` and `ui_actions.generate_tailored_docx_for_job`
    do via `get_job` before reaching this call).

    Staleness is a plain string comparison, correct only because every
    writer of this column goes through `datetime.now(timezone.utc)
    .isoformat()` (fixed-width, UTC) - a differently-formatted timestamp
    written by some future direct SQL would silently break it."""
    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    stale_cutoff = (now - timedelta(seconds=stale_after_seconds)).isoformat()
    with conn:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET tailoring_lock_started_at = ?, tailoring_lock_token = ?
            WHERE id = ? AND (tailoring_lock_started_at IS NULL OR tailoring_lock_started_at < ?)
            """,
            (now.isoformat(), token, job_id, stale_cutoff),
        )
    return token if cursor.rowcount > 0 else None


def release_tailoring_lock(conn: sqlite3.Connection, job_id: int, token: str) -> None:
    """Clears `job_id`'s advisory tailoring lock, but only if `token` still
    matches what's currently stored there - see `try_claim_tailoring_lock`
    for why an unconditional clear would be unsafe. Callers of
    `try_claim_tailoring_lock` must call this in a `finally` block (with the
    token it returned) so the lock always clears on the owning caller's own
    exit, success or failure - otherwise a single failed generation would
    permanently block that job's future retries until the staleness window
    passes."""
    with conn:
        conn.execute(
            "UPDATE jobs SET tailoring_lock_started_at = NULL, tailoring_lock_token = NULL "
            "WHERE id = ? AND tailoring_lock_token = ?",
            (job_id, token),
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
