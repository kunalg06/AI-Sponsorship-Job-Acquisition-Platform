"""Proves views/digest.py actually renders jobs.digest.build_digest's
output - the CLI-level tests in test_jobs_cli.py cover the underlying
data, this covers the Streamlit surface reading the same source of truth.
Uses `AppTest` since views/*.py execute top-level code (DB connections,
widget rendering) as a side effect of import."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

from jobs.db import connect as connect_jobs
from jobs.db import insert_job, mark_applied, update_match_verdict, update_tailoring
from jobs.extract import JobExtraction

_VIEWS_DIR = Path(__file__).resolve().parent.parent / "views"
DIGEST_PY = str(_VIEWS_DIR / "digest.py")


def test_digest_page_shows_the_empty_state_on_a_fresh_db(streamlit_data_env):
    at = AppTest.from_file(DIGEST_PY)
    at.run()

    captions = [c.value for c in at.caption]
    assert "Nothing due right now." in captions
    assert "Nothing waiting on a decision." in captions
    assert "No repeated gaps yet." in captions
    assert any("Last outreach drafted: none yet" in c for c in captions)


def test_digest_page_shows_a_due_reminder(streamlit_data_env):
    jobs_db_path = streamlit_data_env["jobs_db"]
    conn = connect_jobs(jobs_db_path)
    try:
        job_id = insert_job(
            conn,
            "AI Engineer role.",
            JobExtraction(job_title="AI Engineer", company_name="Bending Spoons", is_agency_posting=False),
        )
        mark_applied(conn, job_id)
        when = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        conn.execute("UPDATE jobs SET applied_at = ? WHERE id = ?", (when, job_id))
        conn.commit()
    finally:
        conn.close()

    at = AppTest.from_file(DIGEST_PY)
    at.run()

    markdown_text = " ".join(m.value for m in at.markdown)
    assert f"#{job_id} AI Engineer" in markdown_text
    assert "day-3 follow-up due" in markdown_text


def test_digest_page_shows_a_queued_match(streamlit_data_env):
    jobs_db_path = streamlit_data_env["jobs_db"]
    conn = connect_jobs(jobs_db_path)
    try:
        job_id = insert_job(
            conn,
            "AI Engineer role.",
            JobExtraction(job_title="AI Engineer", company_name="Bending Spoons", is_agency_posting=False),
        )
        update_match_verdict(
            conn, job_id, score=88, verdict="strong_match", matched_skills=[], missing_skills=[], reasoning=""
        )
    finally:
        conn.close()

    at = AppTest.from_file(DIGEST_PY)
    at.run()

    markdown_text = " ".join(m.value for m in at.markdown)
    assert f"#{job_id} AI Engineer" in markdown_text
    assert "88/100 strong_match" in markdown_text


def test_digest_page_shows_a_recurring_gap_theme(streamlit_data_env):
    jobs_db_path = streamlit_data_env["jobs_db"]
    conn = connect_jobs(jobs_db_path)
    try:
        for _ in range(2):
            job_id = insert_job(
                conn,
                "AI Engineer role.",
                JobExtraction(job_title="AI Engineer", company_name="Bending Spoons", is_agency_posting=False),
            )
            update_tailoring(
                conn, job_id, tailor_hash="h", evidence_notes=[], portfolio_gaps=["no Kubernetes experience"], page_risk_warning=None
            )
    finally:
        conn.close()

    at = AppTest.from_file(DIGEST_PY)
    at.run()

    markdown_text = " ".join(m.value for m in at.markdown)
    assert "(2x) no Kubernetes experience" in markdown_text


def test_digest_page_shows_nonzero_momentum(streamlit_data_env):
    jobs_db_path = streamlit_data_env["jobs_db"]
    conn = connect_jobs(jobs_db_path)
    try:
        job_id = insert_job(
            conn,
            "AI Engineer role.",
            JobExtraction(job_title="AI Engineer", company_name="Bending Spoons", is_agency_posting=False),
        )
        mark_applied(conn, job_id)
    finally:
        conn.close()

    at = AppTest.from_file(DIGEST_PY)
    at.run()

    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Applications in the last 7 days"] == "1"
