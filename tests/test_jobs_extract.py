from unittest.mock import MagicMock

import httpx
import pytest
from google.genai._gaos.lib import compat_errors

from jobs.extract import MODEL, JobExtraction, extract_job


def test_extract_job_calls_gemini_with_expected_shape_and_parses_output():
    expected = JobExtraction(
        job_title="AI Engineer",
        company_name="Acme AI Ltd",
        is_agency_posting=False,
        employer_name_for_sponsor_check="Acme AI Ltd",
    )
    fake_response = MagicMock(output_text=expected.model_dump_json())
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = fake_response

    result = extract_job("some raw job text", client=fake_client)

    assert result == expected
    _, kwargs = fake_client.interactions.create.call_args
    assert kwargs["model"] == MODEL
    assert kwargs["input"] == "some raw job text"
    assert kwargs["response_format"]["schema"] == JobExtraction.model_json_schema()


def test_extract_job_raises_system_exit_on_connection_error():
    fake_client = MagicMock()
    original = compat_errors.APIConnectionError(
        message="Connection refused", request=httpx.Request("POST", "https://example.com")
    )
    fake_client.interactions.create.side_effect = original

    with pytest.raises(SystemExit, match="Job extraction failed: Connection refused") as exc_info:
        extract_job("some raw job text", client=fake_client)
    assert exc_info.value.__cause__ is original


def test_agency_posting_with_redacted_client_leaves_sponsor_check_name_unset():
    extraction = JobExtraction(
        job_title="ML Engineer",
        is_agency_posting=True,
        agency_name="Some Recruitment Ltd",
        client_name=None,
        employer_name_for_sponsor_check=None,
    )
    assert extraction.client_name is None
    assert extraction.employer_name_for_sponsor_check is None
