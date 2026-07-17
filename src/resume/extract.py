"""LLM-based structured extraction from a pasted resume/CV.

This is a rarely-run step (once, or whenever the resume changes) that turns
free-text CV content into a structured candidate profile used by match
scoring (and later, tailoring) against job postings.
"""

from __future__ import annotations

from typing import Optional

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from google import genai
from pydantic import BaseModel

MODEL = "gemini-3.5-flash"

_MAX_SDT_DEPTH = 20  # defensive ceiling against pathological/adversarial nesting - real CV content controls are never nested this deep

_SYSTEM_INSTRUCTION = (
    "You extract a structured candidate profile from a pasted CV/resume, for "
    "an AI/ML/software engineering job seeker. Extract only what the resume "
    "actually supports - core_skills and domains should reflect real, "
    "demonstrated experience (projects, roles, tools actually used), not "
    "aspirational or inferred skills. seniority should be your best judgment "
    "from years of experience and role titles (e.g. junior, mid, senior, "
    "staff/lead). summary is a factual 2-3 sentence professional summary "
    "written in third person, suitable for comparing against job postings."
)


class ResumeProfile(BaseModel):
    full_name: Optional[str] = None
    years_experience: Optional[float] = None
    seniority: str
    core_skills: list[str]
    domains: list[str]
    past_roles: list[str]
    summary: str


def extract_profile(raw_resume_text: str, *, client: Optional[genai.Client] = None) -> ResumeProfile:
    """Extract a structured candidate profile from raw pasted resume text via Gemini."""
    client = client or genai.Client()
    interaction = client.interactions.create(
        model=MODEL,
        system_instruction=_SYSTEM_INSTRUCTION,
        input=raw_resume_text,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": ResumeProfile.model_json_schema(),
        },
    )
    return ResumeProfile.model_validate_json(interaction.output_text)


def _row_text(row) -> Optional[str]:
    """One table row as a ' | '-joined line, deduping horizontally-merged
    cells (python-docx repeats a merged cell's text once per spanned column,
    all sharing the same underlying `_tc` element) and flattening any
    multi-paragraph cell's internal newlines to spaces so a cell's content
    never gets mistaken for a row/paragraph boundary. Returns None for an
    all-blank row (e.g. an unfilled template table) so it doesn't inject a
    stray separator into a document that otherwise has no real content."""
    seen_tc = None
    cell_texts = []
    for cell in row.cells:
        if cell._tc is seen_tc:
            continue
        seen_tc = cell._tc
        cell_texts.append(cell.text.replace("\n", " "))
    if not any(text.strip() for text in cell_texts):
        return None
    return " | ".join(cell_texts)


def _iter_body_content_including_sdt(document):
    """Order-preserving walk of the document body, like
    `document.iter_inner_content()`, extended to look inside `w:sdt`
    (structured document tag / content control) wrapper elements found as
    direct children of the body - python-docx's own public API skips them
    entirely (`CT_Body.inner_content_elements`'s xpath is `./w:p | ./w:tbl`,
    direct children only), yet Word's built-in resume/CV templates commonly
    wrap whole sections in content controls this way. Does NOT reach into a
    `w:sdt` wrapping a single table row (`w:tr`) or a single paragraph
    inside a table cell - those are still read (or not) by python-docx's
    own `Table.rows`/cell APIs unchanged, which have the same body-level-only
    blind spot; see the deferred-work entry on this gap.

    The walk itself is iterative (an explicit stack), not recursive, so it
    can't raise `RecursionError` or hang on an arbitrarily deep `w:sdt`
    chain regardless of `_MAX_SDT_DEPTH`. The depth cap is a separate,
    narrower guarantee: it bounds how much of a pathologically/adversarially
    deep chain gets *read* (a data-loss containment measure, matching the
    "silent content loss for rare structures" trade-off already made for
    headers/footers/text boxes), not what makes the walk itself safe to run."""
    p_tag = qn("w:p")
    tbl_tag = qn("w:tbl")
    sdt_tag = qn("w:sdt")
    sdt_content_tag = qn("w:sdtContent")

    stack = [(element, 0) for element in reversed(document.element.body)]
    while stack:
        element, depth = stack.pop()
        tag = element.tag
        if tag == p_tag:
            yield Paragraph(element, document)
        elif tag == tbl_tag:
            yield Table(element, document)
        elif tag == sdt_tag and depth < _MAX_SDT_DEPTH:
            sdt_content = element.find(sdt_content_tag)
            if sdt_content is not None:
                stack.extend((child, depth + 1) for child in reversed(sdt_content))
        # any other element (w:sectPr, an over-depth w:sdt, content wrapped
        # in some other element like w:ins, ...) is skipped, matching
        # iter_inner_content's own scope


def extract_text_from_docx(file) -> str:
    """Pull raw text out of a .docx file: paragraphs and table content, in
    original document order (not paragraphs-then-tables), since a CV can
    interleave prose with a skills/dates table - including a paragraph or
    table wrapped in a `w:sdt` content control as a direct child of the
    document body, at any nesting depth up to `_MAX_SDT_DEPTH` (see
    `_iter_body_content_including_sdt`). A `w:sdt` wrapping a single table
    row or an individual paragraph inside a table cell is not read - see
    that function's docstring. Headers, footers, and text boxes are not
    read either - rarer in CVs and a different python-docx API."""
    document = docx.Document(file)
    lines: list[str] = []
    for item in _iter_body_content_including_sdt(document):
        if isinstance(item, Table):
            lines.extend(text for row in item.rows if (text := _row_text(row)) is not None)
        else:
            lines.append(item.text)
    return "\n".join(lines)
