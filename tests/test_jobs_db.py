from jobs.db import (
    connect,
    get_job,
    insert_job,
    list_applied_jobs,
    list_job_ids_and_company_names,
    list_jobs,
    list_legacy_tailored_rows,
    mark_applied,
    mark_discarded,
    mark_reminders_sent_through,
    update_employer_name,
    update_match_verdict,
    update_salary_verdict,
    update_sponsor_verdict,
    update_tailoring,
)
from jobs.extract import JobExtraction


def test_insert_and_get_job_round_trips_all_fields(tmp_path):
    db_path = tmp_path / "jobs.db"
    conn = connect(db_path)
    try:
        extraction = JobExtraction(
            job_title="GenAI Engineer",
            company_name=None,
            is_agency_posting=True,
            agency_name="Acme Recruitment",
            client_name=None,
            recruiter_name="Jane Doe",
            recruiter_contact="jane@acme-recruitment.example",
            location="London, UK",
            salary_raw="£70,000 - £90,000",
            employer_name_for_sponsor_check=None,
        )
        job_id = insert_job(conn, "raw pasted text here", extraction)

        row = get_job(conn, job_id)
        assert row["job_title"] == "GenAI Engineer"
        assert row["is_agency_posting"] == 1
        assert row["agency_name"] == "Acme Recruitment"
        assert row["client_name"] is None
        assert row["recruiter_contact"] == "jane@acme-recruitment.example"
        assert row["raw_text"] == "raw pasted text here"
    finally:
        conn.close()


def test_list_jobs_orders_newest_first(tmp_path):
    db_path = tmp_path / "jobs.db"
    conn = connect(db_path)
    try:
        for title in ("First Job", "Second Job", "Third Job"):
            extraction = JobExtraction(job_title=title, is_agency_posting=False)
            insert_job(conn, f"text for {title}", extraction)

        rows = list_jobs(conn, limit=10)
        assert [r["job_title"] for r in rows] == ["Third Job", "Second Job", "First Job"]
    finally:
        conn.close()


def test_update_sponsor_verdict_persists_all_fields(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        extraction = JobExtraction(job_title="AI Engineer", is_agency_posting=False)
        job_id = insert_job(conn, "raw text", extraction)

        update_sponsor_verdict(
            conn,
            job_id,
            status="confirmed",
            reason=None,
            matched_name="Acme AI Limited",
            rating="Worker (A rating)",
            route="Skilled Worker",
            town_city="London",
            county="Greater London",
        )

        row = get_job(conn, job_id)
        assert row["sponsor_status"] == "confirmed"
        assert row["sponsor_matched_name"] == "Acme AI Limited"
        assert row["sponsor_route"] == "Skilled Worker"
        assert row["sponsor_matched_town_city"] == "London"
        assert row["sponsor_matched_county"] == "Greater London"
        assert row["sponsor_checked_at"] is not None
    finally:
        conn.close()


def test_update_employer_name_clears_previous_sponsor_verdict(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        extraction = JobExtraction(job_title="AI Engineer", is_agency_posting=True, agency_name="Some Agency")
        job_id = insert_job(conn, "raw text", extraction)
        update_sponsor_verdict(
            conn, job_id, status="cannot_verify", reason="agency redacted client", matched_name=None, rating=None, route=None
        )

        update_employer_name(conn, job_id, "Real Client Ltd")

        row = get_job(conn, job_id)
        assert row["employer_name_for_sponsor_check"] == "Real Client Ltd"
        assert row["sponsor_status"] is None
        assert row["sponsor_reason"] is None
    finally:
        conn.close()


def test_update_salary_verdict_persists_all_fields(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        extraction = JobExtraction(job_title="AI Engineer", is_agency_posting=False, salary_raw="£75,000")
        job_id = insert_job(conn, "raw text", extraction)

        update_salary_verdict(
            conn,
            job_id,
            status="meets_threshold",
            reason="clears the threshold",
            offered=75_000,
            threshold=54_700,
            soc_code="2134",
            soc_job_type="Programmers and software development professionals",
        )

        row = get_job(conn, job_id)
        assert row["salary_status"] == "meets_threshold"
        assert row["salary_offered"] == 75_000
        assert row["salary_threshold"] == 54_700
        assert row["salary_soc_code"] == "2134"
        assert row["salary_checked_at"] is not None
    finally:
        conn.close()


def test_update_match_verdict_persists_all_fields(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        extraction = JobExtraction(job_title="AI Engineer", is_agency_posting=False)
        job_id = insert_job(conn, "raw text", extraction)

        update_match_verdict(
            conn,
            job_id,
            score=82,
            verdict="strong_match",
            matched_skills=["Python", "LangGraph"],
            missing_skills=["Kubernetes"],
            reasoning="Strong overlap on GenAI tooling.",
        )

        row = get_job(conn, job_id)
        assert row["match_score"] == 82
        assert row["match_verdict"] == "strong_match"
        assert row["match_matched_skills"] == '["Python", "LangGraph"]'
        assert row["match_reasoning"] == "Strong overlap on GenAI tooling."
        assert row["match_checked_at"] is not None
    finally:
        conn.close()


def test_connect_adds_missing_columns_to_a_pre_existing_table(tmp_path):
    import sqlite3

    db_path = tmp_path / "old.db"
    # Simulate a jobs.db created before match_* (and sponsor_/salary_) columns
    # existed - CREATE TABLE IF NOT EXISTS alone would never add them.
    bootstrap = sqlite3.connect(db_path)
    bootstrap.execute(
        """
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY,
            raw_text TEXT NOT NULL,
            job_title TEXT NOT NULL,
            company_name TEXT,
            is_agency_posting INTEGER NOT NULL,
            agency_name TEXT,
            client_name TEXT,
            recruiter_name TEXT,
            recruiter_contact TEXT,
            location TEXT,
            salary_raw TEXT,
            employer_name_for_sponsor_check TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    bootstrap.commit()
    bootstrap.close()

    conn = connect(db_path)
    try:
        extraction = JobExtraction(job_title="AI Engineer", is_agency_posting=False)
        job_id = insert_job(conn, "raw text", extraction)
        update_match_verdict(
            conn, job_id, score=90, verdict="strong_match", matched_skills=[], missing_skills=[], reasoning="ok"
        )
        row = get_job(conn, job_id)
        assert row["match_score"] == 90
    finally:
        conn.close()


def test_update_tailoring_persists_all_fields(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        extraction = JobExtraction(job_title="AI Engineer", is_agency_posting=False)
        job_id = insert_job(conn, "raw text", extraction)

        update_tailoring(
            conn,
            job_id,
            tailor_hash="abc123",
            evidence_notes=["backed by repo X"],
            portfolio_gaps=["no Kubernetes experience"],
            page_risk_warning="Tailored resume text is +120 chars vs the original - may push past 1 page.",
        )

        row = get_job(conn, job_id)
        assert row["tailor_hash"] == "abc123"
        assert row["tailor_evidence_notes"] == '["backed by repo X"]'
        assert row["tailor_page_risk_warning"] == "Tailored resume text is +120 chars vs the original - may push past 1 page."
        assert row["tailored_at"] is not None
    finally:
        conn.close()


def test_update_tailoring_persists_a_none_page_risk_warning(tmp_path):
    # A fresh generation that's well within the page budget stores no
    # warning at all - the round-trip must preserve None, not coerce it to
    # an empty string or the literal text "None".
    conn = connect(tmp_path / "jobs.db")
    try:
        extraction = JobExtraction(job_title="AI Engineer", is_agency_posting=False)
        job_id = insert_job(conn, "raw text", extraction)

        update_tailoring(
            conn,
            job_id,
            tailor_hash="abc123",
            evidence_notes=[],
            portfolio_gaps=[],
            page_risk_warning=None,
        )

        row = get_job(conn, job_id)
        assert row["tailor_page_risk_warning"] is None
    finally:
        conn.close()


def test_list_legacy_tailored_rows_returns_rows_with_db_resident_tailored_text(tmp_path):
    # Simulate a jobs.db created before this refactor - `tailored_resume`/
    # `cover_letter` still exist as real columns with real data in it, since
    # `_ensure_columns()` only adds columns, never drops them.
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = connect(db_path)
    job_id = insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
    other_job_id = insert_job(conn, "raw text 2", JobExtraction(job_title="ML Engineer", is_agency_posting=False))
    conn.close()

    # Manually add the legacy columns and populate one row, as if this DB
    # predates the refactor (SCHEMA no longer declares them, so a fresh
    # connect() never creates them).
    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute("ALTER TABLE jobs ADD COLUMN tailored_resume TEXT")
    raw_conn.execute("ALTER TABLE jobs ADD COLUMN cover_letter TEXT")
    raw_conn.execute(
        "UPDATE jobs SET tailored_resume = ?, cover_letter = ? WHERE id = ?",
        ("LEGACY TAILORED RESUME", "LEGACY COVER LETTER", job_id),
    )
    raw_conn.commit()
    raw_conn.close()

    conn = connect(db_path)
    try:
        rows = list_legacy_tailored_rows(conn)
        assert [r["id"] for r in rows] == [job_id]
        assert rows[0]["tailored_resume"] == "LEGACY TAILORED RESUME"
        assert rows[0]["cover_letter"] == "LEGACY COVER LETTER"
        assert other_job_id not in [r["id"] for r in rows]
    finally:
        conn.close()


def test_list_legacy_tailored_rows_returns_empty_on_a_fresh_db_with_no_legacy_columns(tmp_path):
    # A brand new DB created after this refactor never gets the
    # tailored_resume/cover_letter columns at all - querying them directly
    # would be a hard sqlite3.OperationalError, so this must guard via
    # PRAGMA table_info and return [] instead of raising.
    conn = connect(tmp_path / "fresh.db")
    try:
        insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
        assert list_legacy_tailored_rows(conn) == []
    finally:
        conn.close()


def test_list_job_ids_and_company_names_returns_all_jobs(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        id_with_company = insert_job(
            conn, "raw text", JobExtraction(job_title="AI Engineer", company_name="Acme AI", is_agency_posting=False)
        )
        id_without_company = insert_job(
            conn, "raw text 2", JobExtraction(job_title="ML Engineer", company_name=None, is_agency_posting=False)
        )

        rows = {r["id"]: r["company_name"] for r in list_job_ids_and_company_names(conn)}
        assert rows[id_with_company] == "Acme AI"
        assert rows[id_without_company] is None
    finally:
        conn.close()


def test_mark_applied_sets_status_and_start_time(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        job_id = insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
        mark_applied(conn, job_id)

        row = get_job(conn, job_id)
        assert row["applied_status"] == "applied"
        assert row["applied_at"] is not None
        assert row["reminder_3_sent_at"] is None
    finally:
        conn.close()


def test_mark_discarded_sets_status(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        job_id = insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
        mark_discarded(conn, job_id)

        row = get_job(conn, job_id)
        assert row["applied_status"] == "discarded"
    finally:
        conn.close()


def test_mark_reminders_sent_through_sets_only_columns_up_to_milestone(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        job_id = insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
        mark_applied(conn, job_id)
        mark_reminders_sent_through(conn, job_id, 7)

        row = get_job(conn, job_id)
        assert row["reminder_3_sent_at"] is not None
        assert row["reminder_7_sent_at"] is not None
        assert row["reminder_14_sent_at"] is None
    finally:
        conn.close()


def test_list_applied_jobs_only_returns_applied(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        applied_id = insert_job(conn, "raw text", JobExtraction(job_title="Applied Job", is_agency_posting=False))
        pending_id = insert_job(conn, "raw text", JobExtraction(job_title="Pending Job", is_agency_posting=False))
        discarded_id = insert_job(conn, "raw text", JobExtraction(job_title="Discarded Job", is_agency_posting=False))
        mark_applied(conn, applied_id)
        mark_discarded(conn, discarded_id)

        applied = list_applied_jobs(conn)
        assert [row["id"] for row in applied] == [applied_id]
        assert pending_id not in [row["id"] for row in applied]
    finally:
        conn.close()
