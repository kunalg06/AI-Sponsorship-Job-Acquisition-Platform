from unittest.mock import MagicMock

import httpx
import pytest
from google.genai._gaos.lib import compat_errors

from jobs.match_score import (
    DISCOVERY_TRIAGE_THRESHOLD,
    MATCH_THRESHOLD,
    STRONG_MATCH,
    WEAK_MATCH,
    MatchScore,
    match_verdict,
    partition_discovery_queue,
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


def test_score_job_match_raises_system_exit_on_connection_error():
    fake_client = MagicMock()
    original = compat_errors.APIConnectionError(
        message="Connection refused", request=httpx.Request("POST", "https://example.com")
    )
    fake_client.interactions.create.side_effect = original

    with pytest.raises(SystemExit, match="Match scoring failed: Connection refused") as exc_info:
        score_job_match("job posting text", _PROFILE, client=fake_client)
    assert exc_info.value.__cause__ is original


def test_match_verdict_threshold_boundaries():
    assert match_verdict(MATCH_THRESHOLD) == STRONG_MATCH
    assert match_verdict(MATCH_THRESHOLD + 1) == STRONG_MATCH
    assert match_verdict(MATCH_THRESHOLD - 1) == WEAK_MATCH
    assert match_verdict(0) == WEAK_MATCH


def _row(job_id: int, score):
    return {"id": job_id, "match_score": score, "job_title": f"Job {job_id}", "company_name": "Acme"}


def test_partition_discovery_queue_keeps_scores_at_and_above_the_threshold():
    keep, discard, unscored = partition_discovery_queue(
        [_row(1, 92), _row(2, 85), _row(3, 84)], threshold=85
    )
    assert [r["id"] for r in keep] == [1, 2]
    assert [r["id"] for r in discard] == [3]
    assert unscored == []


def test_partition_discovery_queue_never_discards_an_unscored_row():
    """A NULL match_score means scoring was skipped (no resume on file), not
    that the job scored badly - discarding those would throw away rows nobody
    has actually judged."""
    keep, discard, unscored = partition_discovery_queue([_row(1, None), _row(2, 10)], threshold=85)
    assert keep == []
    assert [r["id"] for r in discard] == [2]
    assert [r["id"] for r in unscored] == [1]


def test_partition_discovery_queue_treats_zero_as_a_real_score_not_a_missing_one():
    """0/100 is a verdict, unlike NULL - the truncated-description incident
    produced a queue full of genuine-looking 0s, so the two must not collapse."""
    _, discard, unscored = partition_discovery_queue([_row(1, 0)], threshold=85)
    assert [r["id"] for r in discard] == [1]
    assert unscored == []


def test_partition_discovery_queue_handles_an_empty_queue():
    assert partition_discovery_queue([], threshold=85) == ([], [], [])


def test_discovery_triage_threshold_is_stricter_than_the_advisory_match_threshold():
    """85 is the act-on-its-own line; 70 is the advisory 'worth tailoring' line
    shown in the UI. Collapsing them would make the queue auto-discard rows the
    UI still calls a strong match."""
    assert DISCOVERY_TRIAGE_THRESHOLD > MATCH_THRESHOLD
