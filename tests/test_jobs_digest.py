from datetime import datetime, timedelta, timezone

from jobs.db import connect, insert_job, list_applied_jobs, mark_applied, mark_discarded, update_match_verdict, update_tailoring
from jobs.digest import build_digest, compute_momentum, list_due_reminders, list_match_queue, list_recurring_portfolio_gaps
from jobs.extract import JobExtraction
from jobs.outreach_db import ensure_schema as ensure_outreach_schema
from jobs.outreach_db import insert_outreach_message


def _job(conn, **kwargs):
    defaults = dict(job_title="AI Engineer", is_agency_posting=False)
    defaults.update(kwargs)
    return insert_job(conn, "raw text", JobExtraction(**defaults))


def _backdate_applied_at(conn, job_id, days_ago):
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    conn.execute("UPDATE jobs SET applied_at = ? WHERE id = ?", (when, job_id))
    conn.commit()


def test_list_due_reminders_returns_most_overdue_first(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        soon_due = _job(conn, company_name="Recently Applied")
        mark_applied(conn, soon_due)
        _backdate_applied_at(conn, soon_due, 4)  # day-3 milestone due

        long_overdue = _job(conn, company_name="Long Overdue")
        mark_applied(conn, long_overdue)
        _backdate_applied_at(conn, long_overdue, 10)  # day-7 milestone due

        reminders = list_due_reminders(list_applied_jobs(conn))

        assert [r.job_id for r in reminders] == [long_overdue, soon_due]
        assert reminders[0].milestone == 7
        assert reminders[1].milestone == 3
    finally:
        conn.close()


def test_list_due_reminders_excludes_jobs_not_yet_due(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        job_id = _job(conn)
        mark_applied(conn, job_id)
        _backdate_applied_at(conn, job_id, 1)  # nothing due until day 3

        assert list_due_reminders(list_applied_jobs(conn)) == []
    finally:
        conn.close()


def test_list_due_reminders_ranks_by_overdue_relative_to_own_milestone(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        # Applied longest ago, but its day-14 reminder is only 1 day overdue.
        old_job_barely_overdue = _job(conn, company_name="Old But Barely Overdue")
        mark_applied(conn, old_job_barely_overdue)
        _backdate_applied_at(conn, old_job_barely_overdue, 15)  # day-14 milestone, 1 day overdue

        # Applied more recently, but its day-3 reminder is 3 days overdue.
        newer_job_very_overdue = _job(conn, company_name="Newer But Very Overdue")
        mark_applied(conn, newer_job_very_overdue)
        _backdate_applied_at(conn, newer_job_very_overdue, 6)  # day-3 milestone, 3 days overdue

        reminders = list_due_reminders(list_applied_jobs(conn))

        assert [r.job_id for r in reminders] == [newer_job_very_overdue, old_job_barely_overdue]
    finally:
        conn.close()


def test_list_match_queue_excludes_decided_and_unscored_jobs(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        undecided = _job(conn, company_name="Undecided Co")
        update_match_verdict(conn, undecided, score=80, verdict="strong_match", matched_skills=[], missing_skills=[], reasoning="")

        already_applied = _job(conn, company_name="Already Applied Co")
        update_match_verdict(conn, already_applied, score=90, verdict="strong_match", matched_skills=[], missing_skills=[], reasoning="")
        mark_applied(conn, already_applied)

        _job(conn, company_name="Never Scored Co")  # no match_score at all

        queue = list_match_queue(conn)

        assert [q.job_id for q in queue] == [undecided]
    finally:
        conn.close()


def test_list_match_queue_excludes_a_discarded_scored_job(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        discarded = _job(conn, company_name="Discarded Co")
        update_match_verdict(conn, discarded, score=85, verdict="strong_match", matched_skills=[], missing_skills=[], reasoning="")
        mark_discarded(conn, discarded)

        queue = list_match_queue(conn)

        assert queue == []
    finally:
        conn.close()


def test_list_match_queue_orders_by_score_descending(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        lower = _job(conn, company_name="Lower Score Co")
        update_match_verdict(conn, lower, score=72, verdict="strong_match", matched_skills=[], missing_skills=[], reasoning="")
        higher = _job(conn, company_name="Higher Score Co")
        update_match_verdict(conn, higher, score=95, verdict="strong_match", matched_skills=[], missing_skills=[], reasoning="")

        queue = list_match_queue(conn)

        assert [q.job_id for q in queue] == [higher, lower]
    finally:
        conn.close()


def test_list_recurring_portfolio_gaps_only_includes_gaps_seen_twice_or_more(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        for _ in range(2):
            job_id = _job(conn)
            update_tailoring(
                conn, job_id, tailor_hash="h", evidence_notes=[], portfolio_gaps=["no Kubernetes experience"], page_risk_warning=None
            )
        once_only = _job(conn)
        update_tailoring(
            conn, once_only, tailor_hash="h", evidence_notes=[], portfolio_gaps=["no AWS experience"], page_risk_warning=None
        )

        themes = list_recurring_portfolio_gaps(conn)

        assert [t.gap for t in themes] == ["no Kubernetes experience"]
        assert themes[0].count == 2
    finally:
        conn.close()


def test_list_recurring_portfolio_gaps_strips_whitespace_before_grouping(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        job_a = _job(conn)
        update_tailoring(conn, job_a, tailor_hash="h", evidence_notes=[], portfolio_gaps=["no Kubernetes experience"], page_risk_warning=None)
        job_b = _job(conn)
        update_tailoring(conn, job_b, tailor_hash="h", evidence_notes=[], portfolio_gaps=["  no Kubernetes experience  "], page_risk_warning=None)

        themes = list_recurring_portfolio_gaps(conn)

        assert themes == [themes[0]]  # single theme, not two near-duplicates
        assert themes[0].gap == "no Kubernetes experience"
        assert themes[0].count == 2
    finally:
        conn.close()


def test_list_recurring_portfolio_gaps_does_not_count_a_single_jobs_own_duplicate_gap_as_recurring(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        only_job = _job(conn)
        update_tailoring(
            conn,
            only_job,
            tailor_hash="h",
            evidence_notes=[],
            portfolio_gaps=["no Kubernetes experience", "no Kubernetes experience"],
            page_risk_warning=None,
        )

        themes = list_recurring_portfolio_gaps(conn)

        assert themes == []
    finally:
        conn.close()


def test_compute_momentum_counts_only_applications_within_the_last_7_days(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        recent = _job(conn, company_name="Recent Co")
        mark_applied(conn, recent)
        _backdate_applied_at(conn, recent, 2)

        stale = _job(conn, company_name="Stale Co")
        mark_applied(conn, stale)
        _backdate_applied_at(conn, stale, 10)

        momentum = compute_momentum(conn)

        assert momentum.applications_last_7_days == 1
    finally:
        conn.close()


def test_compute_momentum_counts_an_applied_then_discarded_job_within_the_window(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        job_id = _job(conn, company_name="Applied Then Discarded Co")
        mark_applied(conn, job_id)
        _backdate_applied_at(conn, job_id, 2)
        mark_discarded(conn, job_id)  # does not clear applied_at

        momentum = compute_momentum(conn)

        assert momentum.applications_last_7_days == 1
    finally:
        conn.close()


def test_compute_momentum_reports_none_yet_on_a_fresh_db_with_no_outreach_table(tmp_path):
    # outreach_messages isn't part of jobs.db's base schema - ensure_schema()
    # is never called for it on a plain connect(), so this also proves
    # compute_momentum's own internal ensure_outreach_schema call prevents
    # a "no such table" crash.
    conn = connect(tmp_path / "jobs.db")
    try:
        momentum = compute_momentum(conn)

        assert momentum.applications_last_7_days == 0
        assert momentum.last_outreach_drafted_at is None
        assert momentum.last_tailored_at is None
    finally:
        conn.close()


def test_compute_momentum_reports_the_most_recent_outreach_draft(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        ensure_outreach_schema(conn)
        job_id = _job(conn)
        insert_outreach_message(conn, job_id, contact_id=None, contact_name="Sarah", channel="email", message="Hi!")

        momentum = compute_momentum(conn)

        assert momentum.last_outreach_drafted_at is not None
    finally:
        conn.close()


def test_build_digest_combines_all_four_sections(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    try:
        due_job = _job(conn, company_name="Due Co")
        mark_applied(conn, due_job)
        _backdate_applied_at(conn, due_job, 5)

        queued_job = _job(conn, company_name="Queued Co")
        update_match_verdict(conn, queued_job, score=88, verdict="strong_match", matched_skills=[], missing_skills=[], reasoning="")

        result = build_digest(conn)

        assert len(result.due_reminders) == 1
        assert len(result.match_queue) == 1
        assert result.gap_themes == []
        assert result.momentum.applications_last_7_days == 1
    finally:
        conn.close()
