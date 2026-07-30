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


# Deliberately higher than MATCH_THRESHOLD (70) and deliberately a separate
# constant: 70 is the "is this worth tailoring for" advisory line shown in the
# UI, whereas this is the line at which the discovery queue *acts on its own*
# and discards a row. The user set 85 after the first real outcome (a 92-scored
# job converted to an interview); spec-indeed-job-discovery.md's Design Notes
# had previously resolved this question the other way ("show all... rather than
# hard-filtering at an unvalidated 85"), so this constant is the one place that
# reversal lives - change it here, not at a call site.
DISCOVERY_TRIAGE_THRESHOLD = 85


def partition_discovery_queue(
    rows: list, threshold: int = DISCOVERY_TRIAGE_THRESHOLD
) -> tuple[list, list, list]:
    """Splits a discovery queue into (keep, discard, unscored) by match score.

    Pure - no DB writes, no I/O - so the threshold policy is testable without
    a database and so callers can preview the split before committing to it
    (`jobs triage-discovery` defaults to exactly that dry run).

    `unscored` is its own bucket rather than being folded into `discard`, and
    that distinction is the whole point of this function: `match_score` is
    NULL whenever scoring was skipped (no resume on file at staging time - see
    `_run_match_score`) and a NULL is an *absence of information*, not a low
    score. Discarding those would silently throw away rows nobody has actually
    judged - the same failure mode that made a truncated-description run look
    like fourteen genuine rejections. Unscored rows stay in the queue for the
    human, matching this codebase's `CANNOT_VERIFY`-over-a-guess convention."""
    keep, discard, unscored = [], [], []
    for row in rows:
        score = row["match_score"]
        if score is None:
            unscored.append(row)
        elif score >= threshold:
            keep.append(row)
        else:
            discard.append(row)
    return keep, discard, unscored
