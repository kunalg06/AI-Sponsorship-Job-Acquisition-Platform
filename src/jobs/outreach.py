"""Cold outreach message drafting - channel-aware, remixing one narrative core.

Contact discovery stays manual (LinkedIn browsing, Apollo.io-style tools) -
this module never scrapes anything, it only drafts a message once you tell
it who the contact is.
"""

from __future__ import annotations

from typing import Optional

from google import genai
from pydantic import BaseModel

from llm_errors import GEMINI_CALL_EXCEPTIONS, raise_llm_call_failure

MODEL = "gemini-3.5-flash"

LINKEDIN_NOTE = "linkedin_note"
EMAIL = "email"
CHANNELS = {LINKEDIN_NOTE, EMAIL}

LINKEDIN_NOTE_MAX_CHARS = 300

_SYSTEM_INSTRUCTION_TEMPLATE = (
    "You draft a cold outreach message from a job seeker to a recruiter or "
    "hiring contact, for a specific job posting. Remix the candidate's own "
    "narrative core (why AI, why UK, why them) rather than inventing a "
    "different story each time - consistency reads as confidence. Ground "
    "every claim in their real resume, never invent experience. Be specific "
    "to the company, role, and contact - never generic template filler.\n\n"
    "{channel_instruction}"
)

_CHANNEL_INSTRUCTIONS = {
    LINKEDIN_NOTE: (
        f"This is a LinkedIn connection request note - it has a HARD LIMIT of "
        f"{LINKEDIN_NOTE_MAX_CHARS} characters, no exceptions. Be extremely "
        f"concise: one specific hook, no greeting or sign-off boilerplate."
    ),
    EMAIL: (
        "This is an email - no length limit, but keep it to 3-4 short "
        "paragraphs. Include a greeting and a sign-off."
    ),
}


class OutreachDraft(BaseModel):
    message: str


class OutreachLengthError(Exception):
    """A generated draft violated its channel's length constraint.

    Per docs/v1-scope.md: a draft in the wrong length is worse than no draft
    at all, so this is raised loudly rather than silently truncated.
    """

    def __init__(self, message: str, draft_text: str, char_count: int, limit: int):
        super().__init__(message)
        self.draft_text = draft_text
        self.char_count = char_count
        self.limit = limit


def _build_input(
    job_raw_text: str,
    company_name: Optional[str],
    contact_name: str,
    contact_title: Optional[str],
    narrative_core: str,
    raw_resume_text: str,
    purpose: Optional[str],
) -> str:
    return (
        f"CONTACT: {contact_name}{f' ({contact_title})' if contact_title else ''}\n"
        f"TARGET COMPANY: {company_name or 'unknown - refer to them generically'}\n\n"
        "CANDIDATE'S NARRATIVE CORE (why AI, why UK, why them - remix, don't reinvent):\n"
        f"{narrative_core}\n\n"
        "CANDIDATE'S FULL RESUME (ground claims in this):\n"
        f"{raw_resume_text}\n\n"
        f"PURPOSE OF THIS MESSAGE: {purpose or 'Express genuine interest in the role and open a conversation.'}\n\n"
        "JOB POSTING:\n"
        f"{job_raw_text}\n"
    )


def draft_outreach_message(
    channel: str,
    job_raw_text: str,
    company_name: Optional[str],
    contact_name: str,
    contact_title: Optional[str],
    narrative_core: str,
    raw_resume_text: str,
    purpose: Optional[str] = None,
    *,
    client: Optional[genai.Client] = None,
) -> OutreachDraft:
    if channel not in CHANNELS:
        raise ValueError(f"Unknown channel '{channel}' - expected one of {sorted(CHANNELS)}")

    client = client or genai.Client()
    system_instruction = _SYSTEM_INSTRUCTION_TEMPLATE.format(channel_instruction=_CHANNEL_INSTRUCTIONS[channel])
    try:
        interaction = client.interactions.create(
            model=MODEL,
            system_instruction=system_instruction,
            input=_build_input(
                job_raw_text, company_name, contact_name, contact_title, narrative_core, raw_resume_text, purpose
            ),
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": OutreachDraft.model_json_schema(),
            },
        )
        result = OutreachDraft.model_validate_json(interaction.output_text)
    except GEMINI_CALL_EXCEPTIONS as exc:
        raise_llm_call_failure("Outreach drafting failed", exc)

    if channel == LINKEDIN_NOTE and len(result.message) > LINKEDIN_NOTE_MAX_CHARS:
        raise OutreachLengthError(
            f"Generated LinkedIn note is {len(result.message)} chars, over the {LINKEDIN_NOTE_MAX_CHARS} limit.",
            draft_text=result.message,
            char_count=len(result.message),
            limit=LINKEDIN_NOTE_MAX_CHARS,
        )

    return result
