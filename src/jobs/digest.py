"""Daily coach digest: a deterministic (no LLM call) read layer over the
application tracker, match queue, portfolio gaps, and recent activity -
"what should I do today," per docs/v1-scope.md's V2 fast-follow scope.
Every line is templated straight from query results; nothing here ever
invents advice not grounded in the DB.

`list_due_reminders` also replaces the day-3/7/14 reminder logic that used
to be duplicated inline in `jobs.cli._cmd_due` and `views/jobs_list.py`'s
tracker expander - both now call this instead. (The single-job "Application
Status" detail panel in `views/jobs_list.py` still computes `due_milestone`
inline for its own one-row display - that third call site was out of scope
for this pass and was not touched.)"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from jobs.db import list_applied_jobs
from jobs.outreach_db import ensure_schema as ensure_outreach_schema
from jobs.tracker import days_since, due_milestone


@dataclass
class DueReminder:
    job_id: int
    job_title: str
    company_name: Optional[str]
    milestone: int
    days: int


@dataclass
class QueuedMatch:
    job_id: int
    job_title: str
    company_name: Optional[str]
    match_score: int
    match_verdict: str


@dataclass
class GapTheme:
    gap: str
    count: int


@dataclass
class Momentum:
    applications_last_7_days: int
    last_outreach_drafted_at: Optional[str]
    last_tailored_at: Optional[str]


@dataclass
class Digest:
    due_reminders: list[DueReminder]
    match_queue: list[QueuedMatch]
    gap_themes: list[GapTheme]
    momentum: Momentum


def list_due_reminders(applied_jobs: list[sqlite3.Row]) -> list[DueReminder]:
    """Applied jobs with a day 3/7/14 follow-up currently due, most overdue
    first (`jobs.cli`'s original `due` command and `views/jobs_list.py`'s
    tracker expander both used DB-insertion order before this - most-overdue
    first is strictly more useful and applies to both now).

    "Most overdue" is measured relative to each reminder's own milestone
    (`days - milestone`), not raw days-since-applied - a day-14 reminder
    that's 1 day overdue is less urgent than a day-3 reminder that's 5 days
    overdue, even though the day-14 job was applied to longer ago.

    Takes an already-fetched `applied_jobs` list (from `list_applied_jobs`)
    rather than a connection, so a caller that also needs the raw applied-jobs
    rows (e.g. `views/jobs_list.py`) can fetch once and pass the same list to
    both, instead of two separate queries against a connection that could see
    different data between them."""
    reminders = []
    for job in applied_jobs:
        milestone = due_milestone(
            job["applied_at"], job["reminder_3_sent_at"], job["reminder_7_sent_at"], job["reminder_14_sent_at"]
        )
        if milestone is None:
            continue
        reminders.append(
            DueReminder(
                job_id=job["id"],
                job_title=job["job_title"],
                company_name=job["company_name"],
                milestone=milestone,
                days=days_since(job["applied_at"]),
            )
        )
    reminders.sort(key=lambda r: r.days - r.milestone, reverse=True)
    return reminders


def list_match_queue(conn: sqlite3.Connection) -> list[QueuedMatch]:
    """Jobs already scored but not yet decided (applied or discarded),
    highest match score first - the "what should I look at next" queue."""
    rows = conn.execute(
        """
        SELECT id, job_title, company_name, match_score, match_verdict
        FROM jobs
        WHERE match_score IS NOT NULL AND applied_status IS NULL
        ORDER BY match_score DESC
        """
    ).fetchall()
    return [
        QueuedMatch(
            job_id=row["id"],
            job_title=row["job_title"],
            company_name=row["company_name"],
            match_score=row["match_score"],
            match_verdict=row["match_verdict"],
        )
        for row in rows
    ]


def list_recurring_portfolio_gaps(conn: sqlite3.Connection, *, min_count: int = 2) -> list[GapTheme]:
    """Portfolio gaps repeated across 2+ jobs, most frequent first - exact
    string match only (no fuzzy/semantic merging of near-identical
    phrasings in v1; revisit only if that proves too lossy in practice,
    matching this project's existing "start simple" convention). A gap
    appearing on only one job isn't a "theme" yet, so `min_count` defaults
    to 2."""
    rows = conn.execute("SELECT tailor_portfolio_gaps FROM jobs WHERE tailor_portfolio_gaps IS NOT NULL").fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        job_gaps = {gap.strip() for gap in json.loads(row["tailor_portfolio_gaps"]) if gap.strip()}
        for gap in job_gaps:
            counts[gap] = counts.get(gap, 0) + 1
    themes = [GapTheme(gap=gap, count=count) for gap, count in counts.items() if count >= min_count]
    themes.sort(key=lambda t: t.count, reverse=True)
    return themes


def compute_momentum(conn: sqlite3.Connection) -> Momentum:
    """Recent-activity signal - deliberately just counts/max-timestamps, no
    trend lines or week-over-week comparison in v1. Calls
    `ensure_outreach_schema` itself since `outreach_messages` isn't part of
    jobs.db's base schema and may not exist yet on a DB that's never had
    outreach used."""
    ensure_outreach_schema(conn)
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    applications_last_7_days = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE applied_at IS NOT NULL AND applied_at >= ?",
        (seven_days_ago,),
    ).fetchone()[0]
    last_outreach_drafted_at = conn.execute("SELECT MAX(created_at) FROM outreach_messages").fetchone()[0]
    last_tailored_at = conn.execute("SELECT MAX(tailored_at) FROM jobs").fetchone()[0]
    return Momentum(
        applications_last_7_days=applications_last_7_days,
        last_outreach_drafted_at=last_outreach_drafted_at,
        last_tailored_at=last_tailored_at,
    )


def build_digest(conn: sqlite3.Connection) -> Digest:
    """Single source of truth for both the `jobs digest` CLI command and
    `views/digest.py` - both render this same object, so they can't drift."""
    return Digest(
        due_reminders=list_due_reminders(list_applied_jobs(conn)),
        match_queue=list_match_queue(conn),
        gap_themes=list_recurring_portfolio_gaps(conn),
        momentum=compute_momentum(conn),
    )
