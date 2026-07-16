"""Regression tests proving views/admin.py, views/intake.py, and
views/jobs_list.py route caught exceptions through
jobs.ui_actions.error_display_text rather than bare str(exc) - all
coverage before this file was at the helper's unit level only (see
test_ui_actions.py). Covers one representative call site per file (3 of
the 10 total error_display_text call sites across these views), per this
spec's own scope - enough to catch a systemic typo/revert, not exhaustive
per-site coverage. Uses `AppTest` to run each page as a real script, since
views/*.py execute top-level code (DB connections, widget rendering) as a
side effect of import."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from streamlit.testing.v1 import AppTest

from jobs.db import connect as connect_jobs
from jobs.db import insert_job
from jobs.extract import JobExtraction

RAW_JOB_TEXT = "AI Engineer role at Bending Spoons."

# Resolved at import time (before any test's chdir into a tmp sandbox) so
# AppTest.from_file can find the real scripts regardless of the test's cwd.
_VIEWS_DIR = Path(__file__).resolve().parent.parent / "views"
ADMIN_PY = str(_VIEWS_DIR / "admin.py")
INTAKE_PY = str(_VIEWS_DIR / "intake.py")
JOBS_LIST_PY = str(_VIEWS_DIR / "jobs_list.py")


def _seed_one_job(jobs_db_path) -> int:
    conn = connect_jobs(jobs_db_path)
    try:
        return insert_job(
            conn,
            RAW_JOB_TEXT,
            JobExtraction(
                job_title="AI Engineer",
                company_name="Bending Spoons",
                is_agency_posting=False,
                recruiter_name="Sarah Cole",
                recruiter_contact="sarah@bendingspoons.com",
            ),
        )
    finally:
        conn.close()


def test_admin_page_shows_error_display_text_for_empty_message_exception(streamlit_data_env, monkeypatch):
    # streamlit_data_env seeds sponsors.db via the real register.db.connect
    # before this monkeypatch is applied - pytest resolves fixtures ahead of
    # the test body, so seeding always completes first. Ordering matters:
    # applying the patch earlier would break seeding instead of the page.
    monkeypatch.setattr("register.db.connect", MagicMock(side_effect=OSError()))

    at = AppTest.from_file(ADMIN_PY)
    at.run()

    assert len(at.error) == 1
    assert "OSError" in at.error[0].value


def test_intake_page_shows_error_display_text_for_empty_message_exception(streamlit_data_env, monkeypatch):
    job_id = _seed_one_job(streamlit_data_env["jobs_db"])
    mock_tailor = MagicMock(side_effect=SystemExit())
    monkeypatch.setattr("jobs.ui_actions.generate_tailored_docx_for_job", mock_tailor)

    at = AppTest.from_file(INTAKE_PY)
    # The tailor button only renders once extraction/resolved_employer/saved_job_id
    # are all set (see views/intake.py's nested `if extraction:` / `if resolved_employer:`
    # gates) - presetting all three skips simulating the full paste-a-job flow.
    at.session_state["extraction"] = JobExtraction(
        job_title="AI Engineer",
        company_name="Bending Spoons",
        is_agency_posting=False,
    )
    at.session_state["resolved_employer"] = "Bending Spoons"
    at.session_state["saved_job_id"] = job_id
    at.run()

    tailor_button = next(b for b in at.button if "tailored resume" in b.label)
    tailor_button.click().run()

    assert len(at.error) == 1
    assert "SystemExit" in at.error[0].value
    # No pre-existing docx cache was seeded, so the button reads "Generate"
    # (not "Regenerate") - force should be False here (see
    # spec-force-regenerate-control.md for the True case).
    assert mock_tailor.call_args.kwargs["force"] is False


def test_jobs_list_page_shows_error_display_text_for_empty_message_exception(streamlit_data_env, monkeypatch):
    # Two jobs seeded (not one), and the assertion on call_args checks the
    # *second* job's id was passed - a mock that merely raises regardless of
    # args can't catch a wrong-loop-variable/closure bug that wires the
    # tailor button to the wrong job_id; asserting the argument can.
    jobs_db_path = streamlit_data_env["jobs_db"]
    _seed_one_job(jobs_db_path)
    second_job_id = _seed_one_job(jobs_db_path)
    mock_tailor = MagicMock(side_effect=SystemExit())
    monkeypatch.setattr("jobs.ui_actions.generate_tailored_docx_for_job", mock_tailor)

    at = AppTest.from_file(JOBS_LIST_PY)
    at.run()

    at.button(key=f"tailor_{second_job_id}").click().run()

    assert mock_tailor.call_args[0][0] == second_job_id
    assert mock_tailor.call_args.kwargs["force"] is False
    assert len(at.error) == 1
    assert "SystemExit" in at.error[0].value
