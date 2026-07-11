from resume.db import (
    connect,
    get_latest_narrative,
    get_latest_profile,
    get_latest_raw_resume_text,
    insert_narrative,
    insert_profile,
)
from resume.extract import ResumeProfile


def test_get_latest_profile_returns_none_when_empty(tmp_path):
    conn = connect(tmp_path / "profile.db")
    try:
        assert get_latest_profile(conn) is None
    finally:
        conn.close()


def test_get_latest_raw_resume_text_returns_none_when_empty(tmp_path):
    conn = connect(tmp_path / "profile.db")
    try:
        assert get_latest_raw_resume_text(conn) is None
    finally:
        conn.close()


def test_get_latest_raw_resume_text_returns_most_recent(tmp_path):
    conn = connect(tmp_path / "profile.db")
    try:
        profile = ResumeProfile(
            seniority="senior", core_skills=["Python"], domains=["GenAI"], past_roles=["Senior ML Engineer"], summary="s"
        )
        insert_profile(conn, "old raw resume", profile)
        insert_profile(conn, "new raw resume", profile)

        assert get_latest_raw_resume_text(conn) == "new raw resume"
    finally:
        conn.close()


def test_insert_and_get_latest_profile_round_trips_all_fields(tmp_path):
    conn = connect(tmp_path / "profile.db")
    try:
        profile = ResumeProfile(
            full_name="Jane Doe",
            years_experience=5.0,
            seniority="senior",
            core_skills=["Python", "PyTorch", "LangGraph"],
            domains=["Generative AI", "NLP"],
            past_roles=["Senior ML Engineer at Acme"],
            summary="Senior ML engineer with 5 years building production LLM systems.",
        )
        insert_profile(conn, "raw resume text", profile)

        latest = get_latest_profile(conn)
        assert latest == profile
    finally:
        conn.close()


def test_get_latest_profile_returns_most_recently_inserted(tmp_path):
    conn = connect(tmp_path / "profile.db")
    try:
        old = ResumeProfile(
            seniority="mid", core_skills=["Python"], domains=["ML"], past_roles=["ML Engineer at X"], summary="old"
        )
        new = ResumeProfile(
            seniority="senior", core_skills=["Python", "LangGraph"], domains=["GenAI"], past_roles=["Senior ML Engineer at Y"], summary="new"
        )
        insert_profile(conn, "old resume", old)
        insert_profile(conn, "new resume", new)

        latest = get_latest_profile(conn)
        assert latest.summary == "new"
    finally:
        conn.close()


def test_get_latest_narrative_returns_none_when_empty(tmp_path):
    conn = connect(tmp_path / "profile.db")
    try:
        assert get_latest_narrative(conn) is None
    finally:
        conn.close()


def test_insert_and_get_latest_narrative(tmp_path):
    conn = connect(tmp_path / "profile.db")
    try:
        insert_narrative(conn, "old narrative")
        insert_narrative(conn, "new narrative")

        assert get_latest_narrative(conn) == "new narrative"
    finally:
        conn.close()
