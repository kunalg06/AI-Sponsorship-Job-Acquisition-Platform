"""LLM-based structured extraction from a pasted resume/CV.

This is a rarely-run step (once, or whenever the resume changes) that turns
free-text CV content into a structured candidate profile used by match
scoring (and later, tailoring) against job postings.
"""

from __future__ import annotations

from typing import Optional

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
