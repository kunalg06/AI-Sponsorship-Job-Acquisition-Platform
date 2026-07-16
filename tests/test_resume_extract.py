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


def test_extract_text_from_docx_includes_table_content_in_document_order():
    doc = docx.Document()
    doc.add_paragraph("Jane Doe")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Skill"
    table.cell(0, 1).text = "Years"
    table.cell(1, 0).text = "Python"
    table.cell(1, 1).text = "5"
    doc.add_paragraph("References available on request.")

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    result = extract_text_from_docx(buffer)

    assert result == (
        "Jane Doe\n"
        "Skill | Years\n"
        "Python | 5\n"
        "References available on request."
    )


def test_extract_text_from_docx_skips_all_blank_table_rows():
    # An unfilled template table (grid laid out, nothing typed in) must not
    # inject a stray " | " separator into the output - the caller in
    # views/admin.py treats a blank-after-strip result as "no text found".
    doc = docx.Document()
    doc.add_paragraph("Jane Doe")
    doc.add_table(rows=2, cols=2)  # every cell left empty

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    result = extract_text_from_docx(buffer)

    assert result == "Jane Doe"


def test_extract_text_from_docx_dedupes_merged_cell_text():
    doc = docx.Document()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(0, 0).text = "Skills"
    table.cell(1, 0).text = "Python"
    table.cell(1, 1).text = "5 years"

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    result = extract_text_from_docx(buffer)

    assert result == "Skills\nPython | 5 years"


def test_extract_text_from_docx_flattens_newlines_inside_a_table_cell():
    doc = docx.Document()
    table = doc.add_table(rows=1, cols=2)
    cell = table.cell(0, 0)
    cell.text = "Python"
    cell.add_paragraph("PyTorch")
    table.cell(0, 1).text = "5 years"

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    result = extract_text_from_docx(buffer)

    assert result == "Python PyTorch | 5 years"
