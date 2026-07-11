from unittest.mock import MagicMock

from resume.extract import MODEL, ResumeProfile, extract_profile


def test_extract_profile_calls_gemini_with_expected_shape_and_parses_output():
    expected = ResumeProfile(
        full_name="Jane Doe",
        years_experience=5.0,
        seniority="senior",
        core_skills=["Python", "PyTorch", "LangGraph"],
        domains=["Generative AI", "NLP"],
        past_roles=["Senior ML Engineer at Acme"],
        summary="Senior ML engineer with 5 years building production LLM systems.",
    )
    fake_response = MagicMock(output_text=expected.model_dump_json())
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = fake_response

    result = extract_profile("some raw resume text", client=fake_client)

    assert result == expected
    _, kwargs = fake_client.interactions.create.call_args
    assert kwargs["model"] == MODEL
    assert kwargs["input"] == "some raw resume text"
    assert kwargs["response_format"]["schema"] == ResumeProfile.model_json_schema()
