"""Job-scoped orchestration wrappers shared by every Streamlit page.

Tailoring and outreach used to be reachable only for the job you'd just
pasted in the current browser session (via `st.session_state.saved_job_id`)
- revisiting an older job meant re-pasting its posting text, which silently
created a duplicate row since `jobs.db.insert_job` never dedupes. These
wrappers take a plain `job_id` instead, so any page can trigger either
action for any stored job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from jobs.cli import (
    DEFAULT_GENERATED_CV_DIR,
    DEFAULT_SOURCE_RESUME_DIR,
    _find_source_resume_docx,
    _get_or_generate_tailor_text,
    _load_resume_and_narrative,
    _require_raw_resume_text,
    _sanitize_filename,
)
from jobs.db import connect as connect_jobs
from jobs.db import get_job
from jobs.docx_tailor import (
    build_tailored_docx,
    estimate_page_risk,
    extract_paragraphs,
    generate_paragraph_edits,
    write_plain_docx,
)
from jobs.outreach import OutreachDraft, draft_outreach_message
from jobs.outreach_db import ensure_schema as ensure_outreach_schema
from jobs.outreach_db import insert_outreach_message


def generate_tailored_docx_for_job(job_id: int, jobs_db: str, profile_db: str) -> tuple[Path, Optional[str]]:
    """Tailor the resume + cover letter for any stored job. Mirrors
    `jobs.cli tailor-docx`. Returns (output directory, page-risk warning)."""
    jobs_conn = connect_jobs(jobs_db)
    try:
        job = get_job(jobs_conn, job_id)
        raw_resume_text = _require_raw_resume_text(profile_db)
        text_result = _get_or_generate_tailor_text(jobs_conn, job, raw_resume_text, force=False)

        source_docx = _find_source_resume_docx(DEFAULT_SOURCE_RESUME_DIR)
        paragraphs = extract_paragraphs(source_docx)
        rewritten = generate_paragraph_edits(paragraphs, job["raw_text"], job["company_name"])

        company_slug = _sanitize_filename(job["company_name"] or f"job_{job_id}")
        out_dir = Path(DEFAULT_GENERATED_CV_DIR) / company_slug
        build_tailored_docx(source_docx, rewritten, out_dir / "resume.docx")
        write_plain_docx(text_result.cover_letter, out_dir / "cover_letter.docx")

        return out_dir, estimate_page_risk(source_docx, rewritten)
    finally:
        jobs_conn.close()


def draft_and_save_outreach(
    job_id: int,
    channel: str,
    contact_id: Optional[int],
    contact_name: str,
    contact_title: Optional[str],
    purpose: Optional[str],
    jobs_db: str,
    profile_db: str,
) -> OutreachDraft:
    """Draft + persist an outreach message for any stored job. Raises
    `OutreachLengthError` (nothing saved) if the draft breaks its channel's
    length limit - the caller decides how to surface that."""
    raw_resume_text, narrative_core = _load_resume_and_narrative(profile_db)

    jobs_conn = connect_jobs(jobs_db)
    try:
        job = get_job(jobs_conn, job_id)
        draft = draft_outreach_message(
            channel,
            job["raw_text"],
            job["company_name"],
            contact_name,
            contact_title,
            narrative_core,
            raw_resume_text,
            purpose=purpose,
        )
        ensure_outreach_schema(jobs_conn)
        insert_outreach_message(
            jobs_conn, job_id, contact_id=contact_id, contact_name=contact_name, channel=channel, message=draft.message
        )
        return draft
    finally:
        jobs_conn.close()
