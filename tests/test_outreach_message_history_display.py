"""Proves the "Message history" expander in views/jobs_list.py and
views/intake.py shows a distinguishing caption for a row known to have
failed its file write, instead of the generic "(message file not found)"
caption used for every other missing-file case (e.g. a file deleted
externally). Uses `AppTest` since these are Streamlit page scripts that
execute top-level code as a side effect of import - see
test_views_error_display.py for the same pattern."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from jobs.db import connect as connect_jobs
from jobs.db import insert_job
from jobs.extract import JobExtraction
from jobs.outreach import LINKEDIN_NOTE
from jobs.outreach_db import ensure_schema as ensure_outreach_schema
from jobs.outreach_db import insert_outreach_message, mark_outreach_write_failed

# Resolved at import time (before any test's chdir into a tmp sandbox) so
# AppTest.from_file can find the real scripts regardless of the test's cwd.
_VIEWS_DIR = Path(__file__).resolve().parent.parent / "views"
INTAKE_PY = str(_VIEWS_DIR / "intake.py")
JOBS_LIST_PY = str(_VIEWS_DIR / "jobs_list.py")


def _seed_job_with_outreach_message(jobs_db_path, *, write_failed: bool) -> int:
    conn = connect_jobs(jobs_db_path)
    try:
        ensure_outreach_schema(conn)
        job_id = insert_job(
            conn,
            "AI Engineer role at Bending Spoons.",
            JobExtraction(job_title="AI Engineer", company_name="Bending Spoons", is_agency_posting=False),
        )
        message_id = insert_outreach_message(
            conn, job_id, contact_id=None, contact_name="Sarah Cole", channel=LINKEDIN_NOTE, message="Hi Sarah!"
        )
        if write_failed:
            mark_outreach_write_failed(conn, message_id)
        # Deliberately never writes the .txt file - both the write-failure
        # and the "genuinely missing" cases look identical on disk (nothing
        # there); only the DB marker tells them apart.
        return job_id
    finally:
        conn.close()


def test_jobs_list_shows_distinguishing_caption_for_a_known_write_failure(streamlit_data_env):
    _seed_job_with_outreach_message(streamlit_data_env["jobs_db"], write_failed=True)

    at = AppTest.from_file(JOBS_LIST_PY)
    at.run()

    captions = [c.value for c in at.caption]
    assert "(drafted text failed to save to disk at the time - not recoverable)" in captions
    assert "(message file not found)" not in captions


def test_jobs_list_shows_generic_caption_when_the_file_is_missing_for_an_unknown_reason(streamlit_data_env):
    _seed_job_with_outreach_message(streamlit_data_env["jobs_db"], write_failed=False)

    at = AppTest.from_file(JOBS_LIST_PY)
    at.run()

    captions = [c.value for c in at.caption]
    assert "(message file not found)" in captions
    assert "(drafted text failed to save to disk at the time - not recoverable)" not in captions


def test_intake_shows_distinguishing_caption_for_a_known_write_failure(streamlit_data_env):
    job_id = _seed_job_with_outreach_message(streamlit_data_env["jobs_db"], write_failed=True)

    at = AppTest.from_file(INTAKE_PY)
    # Message history only renders once extraction/resolved_employer/saved_job_id
    # are all set (see views/intake.py's nested `if extraction:` / `if
    # resolved_employer:` gates) - presetting all three skips simulating the
    # full paste-a-job flow, matching test_views_error_display.py's pattern.
    at.session_state["extraction"] = JobExtraction(
        job_title="AI Engineer", company_name="Bending Spoons", is_agency_posting=False
    )
    at.session_state["resolved_employer"] = "Bending Spoons"
    at.session_state["saved_job_id"] = job_id
    at.run()

    captions = [c.value for c in at.caption]
    assert "(drafted text failed to save to disk at the time - not recoverable)" in captions


def test_intake_shows_generic_caption_when_the_file_is_missing_for_an_unknown_reason(streamlit_data_env):
    # Mirrors the jobs_list generic-caption test above - without this, only
    # intake's write-failed=True branch is proven, so a regression that
    # broke intake's `else` fallback (e.g. an accidental elif/if swap) would
    # go undetected even though the two views are meant to behave identically.
    job_id = _seed_job_with_outreach_message(streamlit_data_env["jobs_db"], write_failed=False)

    at = AppTest.from_file(INTAKE_PY)
    at.session_state["extraction"] = JobExtraction(
        job_title="AI Engineer", company_name="Bending Spoons", is_agency_posting=False
    )
    at.session_state["resolved_employer"] = "Bending Spoons"
    at.session_state["saved_job_id"] = job_id
    at.run()

    captions = [c.value for c in at.caption]
    assert "(message file not found)" in captions
    assert "(drafted text failed to save to disk at the time - not recoverable)" not in captions
