"""Tests for views/automate.py - the Automate review queue for Indeed-sourced
postings staged via `jobs stage-indeed`. The CLI-level tests in
test_jobs_cli.py/test_jobs_db.py cover the underlying data; this covers the
Streamlit surface reading (and mutating) that same source of truth. Uses
`AppTest` since views/*.py execute top-level code (DB connections, widget
rendering) as a side effect of import - same pattern as
test_views_error_display.py/test_digest_view.py.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from jobs.db import connect as connect_jobs
from jobs.db import insert_job, list_discovery_queue, update_match_verdict, update_salary_verdict, update_sponsor_verdict
from jobs.extract import JobExtraction

_VIEWS_DIR = Path(__file__).resolve().parent.parent / "views"
AUTOMATE_PY = str(_VIEWS_DIR / "automate.py")


def _stage_indeed_row(jobs_db_path, *, source_job_id: str = "indeed-1") -> int:
    conn = connect_jobs(jobs_db_path)
    try:
        return insert_job(
            conn,
            "Full Indeed posting text.",
            JobExtraction(
                job_title="AI Engineer",
                company_name="Acme AI",
                is_agency_posting=False,
                location="London, UK",
            ),
            source="indeed",
            source_job_id=source_job_id,
            source_posted_at="2026-07-20",
            apply_url="https://to.indeed.com/abc123",
        )
    finally:
        conn.close()


def test_automate_page_shows_the_empty_state_with_no_unreviewed_rows(streamlit_data_env):
    at = AppTest.from_file(AUTOMATE_PY)
    at.run()

    assert not at.exception
    assert len(at.info) == 1
    assert "nothing waiting" in at.info[0].value.lower()


def test_automate_page_renders_a_seeded_row_with_badges_and_apply_link(streamlit_data_env):
    jobs_db_path = streamlit_data_env["jobs_db"]
    job_id = _stage_indeed_row(jobs_db_path)
    conn = connect_jobs(jobs_db_path)
    try:
        update_sponsor_verdict(
            conn,
            job_id,
            status="confirmed",
            reason="Holds a valid Skilled Worker sponsor licence.",
            matched_name="Acme AI Limited",
            rating="Worker (A rating)",
            route="Skilled Worker",
        )
        update_salary_verdict(
            conn,
            job_id,
            status="meets_threshold",
            reason="Clears the threshold.",
            offered=75_000,
            threshold=54_700,
            soc_code="2134",
            soc_job_type="Programmers and software development professionals",
        )
        update_match_verdict(
            conn, job_id, score=82, verdict="strong_match", matched_skills=["Python"], missing_skills=[], reasoning="Good fit."
        )
    finally:
        conn.close()

    at = AppTest.from_file(AUTOMATE_PY)
    at.run()

    assert not at.exception
    assert len(at.info) == 0  # not the empty state

    subheaders = [s.value for s in at.subheader]
    assert "AI Engineer" in subheaders

    markdown_text = " ".join(m.value for m in at.markdown)
    assert "Acme AI" in markdown_text
    assert "London, UK" in markdown_text
    assert "2026-07-20" in markdown_text
    assert "CONFIRMED" in markdown_text
    assert "Acme AI Limited" in markdown_text
    assert "MEETS_THRESHOLD" in markdown_text
    assert "82/100" in markdown_text

    assert at.button(key=f"mark_reviewed_{job_id}") is not None


def test_automate_page_no_match_score_shows_unavailable_caption_instead_of_hiding_the_row(streamlit_data_env):
    # No profile was on file when this hypothetical row was staged -
    # match_score stays NULL, matching _run_match_score's own no-profile
    # skip. The row must still appear (never hard-filtered), just without a
    # match badge.
    jobs_db_path = streamlit_data_env["jobs_db"]
    _stage_indeed_row(jobs_db_path)

    at = AppTest.from_file(AUTOMATE_PY)
    at.run()

    assert not at.exception
    captions = [c.value for c in at.caption]
    assert any("match score unavailable" in c.lower() for c in captions)


def test_mark_reviewed_removes_the_row_from_the_queue_but_leaves_it_intact_in_the_db(streamlit_data_env):
    jobs_db_path = streamlit_data_env["jobs_db"]
    job_id = _stage_indeed_row(jobs_db_path)

    at = AppTest.from_file(AUTOMATE_PY)
    at.run()
    assert len(at.info) == 0  # the row is present before reviewing

    at.button(key=f"mark_reviewed_{job_id}").click().run()

    assert not at.exception
    assert len(at.info) == 1
    assert "nothing waiting" in at.info[0].value.lower()

    # Confirms CAP-level behavior directly against the DB too, not just the
    # re-rendered page: the row itself is untouched (still fully visible via
    # jobs.db.get_job/Jobs List) - only discovery_reviewed_at changed.
    conn = connect_jobs(jobs_db_path)
    try:
        assert list_discovery_queue(conn) == []
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    assert row["discovery_reviewed_at"] is not None
    assert row["job_title"] == "AI Engineer"
    assert row["source"] == "indeed"


def test_multiple_unreviewed_rows_shows_the_correct_count_caption(streamlit_data_env):
    jobs_db_path = streamlit_data_env["jobs_db"]
    _stage_indeed_row(jobs_db_path, source_job_id="indeed-1")
    _stage_indeed_row(jobs_db_path, source_job_id="indeed-2")

    at = AppTest.from_file(AUTOMATE_PY)
    at.run()

    assert not at.exception
    captions = [c.value for c in at.caption]
    # The caption names displayed-vs-total explicitly: a capped list must never
    # read as the whole queue (see DISPLAY_LIMIT in views/automate.py).
    assert any("Showing 2 of 2 unreviewed candidates" in c for c in captions)


def test_automate_page_shows_missing_and_matched_skills_so_a_low_score_is_auditable(streamlit_data_env):
    """The score alone is not a verdict the user can check. This page is where
    triage happens, so the evidence behind the number has to be visible here -
    not only on Jobs List."""
    jobs_db_path = streamlit_data_env["jobs_db"]
    job_id = _stage_indeed_row(jobs_db_path)
    conn = connect_jobs(jobs_db_path)
    try:
        update_match_verdict(
            conn,
            job_id,
            score=48,
            verdict="weak_match",
            matched_skills=["Python", "SQL"],
            missing_skills=["Kubernetes", "Terraform"],
            reasoning="Strong Python overlap but no infrastructure experience shown.",
        )
    finally:
        conn.close()

    at = AppTest.from_file(AUTOMATE_PY)
    at.run()

    assert not at.exception
    markdown_text = " ".join(m.value for m in at.markdown)
    assert "48/100" in markdown_text
    assert "Kubernetes" in markdown_text
    assert "Terraform" in markdown_text
    assert "Python" in markdown_text
    captions = " ".join(c.value for c in at.caption)
    assert "no infrastructure experience shown" in captions


def test_automate_page_flags_a_score_that_has_no_supporting_detail_at_all(streamlit_data_env):
    """A score with empty skills lists and empty reasoning is what a truncated
    description produces - it must be called out as unverified rather than
    rendered as a confident verdict, which is how a whole queue of bogus 0/100s
    went unnoticed for a day."""
    jobs_db_path = streamlit_data_env["jobs_db"]
    job_id = _stage_indeed_row(jobs_db_path)
    conn = connect_jobs(jobs_db_path)
    try:
        update_match_verdict(
            conn, job_id, score=0, verdict="weak_match", matched_skills=[], missing_skills=[], reasoning=""
        )
    finally:
        conn.close()

    at = AppTest.from_file(AUTOMATE_PY)
    at.run()

    assert not at.exception
    captions = " ".join(c.value for c in at.caption).lower()
    assert "unverified" in captions


def test_automate_page_survives_malformed_skills_json_without_crashing(streamlit_data_env):
    """A review queue must still render every other field of a row even if one
    column is unreadable."""
    jobs_db_path = streamlit_data_env["jobs_db"]
    job_id = _stage_indeed_row(jobs_db_path)
    conn = connect_jobs(jobs_db_path)
    try:
        update_match_verdict(
            conn, job_id, score=70, verdict="strong_match", matched_skills=[], missing_skills=[], reasoning="ok"
        )
        with conn:
            conn.execute("UPDATE jobs SET match_missing_skills = ? WHERE id = ?", ("{not json", job_id))
    finally:
        conn.close()

    at = AppTest.from_file(AUTOMATE_PY)
    at.run()

    assert not at.exception
    assert "70/100" in " ".join(m.value for m in at.markdown)


def _seed_scored_row(jobs_db_path, *, source_job_id: str, score: int | None, title: str = "AI Engineer") -> int:
    """Stage one Indeed row and give it `score` (None leaves match_score NULL)."""
    conn = connect_jobs(jobs_db_path)
    try:
        job_id = insert_job(
            conn,
            "Full Indeed posting text.",
            JobExtraction(
                job_title=title,
                company_name="Acme AI",
                is_agency_posting=False,
                location="London, UK",
            ),
            source="indeed",
            source_job_id=source_job_id,
            source_posted_at="2026-07-20",
            apply_url="https://to.indeed.com/abc123",
        )
        if score is not None:
            update_match_verdict(
                conn, job_id, score=score, verdict="strong_match", matched_skills=[], missing_skills=[], reasoning="."
            )
        return job_id
    finally:
        conn.close()


def test_list_discovery_queue_limit_none_returns_the_whole_queue(tmp_path):
    """The display cap must not become an action cap - see the whole-queue
    comment on list_discovery_queue. 25 rows is past the default 20."""
    jobs_db_path = str(tmp_path / "jobs.db")
    for i in range(25):
        _seed_scored_row(jobs_db_path, source_job_id=f"indeed-{i}", score=90)

    conn = connect_jobs(jobs_db_path)
    try:
        assert len(list_discovery_queue(conn)) == 20  # unchanged default
        assert len(list_discovery_queue(conn, limit=None)) == 25
    finally:
        conn.close()


def test_bulk_triage_discards_below_threshold_rows_beyond_the_displayed_page(streamlit_data_env):
    """The regression this feature exists to prevent: triaging a 25-row queue
    while only 20 are rendered must still discard the low scorers sitting
    below the fold, not silently leave them queued."""
    jobs_db_path = streamlit_data_env["jobs_db"]
    high = [_seed_scored_row(jobs_db_path, source_job_id=f"hi-{i}", score=90) for i in range(20)]
    low = [_seed_scored_row(jobs_db_path, source_job_id=f"lo-{i}", score=40) for i in range(5)]

    at = AppTest.from_file(AUTOMATE_PY)
    at.run()
    at.button(key="triage_preview").click().run()
    at.button(key="triage_apply").click().run()

    assert not at.exception
    conn = connect_jobs(jobs_db_path)
    try:
        remaining = {row["id"] for row in list_discovery_queue(conn, limit=None)}
    finally:
        conn.close()
    assert remaining == set(high), "every below-threshold row should be discarded, including the un-rendered ones"
    assert not (remaining & set(low))


def test_bulk_triage_never_discards_an_unscored_row(streamlit_data_env):
    """A NULL match_score is an absence of information, not a low score -
    partition_discovery_queue's third bucket exists for exactly this."""
    jobs_db_path = streamlit_data_env["jobs_db"]
    unscored = _seed_scored_row(jobs_db_path, source_job_id="none-1", score=None)
    low = _seed_scored_row(jobs_db_path, source_job_id="lo-1", score=30)

    at = AppTest.from_file(AUTOMATE_PY)
    at.run()
    at.button(key="triage_preview").click().run()
    at.button(key="triage_apply").click().run()

    assert not at.exception
    conn = connect_jobs(jobs_db_path)
    try:
        remaining = {row["id"] for row in list_discovery_queue(conn, limit=None)}
    finally:
        conn.close()
    assert unscored in remaining
    assert low not in remaining


def test_bulk_triage_preview_alone_changes_nothing(streamlit_data_env):
    """Preview and commit are two separate actions - previewing must be a
    pure read, since data/*.db has no backup."""
    jobs_db_path = streamlit_data_env["jobs_db"]
    low = _seed_scored_row(jobs_db_path, source_job_id="lo-1", score=30)

    at = AppTest.from_file(AUTOMATE_PY)
    at.run()
    at.button(key="triage_preview").click().run()

    assert not at.exception
    conn = connect_jobs(jobs_db_path)
    try:
        remaining = {row["id"] for row in list_discovery_queue(conn, limit=None)}
    finally:
        conn.close()
    assert low in remaining, "preview must not mutate anything"
