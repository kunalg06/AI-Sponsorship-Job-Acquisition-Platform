"""Match scoring: how well the candidate profile fits a given job posting.

Score is the go/no-go gate for spending effort tailoring a resume/cover
letter for this job (~70% threshold per docs/v1-scope.md - tune once real
outcome data exists).
"""

from __future__ import annotations

from typing import Optional

from google import genai
from pydantic import BaseModel

from llm_errors import GEMINI_CALL_EXCEPTIONS, raise_llm_call_failure
from resume.extract import ResumeProfile

MODEL = "gemini-3.5-flash"

MATCH_THRESHOLD = 70
STRONG_MATCH = "strong_match"
WEAK_MATCH = "weak_match"

_SYSTEM_INSTRUCTION = (
    "You score how well a candidate's profile matches a job posting, for an "
    "AI/ML/software engineering job seeker deciding whether a job is worth "
    "the effort of tailoring an application for. Score 0-100: weight actual "
    "skills/tools overlap most heavily, then domain fit (e.g. GenAI vs "
    "classical ML vs data engineering), then seniority/experience fit. Do "
    "not inflate the score to be encouraging - a mismatched or underqualified "
    "candidate should score low. List matched_skills (skills/experience the "
    "candidate genuinely has that this job wants) and missing_skills (things "
    "the job wants that the candidate's profile doesn't show). Keep reasoning "
    "to 2-3 sentences, specific and evidence-based."
)


class MatchScore(BaseModel):
    score: int
    matched_skills: list[str]
    missing_skills: list[str]
    reasoning: str


def _build_input(job_raw_text: str, profile: ResumeProfile) -> str:
    profile_summary = (
        "CANDIDATE PROFILE\n"
        f"Seniority: {profile.seniority}\n"
        f"Years of experience: {profile.years_experience if profile.years_experience is not None else 'unknown'}\n"
        f"Core skills: {', '.join(profile.core_skills)}\n"
        f"Domains: {', '.join(profile.domains)}\n"
        f"Past roles: {', '.join(profile.past_roles)}\n"
        f"Summary: {profile.summary}\n"
    )
    return f"{profile_summary}\n---\n\nJOB POSTING\n{job_raw_text}"


def score_job_match(
    job_raw_text: str, profile: ResumeProfile, *, client: Optional[genai.Client] = None
) -> MatchScore:
    client = client or genai.Client()
    try:
        interaction = client.interactions.create(
            model=MODEL,
            system_instruction=_SYSTEM_INSTRUCTION,
            input=_build_input(job_raw_text, profile),
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": MatchScore.model_json_schema(),
            },
        )
        return MatchScore.model_validate_json(interaction.output_text)
    except GEMINI_CALL_EXCEPTIONS as exc:
        raise_llm_call_failure("Match scoring failed", exc)


def match_verdict(score: int) -> str:
    return STRONG_MATCH if score >= MATCH_THRESHOLD else WEAK_MATCH
