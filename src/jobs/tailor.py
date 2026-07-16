"""Resume + cover letter tailoring, grounded in real GitHub evidence.

Only run this on jobs that already cleared the match-score threshold - it's
the expensive step (docs/v1-scope.md). Cached on hash(resume + JD) so
re-running against an unchanged resume/job pair doesn't regenerate.
"""

from __future__ import annotations

import hashlib
import sys
import traceback
from typing import Optional

import httpx
from google import genai
from google.genai import errors as genai_errors
from pydantic import BaseModel, ValidationError

from resume.github_evidence import RepoEvidence

MODEL = "gemini-3.5-flash"

_SYSTEM_INSTRUCTION = (
    "You tailor a candidate's resume and write a cover letter for a specific "
    "job posting. Ground every resume bullet in the candidate's real, "
    "verbatim resume and, where relevant, their real GitHub repositories "
    "(name the repo when a claim is backed by one). Never invent metrics, "
    "technologies, or projects the candidate hasn't actually done. If the "
    "job wants something the candidate's resume and repos don't support, "
    "list it under portfolio_gaps instead of fabricating experience. The "
    "tailored resume must be plain text and ATS-friendly: standard section "
    "headers, no tables or columns, no special characters beyond basic "
    "punctuation and bullet dashes. The cover letter should be 3-4 short "
    "paragraphs, specific to this company and role - not generic filler."
)


class TailoredApplication(BaseModel):
    tailored_resume: str
    cover_letter: str
    evidence_notes: list[str]
    portfolio_gaps: list[str]


def compute_tailor_hash(raw_resume_text: str, job_raw_text: str) -> str:
    combined = f"{raw_resume_text}\n---\n{job_raw_text}".encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def _build_input(
    job_raw_text: str,
    company_name: Optional[str],
    raw_resume_text: str,
    repos: list[RepoEvidence],
) -> str:
    if repos:
        repo_lines = "\n".join(
            f"- {r.name} ({r.language or 'unknown language'}, {r.stars} stars): "
            f"{r.description or 'no description'} - {r.url}"
            for r in repos
        )
    else:
        repo_lines = "(no public repos found)"

    return (
        "CANDIDATE'S FULL RESUME (verbatim - the source of truth for real experience):\n"
        f"{raw_resume_text}\n\n"
        "CANDIDATE'S REAL GITHUB REPOSITORIES (verify project claims against these):\n"
        f"{repo_lines}\n\n"
        f"TARGET COMPANY: {company_name or 'unknown - refer to them generically as the hiring company'}\n\n"
        "JOB POSTING:\n"
        f"{job_raw_text}\n"
    )


def generate_tailored_application(
    job_raw_text: str,
    company_name: Optional[str],
    raw_resume_text: str,
    repos: list[RepoEvidence],
    *,
    client: Optional[genai.Client] = None,
) -> TailoredApplication:
    client = client or genai.Client()
    try:
        interaction = client.interactions.create(
            model=MODEL,
            system_instruction=_SYSTEM_INSTRUCTION,
            input=_build_input(job_raw_text, company_name, raw_resume_text, repos),
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": TailoredApplication.model_json_schema(),
            },
        )
        return TailoredApplication.model_validate_json(interaction.output_text)
    except (
        genai_errors.APIError,
        genai_errors.UnknownApiResponseError,
        httpx.HTTPError,
        ValidationError,
        RuntimeError,  # covers the SDK's bare RuntimeError when no API credentials resolve
    ) as exc:
        detail = str(exc).strip() or type(exc).__name__
        # Server-side diagnostic only: the Streamlit UI only ever sees `detail`
        # above via SystemExit, so the full original traceback would otherwise
        # be lost. Never let this diagnostic itself break the SystemExit
        # contract callers rely on.
        try:
            traceback.print_exc(file=sys.stderr)
        except Exception:
            pass
        raise SystemExit(f"Tailoring generation failed: {detail}") from exc
