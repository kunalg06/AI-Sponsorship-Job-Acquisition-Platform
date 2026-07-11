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

from dataclasses import asdict
from pathlib import Path
from typing import Optional

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


def check_sponsor(employer_name: Optional[str] = None, *, sponsor_db: str = DEFAULT_SPONSOR_DB) -> dict:
    """Look up whether `employer_name` is a licensed UK sponsor."""
    conn = connect_register(sponsor_db)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
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
    """
    if action not in _ACTIONS:
        raise ValueError(f"Unknown action '{action}' - expected one of {sorted(_ACTIONS)}")

    conn = connect_jobs(jobs_db)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        job = get_job(conn, job_id)
        if job is None:
            raise ValueError(f"no job with id {job_id}")
        _ACTIONS[action](conn, job_id)
        return dict(get_job(conn, job_id))
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
