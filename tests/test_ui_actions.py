"""Tests for `jobs.ui_actions` - job-scoped wrappers shared by every
Streamlit page. `draft_and_save_outreach` had zero test coverage before
this file (the write-atomicity/error-message fix in this diff is what
first required it)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import jobs.ui_actions as ui_actions
from jobs.db import connect as connect_jobs
from jobs.db import insert_job
from jobs.extract import JobExtraction
from jobs.outreach import LINKEDIN_NOTE, OutreachDraft
from jobs.outreach_db import ensure_schema as ensure_outreach_schema
from jobs.outreach_db import list_outreach_messages
from jobs.ui_actions import _outreach_message_path, draft_and_save_outreach, error_display_text
from resume.db import connect as connect_profile
from resume.db import insert_narrative, insert_profile
from resume.extract import ResumeProfile

RESUME_TEXT = "Jane Doe - Senior Backend Engineer. 5 years Python."


def _seed_profile_and_narrative(profile_db_path: Path) -> None:
    conn = connect_profile(profile_db_path)
    try:
        insert_profile(
            conn,
            RESUME_TEXT,
            ResumeProfile(
                full_name="Jane Doe",
                years_experience=5,
                seniority="Senior",
                core_skills=["Python"],
                domains=["Backend"],
                past_roles=["Engineer"],
                summary="Backend engineer.",
            ),
        )
        insert_narrative(conn, "Why AI, why UK, why them - the candidate's narrative core.")
    finally:
        conn.close()


@pytest.fixture
def ui_outreach_env(tmp_path, monkeypatch):
    jobs_db = tmp_path / "jobs.db"
    profile_db = tmp_path / "profile.db"

    conn = connect_jobs(jobs_db)
    try:
        job_id = insert_job(
            conn,
            "job posting text",
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

    _seed_profile_and_narrative(profile_db)

    monkeypatch.setattr(
        ui_actions, "draft_outreach_message", MagicMock(return_value=OutreachDraft(message="Hi Sarah, let's talk."))
    )

    return {"jobs_db": jobs_db, "profile_db": profile_db, "job_id": job_id}


def test_draft_and_save_outreach_writes_the_expected_txt_file_and_stores_no_message_column(ui_outreach_env):
    draft = draft_and_save_outreach(
        ui_outreach_env["job_id"],
        LINKEDIN_NOTE,
        contact_id=None,
        contact_name="Sarah Cole",
        contact_title="Recruiter",
        purpose=None,
        jobs_db=str(ui_outreach_env["jobs_db"]),
        profile_db=str(ui_outreach_env["profile_db"]),
    )

    assert draft.message == "Hi Sarah, let's talk."

    conn = connect_jobs(ui_outreach_env["jobs_db"])
    try:
        ensure_outreach_schema(conn)
        messages = list_outreach_messages(conn, ui_outreach_env["job_id"])
    finally:
        conn.close()

    assert len(messages) == 1
    message_row = messages[0]
    assert "message" not in message_row.keys()

    path = _outreach_message_path(
        "Bending Spoons", ui_outreach_env["job_id"], LINKEDIN_NOTE, message_row["id"], ui_actions.DEFAULT_GENERATED_CV_DIR
    )
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "Hi Sarah, let's talk."


def test_draft_and_save_outreach_write_failure_after_db_commit_raises_error_containing_the_drafted_text(
    ui_outreach_env, monkeypatch
):
    """The DB row commits before the file write is attempted, so a write
    failure here is worse than an ordinary I/O error - unlike the CLI's
    equivalent fix, the recovery text must be *inside* the exception
    message, since a Streamlit user never sees server-side print() output."""
    monkeypatch.setattr(ui_actions, "_atomic_write_text", MagicMock(side_effect=OSError("disk full")))

    with pytest.raises(SystemExit) as exc_info:
        draft_and_save_outreach(
            ui_outreach_env["job_id"],
            LINKEDIN_NOTE,
            contact_id=None,
            contact_name="Sarah Cole",
            contact_title="Recruiter",
            purpose=None,
            jobs_db=str(ui_outreach_env["jobs_db"]),
            profile_db=str(ui_outreach_env["profile_db"]),
        )

    message = str(exc_info.value)
    assert "was logged to the database" in message
    assert "Hi Sarah, let's talk." in message

    # The DB row is still there (insert-only convention, no rollback) - the
    # exact orphaned-metadata state the error message must warn about.
    conn = connect_jobs(ui_outreach_env["jobs_db"])
    try:
        ensure_outreach_schema(conn)
        messages = list_outreach_messages(conn, ui_outreach_env["job_id"])
    finally:
        conn.close()
    assert len(messages) == 1


def test_error_display_text_returns_str_exc_unchanged_when_non_empty():
    exc = ValueError("disk full")
    assert error_display_text(exc) == "disk full"


def test_error_display_text_falls_back_to_type_name_when_str_exc_is_empty():
    exc = OSError()
    assert str(exc) == ""

    text = error_display_text(exc)

    assert text != ""
    assert "OSError" in text


def test_error_display_text_falls_back_to_type_name_when_str_exc_is_whitespace_only():
    exc = ValueError("   ")

    text = error_display_text(exc)

    assert text.strip() != ""
    assert "ValueError" in text


def test_error_display_text_handles_system_exit_unchanged_when_non_empty():
    # SystemExit is what most real call sites (views/intake.py, views/jobs_list.py)
    # actually pass - it's a BaseException, not an Exception subclass.
    exc = SystemExit("No job #99 found in data/jobs.db")
    assert error_display_text(exc) == "No job #99 found in data/jobs.db"


def test_error_display_text_survives_a_str_that_itself_raises():
    class BrokenStr(Exception):
        def __str__(self):
            raise RuntimeError("__str__ is broken")

    text = error_display_text(BrokenStr())

    assert text != ""
    assert "BrokenStr" in text
