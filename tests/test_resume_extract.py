import io
from unittest.mock import MagicMock

import docx

from resume.extract import MODEL, ResumeProfile, extract_profile, extract_text_from_docx


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


def test_extract_text_from_docx_joins_paragraph_text_with_newlines():
    doc = docx.Document()
    doc.add_paragraph("Jane Doe")
    doc.add_paragraph("Senior ML Engineer with 5 years of experience.")
    doc.add_paragraph("Skills: Python, PyTorch, LangGraph")

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    result = extract_text_from_docx(buffer)

    assert result == (
        "Jane Doe\n"
        "Senior ML Engineer with 5 years of experience.\n"
        "Skills: Python, PyTorch, LangGraph"
    )
