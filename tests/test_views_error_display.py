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


def test_intake_page_extract_button_shows_error_display_text_on_extraction_failure(streamlit_data_env, monkeypatch):
    # extract_job/score_job_match/extract_profile had NO error handling at
    # all until this fix (unlike the three SystemExit-raising call sites
    # above) - a real API failure crashed the whole page uncaught. This
    # covers the "Extract & Check Sponsor" button, the first of the two
    # newly-wrapped call sites in this file.
    monkeypatch.setattr("jobs.extract.extract_job", MagicMock(side_effect=SystemExit("Job extraction failed: boom")))

    at = AppTest.from_file(INTAKE_PY)
    at.run()
    at.text_area(key="raw_text_input").input(RAW_JOB_TEXT).run()

    extract_button = next(b for b in at.button if b.label == "Extract & Check Sponsor")
    extract_button.click().run()

    assert len(at.error) == 1
    assert "Job extraction failed: boom" in at.error[0].value
    # A failed extraction must not silently carry over a stale raw_text into
    # session state as if it had succeeded.
    assert "raw_text" not in at.session_state
    assert "extraction" not in at.session_state or at.session_state["extraction"] is None


def test_admin_page_extract_register_button_shows_error_display_text_on_extraction_failure(
    streamlit_data_env, monkeypatch
):
    # The second newly-wrapped call site: extract_profile's caller used
    # `except Exception`, which does NOT catch SystemExit (not an Exception
    # subclass) - without widening it, this fix would still crash uncaught.
    monkeypatch.setattr(
        "resume.extract.extract_profile", MagicMock(side_effect=SystemExit("Resume profile extraction failed: boom"))
    )

    at = AppTest.from_file(ADMIN_PY)
    at.run()
    at.file_uploader[0].set_value(("resume.txt", b"Jane Doe\nSenior ML Engineer", "text/plain"))
    at.run()

    register_button = next(b for b in at.button if b.label == "Extract & Register Profile")
    register_button.click().run()

    assert len(at.error) == 1
    assert "Resume profile extraction failed: boom" in at.error[0].value
    assert at.session_state["cv_registration_in_progress"] is False
