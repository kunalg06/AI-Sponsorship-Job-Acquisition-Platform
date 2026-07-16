"""LLM-based structured extraction from a pasted resume/CV.

This is a rarely-run step (once, or whenever the resume changes) that turns
free-text CV content into a structured candidate profile used by match
scoring (and later, tailoring) against job postings.
"""

from __future__ import annotations

from typing import Optional

import docx
from docx.table import Table
from google import genai
from pydantic import BaseModel

MODEL = "gemini-3.5-flash"

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


def extract_text_from_docx(file) -> str:
    """Pull raw text out of a .docx file: paragraphs and table content, in
    original document order (not paragraphs-then-tables), since a CV can
    interleave prose with a skills/dates table. Headers, footers, text boxes,
    and content-control-wrapped (`w:sdt`) sections are not read - rarer in
    CVs and a different python-docx API."""
    document = docx.Document(file)
    lines: list[str] = []
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            lines.extend(text for row in item.rows if (text := _row_text(row)) is not None)
        else:
            lines.append(item.text)
    return "\n".join(lines)
