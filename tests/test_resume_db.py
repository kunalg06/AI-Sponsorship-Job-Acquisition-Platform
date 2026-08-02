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


def _profile(**overrides) -> ResumeProfile:
    fields = dict(
        full_name="Jane Doe",
        years_experience=5.0,
        seniority="senior",
        core_skills=["Python", "PyTorch"],
        domains=["Generative AI"],
        past_roles=["Senior ML Engineer at Acme"],
        summary="Senior ML engineer.",
    )
    fields.update(overrides)
    return ResumeProfile(**fields)


def test_get_latest_profile_skips_later_profile_with_no_core_skills(tmp_path):
    """A skill-less row must not shadow the real resume.

    Regression: a test wrote a placeholder profile into the production db, and
    because the lookup was plain ORDER BY id DESC it won over the real resume.
    Match scoring then fed the LLM a blank candidate and stored 0/100 against
    86 jobs - silently, with no error and no NULL to signal the gap.
    """
    conn = connect(tmp_path / "profile.db")
    try:
        insert_profile(conn, "real resume", _profile())
        insert_profile(
            conn,
            "current resume text",
            _profile(full_name=None, core_skills=[], domains=[], past_roles=[], summary="current"),
        )

        latest = get_latest_profile(conn)

        assert latest is not None
        assert latest.full_name == "Jane Doe"
        assert latest.core_skills == ["Python", "PyTorch"]
    finally:
        conn.close()


def test_get_latest_profile_returns_none_when_every_profile_is_skill_less(tmp_path):
    """None (-> match_score stays NULL, row stays in the queue for a human) is
    the right answer here, not a profile that scores everything 0."""
    conn = connect(tmp_path / "profile.db")
    try:
        insert_profile(conn, "placeholder", _profile(core_skills=[]))

        assert get_latest_profile(conn) is None
    finally:
        conn.close()


def test_get_latest_profile_still_prefers_the_newest_usable_profile(tmp_path):
    """The skip must not turn into "always return the oldest"."""
    conn = connect(tmp_path / "profile.db")
    try:
        insert_profile(conn, "old", _profile(full_name="Old Name"))
        insert_profile(conn, "new", _profile(full_name="New Name"))

        latest = get_latest_profile(conn)

        assert latest is not None
        assert latest.full_name == "New Name"
    finally:
        conn.close()
