"""Tests for the `skip-sponsor-check` CLI command and the intake page's
"Remote from anywhere" checkbox - both routes to the same SKIPPED sponsor
verdict, letting a job bypass the UK sponsor register check when the posting
has no UK right-to-work requirement at all. Exercised through the real CLI
wiring (`build_parser()`/`args.func`, same convention as test_jobs_cli.py)
and, for the checkbox, through a real page run (`AppTest`, same convention
as test_views_error_display.py)."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from jobs.cli import build_parser
from jobs.db import connect as connect_jobs
from jobs.db import get_job, insert_job
from jobs.extract import JobExtraction
from jobs.sponsor_check import REMOTE_ANYWHERE_SKIP_REASON, SKIPPED

# Resolved at import time (before any test's chdir into a tmp sandbox) so
# AppTest.from_file can find the real script regardless of the test's cwd.
_INTAKE_PY = str(Path(__file__).resolve().parent.parent / "views" / "intake.py")


def _run(argv: list[str]) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


def _make_job(jobs_db_path: Path, *, company_name="Acme AI") -> int:
    conn = connect_jobs(jobs_db_path)
    try:
        job_id = insert_job(
            conn, "job posting text", JobExtraction(job_title="AI Engineer", company_name=company_name, is_agency_posting=False)
        )
    finally:
        conn.close()
    return job_id


def test_skip_sponsor_check_sets_skipped_status_and_shared_reason(tmp_path):
    jobs_db = tmp_path / "jobs.db"
    job_id = _make_job(jobs_db, company_name="Fully Remote Co")

    _run(["skip-sponsor-check", str(job_id), "--db", str(jobs_db)])

    conn = connect_jobs(jobs_db)
    try:
        job = get_job(conn, job_id)
    finally:
        conn.close()

    assert job["sponsor_status"] == SKIPPED
    assert job["sponsor_reason"] == REMOTE_ANYWHERE_SKIP_REASON
    assert job["sponsor_matched_name"] == "Fully Remote Co"


def test_skip_sponsor_check_undo_clears_the_skip(tmp_path):
    jobs_db = tmp_path / "jobs.db"
    job_id = _make_job(jobs_db)

    _run(["skip-sponsor-check", str(job_id), "--db", str(jobs_db)])
    _run(["skip-sponsor-check", str(job_id), "--undo", "--db", str(jobs_db)])

    conn = connect_jobs(jobs_db)
    try:
        job = get_job(conn, job_id)
    finally:
        conn.close()

    assert job["sponsor_status"] is None
    assert job["sponsor_reason"] is None


def test_skip_sponsor_check_unknown_job_id_raises_system_exit(tmp_path):
    jobs_db = tmp_path / "jobs.db"
    connect_jobs(jobs_db).close()

    try:
        _run(["skip-sponsor-check", "999", "--db", str(jobs_db)])
    except SystemExit as exc:
        assert "999" in str(exc)
    else:
        raise AssertionError("expected SystemExit for an unknown job id")


def test_intake_remote_checkbox_skips_the_register_lookup_and_saves_skipped(streamlit_data_env):
    at = AppTest.from_file(_INTAKE_PY)
    at.session_state["raw_text"] = "AI Engineer, fully remote, work from anywhere."
    at.session_state["extraction"] = JobExtraction(
        job_title="AI Engineer",
        company_name="Totally Made Up Remote Co",  # deliberately absent from the (empty) sponsor register
        is_agency_posting=False,
    )
    at.run()

    checkbox = next(c for c in at.checkbox if "Remote from anywhere" in c.label)
    checkbox.check().run()

    # The register-only widgets (candidate picker, "choose a different
    # company", the status-update form) must not appear on the skip path -
    # there was never a register lookup to revise.
    assert not any("different company" in b.label for b in at.button)
    assert not any("Which company is this?" in md.value for md in at.markdown)

    assert any("SKIPPED" in md.value for md in at.markdown)

    save_button = next(b for b in at.button if "Save job" in b.label)
    save_button.click().run()

    assert len(at.error) == 0
    saved_job_id = at.session_state["saved_job_id"]

    conn = connect_jobs(streamlit_data_env["jobs_db"])
    try:
        job = get_job(conn, saved_job_id)
    finally:
        conn.close()

    assert job["sponsor_status"] == SKIPPED
    assert job["sponsor_reason"] == REMOTE_ANYWHERE_SKIP_REASON
    assert job["sponsor_matched_name"] == "Totally Made Up Remote Co"
