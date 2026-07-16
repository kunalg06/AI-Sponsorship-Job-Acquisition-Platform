from unittest.mock import MagicMock

import httpx
import pytest
from google.genai import errors as genai_errors

from jobs.tailor import MODEL, TailoredApplication, compute_tailor_hash, generate_tailored_application
from resume.github_evidence import RepoEvidence


def test_compute_tailor_hash_is_deterministic_and_sensitive_to_either_input():
    h1 = compute_tailor_hash("resume text", "job text")
    h2 = compute_tailor_hash("resume text", "job text")
    h3 = compute_tailor_hash("different resume", "job text")
    h4 = compute_tailor_hash("resume text", "different job")

    assert h1 == h2
    assert h1 != h3
    assert h1 != h4


def test_generate_tailored_application_includes_repo_evidence_and_job_text_in_input():
    expected = TailoredApplication(
        tailored_resume="TAILORED RESUME TEXT",
        cover_letter="COVER LETTER TEXT",
        evidence_notes=["RAG claim backed by rag-knowledge-assistant repo"],
        portfolio_gaps=["No Kubernetes experience shown"],
    )
    fake_response = MagicMock(output_text=expected.model_dump_json())
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = fake_response

    repos = [
        RepoEvidence(
            name="rag-knowledge-assistant",
            url="https://github.com/kunalg06/rag-knowledge-assistant",
            description="RAG platform using LangChain and FAISS",
            language="Python",
            stars=3,
        )
    ]

    result = generate_tailored_application(
        "Senior GenAI Engineer job posting text",
        "Acme AI Ltd",
        "candidate's full resume text",
        repos,
        client=fake_client,
    )

    assert result == expected
    _, kwargs = fake_client.interactions.create.call_args
    assert kwargs["model"] == MODEL
    sent_input = kwargs["input"]
    assert "Senior GenAI Engineer job posting text" in sent_input
    assert "candidate's full resume text" in sent_input
    assert "rag-knowledge-assistant" in sent_input
    assert "Acme AI Ltd" in sent_input


def test_generate_tailored_application_handles_no_repo_evidence():
    expected = TailoredApplication(
        tailored_resume="TAILORED RESUME TEXT",
        cover_letter="COVER LETTER TEXT",
        evidence_notes=[],
        portfolio_gaps=[],
    )
    fake_response = MagicMock(output_text=expected.model_dump_json())
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = fake_response

    result = generate_tailored_application(
        "job text", None, "resume text", [], client=fake_client
    )

    assert result == expected
    _, kwargs = fake_client.interactions.create.call_args
    assert "no public repos found" in kwargs["input"]


def test_generate_tailored_application_raises_system_exit_on_api_error():
    fake_client = MagicMock()
    original = genai_errors.APIError(500, {"message": "Internal error", "status": "INTERNAL"})
    fake_client.interactions.create.side_effect = original

    with pytest.raises(SystemExit, match="Tailoring generation failed") as exc_info:
        generate_tailored_application("job text", "Acme", "resume text", [], client=fake_client)
    assert "Internal error" in str(exc_info.value)
    assert exc_info.value.__cause__ is original


def test_generate_tailored_application_raises_system_exit_on_network_error():
    fake_client = MagicMock()
    original = httpx.ConnectError("Connection refused")
    fake_client.interactions.create.side_effect = original

    with pytest.raises(SystemExit, match="Tailoring generation failed") as exc_info:
        generate_tailored_application("job text", "Acme", "resume text", [], client=fake_client)
    assert "Connection refused" in str(exc_info.value)
    assert exc_info.value.__cause__ is original


def test_generate_tailored_application_raises_system_exit_on_missing_credentials():
    # The SDK raises a bare RuntimeError from `client.interactions.create()` itself
    # when no API credentials resolve - not an APIError, since the request never
    # reaches the API.
    fake_client = MagicMock()
    original = RuntimeError("Could not resolve API token from the environment")
    fake_client.interactions.create.side_effect = original

    with pytest.raises(SystemExit, match="Tailoring generation failed") as exc_info:
        generate_tailored_application("job text", "Acme", "resume text", [], client=fake_client)
    assert "Could not resolve API token" in str(exc_info.value)
    assert exc_info.value.__cause__ is original


def test_generate_tailored_application_raises_system_exit_on_unknown_api_response():
    # A 200 response with a non-JSON body raises `UnknownApiResponseError`, a
    # `ValueError` subclass, not an `APIError` subclass - a distinct SDK failure
    # mode from both the API-error and network-error paths above.
    fake_client = MagicMock()
    original = genai_errors.UnknownApiResponseError("Failed to parse response as JSON.")
    fake_client.interactions.create.side_effect = original

    with pytest.raises(SystemExit, match="Tailoring generation failed") as exc_info:
        generate_tailored_application("job text", "Acme", "resume text", [], client=fake_client)
    assert "Failed to parse response as JSON" in str(exc_info.value)
    assert exc_info.value.__cause__ is original


def test_generate_tailored_application_raises_system_exit_on_malformed_response():
    fake_response = MagicMock(output_text="{}")
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = fake_response

    with pytest.raises(SystemExit, match="Tailoring generation failed") as exc_info:
        generate_tailored_application("job text", "Acme", "resume text", [], client=fake_client)
    assert "tailored_resume" in str(exc_info.value)


def test_generate_tailored_application_raises_system_exit_on_non_json_response():
    fake_response = MagicMock(output_text="not valid json at all")
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = fake_response

    with pytest.raises(SystemExit, match="Tailoring generation failed"):
        generate_tailored_application("job text", "Acme", "resume text", [], client=fake_client)


def test_generate_tailored_application_raises_system_exit_with_type_name_when_error_message_is_empty():
    fake_client = MagicMock()
    fake_client.interactions.create.side_effect = httpx.HTTPError("")

    with pytest.raises(SystemExit, match="Tailoring generation failed: HTTPError"):
        generate_tailored_application("job text", "Acme", "resume text", [], client=fake_client)


def test_generate_tailored_application_does_not_catch_unrelated_exceptions():
    # Confirms the except clause is precisely scoped, not a bare `except Exception` -
    # an unrelated failure must still propagate raw, not be swallowed into SystemExit.
    fake_client = MagicMock()
    fake_client.interactions.create.side_effect = KeyError("unexpected")

    with pytest.raises(KeyError):
        generate_tailored_application("job text", "Acme", "resume text", [], client=fake_client)
