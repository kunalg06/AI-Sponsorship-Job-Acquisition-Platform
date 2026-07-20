"""LLM-based structured extraction from a pasted job posting.

Job postings have no fixed layout (unlike the sponsor register CSV), so
field extraction goes through Gemini rather than regex/heuristics.
"""

from __future__ import annotations

from typing import Optional

from google import genai
from pydantic import BaseModel

from llm_errors import GEMINI_CALL_EXCEPTIONS, raise_llm_call_failure

MODEL = "gemini-3.5-flash"

_SYSTEM_INSTRUCTION = (
    "You extract structured fields from a UK job posting pasted by a job seeker. "
    "The posting may be from a direct employer or a recruitment agency posting on "
    "behalf of a client. Distinguish the two carefully: many UK postings are placed "
    "by an agency and deliberately omit or redact the actual employer's name. "
    "Only fill employer_name_for_sponsor_check when you are confident it names the "
    "actual entity that would employ the candidate (i.e. who would need to hold "
    "Skilled Worker sponsorship) - leave it null if only an agency/recruiter is named "
    "and no client is identified. Extract only what is actually stated in the "
    "posting; do not guess or invent values."
)


class JobExtraction(BaseModel):
    job_title: str
    company_name: Optional[str] = None
    is_agency_posting: bool
    agency_name: Optional[str] = None
    client_name: Optional[str] = None
    recruiter_name: Optional[str] = None
    recruiter_contact: Optional[str] = None
    location: Optional[str] = None
    salary_raw: Optional[str] = None
    employer_name_for_sponsor_check: Optional[str] = None


def extract_job(raw_text: str, *, client: Optional[genai.Client] = None) -> JobExtraction:
    """Extract structured fields from a raw pasted job posting via Gemini."""
    client = client or genai.Client()
    try:
        interaction = client.interactions.create(
            model=MODEL,
            system_instruction=_SYSTEM_INSTRUCTION,
            input=raw_text,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": JobExtraction.model_json_schema(),
            },
        )
        return JobExtraction.model_validate_json(interaction.output_text)
    except GEMINI_CALL_EXCEPTIONS as exc:
        raise_llm_call_failure("Job extraction failed", exc)
