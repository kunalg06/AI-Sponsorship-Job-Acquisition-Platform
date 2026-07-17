import io
from unittest.mock import MagicMock

import docx
from docx.oxml import OxmlElement

from resume.extract import (
    MODEL,
    ResumeProfile,
    _iter_body_content_including_sdt,
    extract_profile,
    extract_text_from_docx,
)


def _wrap_in_sdt(element):
    """Wrap an existing paragraph/table oxml element in a
    `<w:sdt><w:sdtContent>...</w:sdtContent></w:sdt>` content-control
    wrapper, replacing it in place at the same document position -
    simulates how Word's own resume/CV templates mark up a section as a
    content control. Returns the new `w:sdt` element, so callers can wrap
    it again to build a nested chain."""
    parent = element.getparent()
    index = list(parent).index(element)
    sdt = OxmlElement("w:sdt")
    sdt_content = OxmlElement("w:sdtContent")
    sdt.append(sdt_content)
    parent.remove(element)
    sdt_content.append(element)
    parent.insert(index, sdt)
    return sdt


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


def test_extract_text_from_docx_reads_a_paragraph_wrapped_in_a_content_control():
    doc = docx.Document()
    doc.add_paragraph("Jane Doe")
    wrapped = doc.add_paragraph("Senior ML Engineer")
    doc.add_paragraph("References available on request.")
    _wrap_in_sdt(wrapped._p)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    result = extract_text_from_docx(buffer)

    assert result == "Jane Doe\nSenior ML Engineer\nReferences available on request."


def test_extract_text_from_docx_reads_a_table_wrapped_in_a_content_control():
    doc = docx.Document()
    doc.add_paragraph("Jane Doe")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Python"
    table.cell(0, 1).text = "5 years"
    doc.add_paragraph("References available on request.")
    _wrap_in_sdt(table._tbl)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    result = extract_text_from_docx(buffer)

    assert result == "Jane Doe\nPython | 5 years\nReferences available on request."


def test_extract_text_from_docx_reads_content_nested_two_levels_deep_in_content_controls():
    doc = docx.Document()
    doc.add_paragraph("Jane Doe")
    wrapped = doc.add_paragraph("Senior ML Engineer")
    inner_sdt = _wrap_in_sdt(wrapped._p)
    _wrap_in_sdt(inner_sdt)  # a content control nested inside another one

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    result = extract_text_from_docx(buffer)

    assert result == "Jane Doe\nSenior ML Engineer"


def test_extract_text_from_docx_skips_content_past_the_depth_cap_without_crashing():
    doc = docx.Document()
    doc.add_paragraph("Jane Doe")
    buried = doc.add_paragraph("Buried past the depth cap")
    doc.add_paragraph("References available on request.")

    element = buried._p
    for _ in range(30):  # well past _MAX_SDT_DEPTH (20)
        element = _wrap_in_sdt(element)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    result = extract_text_from_docx(buffer)  # must not raise (no RecursionError, no hang)

    assert "Buried past the depth cap" not in result
    assert result == "Jane Doe\nReferences available on request."


def test_iter_body_content_including_sdt_does_not_recursion_error_on_a_pathologically_deep_chain():
    # Exercises the walk directly, in-memory (no save/reload round-trip):
    # lxml's XML *parser* itself refuses to load a document nested past
    # ~256 levels ("Excessive depth in document"), which would mask
    # whether our own walk is actually recursion-safe - building the tree
    # via the oxml element API instead (as `_wrap_in_sdt` does) isn't
    # subject to that parse-time guard, so this depth is only reachable
    # from a document already loaded via some other means (e.g. a parser
    # configured with XML_PARSE_HUGE), which is exactly the untrusted-input
    # case `_MAX_SDT_DEPTH` defends against.
    doc = docx.Document()
    doc.add_paragraph("Jane Doe")
    buried = doc.add_paragraph("Buried impossibly deep")

    element = buried._p
    for _ in range(1500):  # comfortably past Python's default recursion limit (1000)
        element = _wrap_in_sdt(element)

    items = list(_iter_body_content_including_sdt(doc))  # must not raise RecursionError

    assert [item.text for item in items] == ["Jane Doe"]


def test_extract_text_from_docx_reads_content_at_exactly_the_depth_cap():
    doc = docx.Document()
    p = doc.add_paragraph("At the cap")

    element = p._p
    for _ in range(20):  # exactly _MAX_SDT_DEPTH - must still be read
        element = _wrap_in_sdt(element)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    result = extract_text_from_docx(buffer)

    assert result == "At the cap"


def test_extract_text_from_docx_skips_content_one_level_past_the_depth_cap():
    doc = docx.Document()
    p = doc.add_paragraph("Just past the cap")

    element = p._p
    for _ in range(21):  # one more than _MAX_SDT_DEPTH - must be dropped
        element = _wrap_in_sdt(element)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    result = extract_text_from_docx(buffer)

    assert result == ""


def test_iter_body_content_including_sdt_skips_an_sdt_with_no_sdt_content_child():
    doc = docx.Document()
    doc.add_paragraph("Jane Doe")
    sdt = OxmlElement("w:sdt")  # no <w:sdtContent> child at all - malformed but must not crash
    doc.element.body.insert(0, sdt)
    doc.add_paragraph("References available on request.")

    items = list(_iter_body_content_including_sdt(doc))

    assert [item.text for item in items] == ["Jane Doe", "References available on request."]


def test_iter_body_content_including_sdt_handles_an_empty_sdt_content():
    doc = docx.Document()
    doc.add_paragraph("Jane Doe")
    sdt = OxmlElement("w:sdt")
    sdt.append(OxmlElement("w:sdtContent"))  # present but zero children
    doc.element.body.insert(0, sdt)

    items = list(_iter_body_content_including_sdt(doc))

    assert [item.text for item in items] == ["Jane Doe"]


def test_extract_text_from_docx_preserves_order_across_multiple_interleaved_wraps():
    doc = docx.Document()
    doc.add_paragraph("Plain 1")
    wrapped_p = doc.add_paragraph("Wrapped paragraph")
    _wrap_in_sdt(wrapped_p._p)
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Plain table"
    doc.add_paragraph("Plain 2")

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    result = extract_text_from_docx(buffer)

    assert result == "Plain 1\nWrapped paragraph\nPlain table\nPlain 2"


def test_iter_body_content_including_sdt_reads_multiple_block_children_in_one_wrapper():
    doc = docx.Document()
    first = doc.add_paragraph("First in wrapper")
    second = doc.add_paragraph("Second in wrapper")

    sdt = OxmlElement("w:sdt")
    sdt_content = OxmlElement("w:sdtContent")
    sdt.append(sdt_content)
    body = doc.element.body
    index = list(body).index(first._p)
    body.remove(first._p)
    body.remove(second._p)
    sdt_content.append(first._p)
    sdt_content.append(second._p)
    body.insert(index, sdt)

    items = list(_iter_body_content_including_sdt(doc))

    assert [item.text for item in items] == ["First in wrapper", "Second in wrapper"]
