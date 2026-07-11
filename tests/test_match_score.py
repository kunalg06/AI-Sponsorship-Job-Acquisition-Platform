from unittest.mock import MagicMock

from jobs.match_score import (
    MATCH_THRESHOLD,
    STRONG_MATCH,
    WEAK_MATCH,
    MatchScore,
    match_verdict,
    score_job_match,
)
from resume.extract import ResumeProfile

_PROFILE = ResumeProfile(
    full_name="Jane Doe",
    years_experience=5.0,
    seniority="senior",
    core_skills=["Python", "PyTorch", "LangGraph"],
    domains=["Generative AI", "NLP"],
    past_roles=["Senior ML Engineer at Acme"],
    summary="Senior ML engineer with 5 years building production LLM systems.",
)


def test_score_job_match_calls_gemini_with_profile_and_job_text_and_parses_output():
    expected = MatchScore(
        score=82,
        matched_skills=["Python", "LangGraph"],
        missing_skills=["Kubernetes"],
        reasoning="Strong overlap on GenAI tooling and seniority.",
    )
    fake_response = MagicMock(output_text=expected.model_dump_json())
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = fake_response

    result = score_job_match("Senior GenAI Engineer job posting text", _PROFILE, client=fake_client)

    assert result == expected
    _, kwargs = fake_client.interactions.create.call_args
    sent_input = kwargs["input"]
    assert "Senior GenAI Engineer job posting text" in sent_input
    assert "LangGraph" in sent_input
    assert "senior" in sent_input


def test_match_verdict_threshold_boundaries():
    assert match_verdict(MATCH_THRESHOLD) == STRONG_MATCH
    assert match_verdict(MATCH_THRESHOLD + 1) == STRONG_MATCH
    assert match_verdict(MATCH_THRESHOLD - 1) == WEAK_MATCH
    assert match_verdict(0) == WEAK_MATCH
