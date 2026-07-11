from unittest.mock import MagicMock

import pytest

from jobs.outreach import (
    EMAIL,
    LINKEDIN_NOTE,
    LINKEDIN_NOTE_MAX_CHARS,
    MODEL,
    OutreachDraft,
    OutreachLengthError,
    draft_outreach_message,
)


def _fake_client(message_text: str) -> MagicMock:
    expected = OutreachDraft(message=message_text)
    fake_response = MagicMock(output_text=expected.model_dump_json())
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = fake_response
    return fake_client


def test_draft_outreach_message_email_has_no_length_constraint():
    long_message = "Dear Sarah, " + ("x" * 500)
    fake_client = _fake_client(long_message)

    result = draft_outreach_message(
        EMAIL,
        "job posting text",
        "Acme AI Ltd",
        "Sarah Cole",
        "Recruiter",
        "why AI, why UK, why me narrative",
        "candidate resume text",
        client=fake_client,
    )

    assert result.message == long_message
    _, kwargs = fake_client.interactions.create.call_args
    assert kwargs["model"] == MODEL
    assert "Sarah Cole" in kwargs["input"]
    assert "Acme AI Ltd" in kwargs["input"]


def test_draft_outreach_message_linkedin_note_within_limit_succeeds():
    short_message = "Hi Sarah, I'd love to connect about the GenAI role - my background is a strong fit."
    assert len(short_message) <= LINKEDIN_NOTE_MAX_CHARS
    fake_client = _fake_client(short_message)

    result = draft_outreach_message(
        LINKEDIN_NOTE, "job text", "Acme AI Ltd", "Sarah Cole", None, "narrative", "resume", client=fake_client
    )

    assert result.message == short_message


def test_draft_outreach_message_linkedin_note_over_limit_raises():
    over_limit_message = "x" * (LINKEDIN_NOTE_MAX_CHARS + 1)
    fake_client = _fake_client(over_limit_message)

    with pytest.raises(OutreachLengthError) as exc_info:
        draft_outreach_message(
            LINKEDIN_NOTE, "job text", "Acme AI Ltd", "Sarah Cole", None, "narrative", "resume", client=fake_client
        )

    assert exc_info.value.char_count == LINKEDIN_NOTE_MAX_CHARS + 1
    assert exc_info.value.draft_text == over_limit_message


def test_draft_outreach_message_rejects_unknown_channel():
    with pytest.raises(ValueError):
        draft_outreach_message(
            "carrier_pigeon", "job text", "Acme AI Ltd", "Sarah Cole", None, "narrative", "resume"
        )
