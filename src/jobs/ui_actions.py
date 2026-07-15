"""Job-scoped orchestration wrappers shared by every Streamlit page.

Tailoring and outreach used to be reachable only for the job you'd just
pasted in the current browser session (via `st.session_state.saved_job_id`)
- revisiting an older job meant re-pasting its posting text, which silently
created a duplicate row since `jobs.db.insert_job` never dedupes. These
wrappers take a plain `job_id` instead, so any page can trigger either
action for any stored job.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from jobs.cli import (
    DEFAULT_GENERATED_CV_DIR,
    DEFAULT_SOURCE_RESUME_DIR,
    _atomic_write_text,
    _load_resume_and_narrative,
    _outreach_message_path,
    _require_raw_resume_text,
    _tailor_docx_for_job,
)
from jobs.db import connect as connect_jobs
from jobs.db import get_job
from jobs.outreach import OutreachDraft, draft_outreach_message
from jobs.outreach_db import ensure_schema as ensure_outreach_schema
from jobs.outreach_db import insert_outreach_message


def error_display_text(exc: BaseException) -> str:
    """Text for a view to pass to `st.error()`. `str(exc)` is usually
    informative, but some exception types (e.g. bare `OSError`) can have an
    empty or whitespace-only `str()`, which renders a blank-looking error box
    with no clue what went wrong - fall back to naming the exception's type
    in that case. Takes `BaseException`, not `Exception`, since most callers
    pass a caught `SystemExit` (this codebase's own convention for
    CLI-layer failures reaching the UI), which is not an `Exception`
    subclass."""
    try:
        text = str(exc).strip()
    except Exception:
        text = ""
    return text or f"{type(exc).__name__}: (no error message)"


def generate_tailored_docx_for_job(job_id: int, jobs_db: str, profile_db: str) -> tuple[Path, Optional[str]]:
    """Tailor the resume + cover letter for any stored job. Mirrors
    `jobs.cli tailor-docx` via the same shared `_tailor_docx_for_job` helper
    (job_id-keyed cache-check - see that function's docstring). Returns
    (output directory, page-risk warning).

    Raises `SystemExit` for an unknown `job_id` - matching the CLI's own
    `_cmd_tailor`/`_cmd_tailor_docx` convention. Both Streamlit callers of
    this function (`views/intake.py`, `views/jobs_list.py`) already wrap
    their call in `except SystemExit as exc: st.error(error_display_text(exc))`
    (since `_require_raw_resume_text`/`_find_source_resume_docx` downstream
    can already raise it), so this doesn't crash the app - it surfaces as a
    normal error message like any other failure on this path."""
    jobs_conn = connect_jobs(jobs_db)
    try:
        job = get_job(jobs_conn, job_id)
        if job is None:
            raise SystemExit(f"No job #{job_id} found in {jobs_db}")
        raw_resume_text = _require_raw_resume_text(profile_db)
        result = _tailor_docx_for_job(
            jobs_conn, job, raw_resume_text, DEFAULT_SOURCE_RESUME_DIR, DEFAULT_GENERATED_CV_DIR, force=False
        )
        return result.resume_path.parent, result.page_risk_warning
    finally:
        jobs_conn.close()


def draft_and_save_outreach(
    job_id: int,
    channel: str,
    contact_id: Optional[int],
    contact_name: str,
    contact_title: Optional[str],
    purpose: Optional[str],
    jobs_db: str,
    profile_db: str,
) -> OutreachDraft:
    """Draft + persist an outreach message for any stored job. Raises
    `OutreachLengthError` (nothing saved) if the draft breaks its channel's
    length limit - the caller decides how to surface that."""
    raw_resume_text, narrative_core = _load_resume_and_narrative(profile_db)

    jobs_conn = connect_jobs(jobs_db)
    try:
        job = get_job(jobs_conn, job_id)
        draft = draft_outreach_message(
            channel,
            job["raw_text"],
            job["company_name"],
            contact_name,
            contact_title,
            narrative_core,
            raw_resume_text,
            purpose=purpose,
        )
        ensure_outreach_schema(jobs_conn)
        try:
            message_id = insert_outreach_message(
                jobs_conn, job_id, contact_id=contact_id, contact_name=contact_name, channel=channel, message=draft.message
            )
        except sqlite3.IntegrityError:
            raise SystemExit(
                "This jobs.db has a pre-existing outreach_messages table from before message text moved to disk - "
                "run `uv run python -m jobs.cli migrate-legacy-outreach` first."
            )
        path = _outreach_message_path(job["company_name"], job_id, channel, message_id, DEFAULT_GENERATED_CV_DIR)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _atomic_write_text(path, draft.message)
        except (OSError, ValueError) as exc:
            # Unlike the CLI's equivalent fix, the recovery text goes in the
            # exception message itself, not print()'d - a Streamlit user only
            # ever sees this via `st.error(error_display_text(exc))`, never
            # server stdout.
            raise SystemExit(
                f"Job #{job_id}: outreach message #{message_id} ({channel}, {len(draft.message)} chars) "
                f"was logged to the database, but writing its text to {path} failed: {exc}. "
                f"The drafted text itself was not saved to disk - recover it below:\n\n{draft.message}"
            )
        return draft
    finally:
        jobs_conn.close()
