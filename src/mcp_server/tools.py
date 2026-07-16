"""Thin, connection-per-call wrappers over the job-search pipeline, exposed as
MCP tools by `mcp_server.server`.

No business logic lives here - every function just opens a DB connection,
delegates to the already-correct pipeline function (`jobs.sponsor_check`,
`jobs.salary_check`, `jobs.db`, `jobs.tracker`, `register.db`), and closes the
connection in `finally` before returning a plain JSON-safe dict. Connection
lifetime is scoped to a single call, never held open across calls, because
the MCP server is a long-running process and a cached connection risks
missing writes made elsewhere (see project-context.md).

This module intentionally imports nothing from the `mcp` package, so it stays
importable and unit-testable even when the `mcp` SDK isn't installed - only
`mcp_server.server` needs that dependency.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jobs.db import _ensure_columns
from jobs.db import connect as connect_jobs
from jobs.db import get_job, list_applied_jobs, mark_applied, mark_discarded
from jobs.salary_check import check_salary_threshold as _check_salary_threshold
from jobs.sponsor_check import check_sponsor_status
from jobs.tracker import APPLIED, DISCARDED, due_milestone
from register.db import connect as connect_register

# Anchored to the project root (not the process's CWD) because an MCP client
# spawns this server with an arbitrary working directory - a relative default
# here would silently resolve to the wrong location and auto-create an empty
# DB there instead of erroring (see project-context.md).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPONSOR_DB = str(_PROJECT_ROOT / "data" / "sponsors.db")
DEFAULT_JOBS_DB = str(_PROJECT_ROOT / "data" / "jobs.db")

_ACTIONS = {APPLIED: mark_applied, DISCARDED: mark_discarded}

# Audit trail for MCP-triggered track_application mutations (see
# _bmad-output/implementation-artifacts/spec-mcp-track-application-audit-trail.md).
# Deliberately self-contained to this module - NOT part of jobs/db.py's SCHEMA
# - because the gap this closes ("was this even me?") is specific to the MCP
# invocation path; the CLI/Streamlit UI already act with the human at the
# keyboard. `job_id INTEGER NOT NULL` is safe at initial CREATE TABLE time
# only because every logged path already has a real job_id by the time a row
# is written; any *later* column added here must stay nullable, exactly like
# jobs/db.py's own `_ensure_columns()` guard, since ALTER TABLE ... ADD COLUMN
# with a NOT NULL constraint and no DEFAULT fails against a non-empty table.
_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_audit_log (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    job_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    previous_status TEXT,
    result TEXT NOT NULL,
    error TEXT
);
"""


def _ensure_audit_table(conn: sqlite3.Connection) -> None:
    """Idempotent create, plus a small additive-column migration guard so a
    `mcp_audit_log` table created by an older version of this code (missing a
    column this version expects) gets backfilled instead of breaking inserts.
    Reuses `jobs/db.py`'s own `_ensure_columns()` helper rather than
    re-implementing the same column-diffing logic here."""
    conn.executescript(_AUDIT_SCHEMA)
    _ensure_columns(conn, "mcp_audit_log", _AUDIT_SCHEMA)


def _record_audit(
    conn: sqlite3.Connection,
    job_id: int,
    action: str,
    previous_status: Optional[str],
    result: str,
    error: Optional[str] = None,
) -> None:
    """Write one `mcp_audit_log` row. Callers are responsible for deciding
    whether a failure here may propagate (see `track_application`) - this
    helper itself does no swallowing, so both the best-effort success-path
    caller and the must-not-suppress rejection-path caller can wrap it as
    appropriate."""
    with conn:
        conn.execute(
            """
            INSERT INTO mcp_audit_log (timestamp, job_id, action, previous_status, result, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (datetime.now(timezone.utc).isoformat(), job_id, action, previous_status, result, error),
        )


def check_sponsor(employer_name: Optional[str] = None, *, sponsor_db: str = DEFAULT_SPONSOR_DB) -> dict:
    """Look up whether `employer_name` is a licensed UK sponsor."""
    conn = connect_register(sponsor_db)
    try:
        # connect_register() (register.db.connect()) already sets its own
        # busy_timeout - re-setting it here would silently downgrade it,
        # defeating the margin it's sized for (unlike connect_jobs() below,
        # which sets none of its own).
        verdict = check_sponsor_status(conn, employer_name)
        return asdict(verdict)
    finally:
        conn.close()


def check_salary_threshold(job_title: str, salary_raw: Optional[str] = None) -> dict:
    """Check whether a posting's stated salary clears the Skilled Worker
    sponsorship threshold for this job title. No DB involved - pure lookup."""
    verdict = _check_salary_threshold(job_title, salary_raw)
    return asdict(verdict)


def track_application(job_id: int, action: str, *, jobs_db: str = DEFAULT_JOBS_DB) -> dict:
    """Mark a job applied or discarded, returning the updated job row.

    Raises ValueError for an unrecognised `action`, or for a `job_id` that
    doesn't exist in `jobs_db` - never guesses at either.

    Every attempt that reaches a real DB connection is written to
    `mcp_audit_log` - a successful mutation, an unknown-job_id rejection, and
    a mutation call that itself raises - so an MCP client's tracker changes
    can be reconstructed after the fact. The one exception is this function's
    very first check: an invalid `action` string must stay a zero-I/O
    fast-fail exactly as it was before this feature existed (no connection
    opened, no `jobs.db` created as a side effect, nothing logged) - see the
    frozen spec's `Never` bullet for why. Logging failures never change the
    outcome the caller sees: a successful mutation still returns its result
    even if writing the audit row fails, and a rejection's original exception
    is never suppressed or replaced by an audit-write failure.
    """
    if action not in _ACTIONS:
        raise ValueError(f"Unknown action '{action}' - expected one of {sorted(_ACTIONS)}")

    conn = connect_jobs(jobs_db)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            _ensure_audit_table(conn)
        except Exception:
            pass  # best-effort: a schema-setup hiccup must not block the mutation itself

        job = get_job(conn, job_id)
        if job is None:
            error = f"no job with id {job_id}"
            try:
                _record_audit(conn, job_id, action, None, "error", error)
            except Exception:
                pass  # must not suppress the ValueError below
            raise ValueError(error)

        previous_status = job["applied_status"]
        try:
            _ACTIONS[action](conn, job_id)
        except Exception as exc:
            try:
                _record_audit(conn, job_id, action, previous_status, "error", f"{type(exc).__name__}: {exc}")
            except Exception:
                pass  # must not suppress the original exception being re-raised
            raise

        updated = dict(get_job(conn, job_id))
        try:
            _record_audit(conn, job_id, action, previous_status, "success", None)
        except Exception:
            pass  # best-effort: a logging failure must not mask a successful return
        return updated
    finally:
        conn.close()


def list_applications(due_only: bool = False, *, jobs_db: str = DEFAULT_JOBS_DB) -> list[dict]:
    """List applied jobs, each annotated with its current `due_milestone`
    (3/7/14, or None). With `due_only=True`, only jobs with a due-and-not-yet-
    sent reminder are returned."""
    conn = connect_jobs(jobs_db)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        rows = list_applied_jobs(conn)
    finally:
        conn.close()

    results = []
    for row in rows:
        milestone = due_milestone(
            row["applied_at"], row["reminder_3_sent_at"], row["reminder_7_sent_at"], row["reminder_14_sent_at"]
        )
        if due_only and milestone is None:
            continue
        entry = dict(row)
        entry["due_milestone"] = milestone
        results.append(entry)
    return results
