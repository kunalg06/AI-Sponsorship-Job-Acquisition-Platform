"""CLI for pasting a job posting into the intake pipeline."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.error
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from jobs.atomic_fs import _fsync_directory
from jobs.db import (
    connect,
    get_job,
    insert_job,
    list_applied_jobs,
    list_job_ids_and_company_names,
    list_jobs,
    list_legacy_tailored_rows,
    mark_applied,
    mark_discarded,
    mark_reminders_sent_through,
    update_employer_name,
    update_match_verdict,
    update_salary_verdict,
    update_sponsor_verdict,
    update_tailoring,
)
from jobs.docx_tailor import (
    build_tailored_docx,
    estimate_page_risk,
    extract_paragraphs,
    generate_paragraph_edits,
    write_plain_docx,
)
from jobs.extract import extract_job
from jobs.match_score import MATCH_THRESHOLD, STRONG_MATCH, WEAK_MATCH, match_verdict, score_job_match
from jobs.outreach import EMAIL, LINKEDIN_NOTE, OutreachLengthError, draft_outreach_message
from jobs.outreach_db import (
    ensure_schema as ensure_outreach_schema,
)
from jobs.outreach_db import (
    drop_legacy_message_column,
    get_contact,
    insert_contact,
    insert_outreach_message,
    list_contacts,
    list_legacy_outreach_message_rows,
)
from jobs.salary_check import MEETS_THRESHOLD, check_salary_threshold
from jobs.sponsor_check import CONFIRMED, FUZZY_MATCH, USER_CONFIRMED, check_sponsor_status
from jobs.tailor import compute_tailor_hash, generate_tailored_application
from jobs.tracker import due_milestone, days_since
from register.db import connect as connect_register
from resume.db import connect as connect_profile
from resume.db import get_latest_narrative, get_latest_profile, get_latest_raw_resume_text
from resume.github_evidence import extract_github_username, fetch_public_repos

load_dotenv()

DEFAULT_DB = "data/jobs.db"
DEFAULT_SPONSOR_DB = "data/sponsors.db"
DEFAULT_PROFILE_DB = "data/profile.db"
DEFAULT_TAILOR_OUT_DIR = "data/tailored"
DEFAULT_SOURCE_RESUME_DIR = "cv/my-resume"
DEFAULT_GENERATED_CV_DIR = "cv/generated_cv"


def _read_input(args: argparse.Namespace) -> str:
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    text = sys.stdin.read()
    if not text.strip():
        raise SystemExit("No job text provided - pass --file or pipe text via stdin.")
    return text


def _run_sponsor_check(jobs_conn, sponsor_db: str, job_id: int, employer_name, job_location: Optional[str] = None) -> None:
    register_conn = connect_register(sponsor_db)
    try:
        verdict = check_sponsor_status(register_conn, employer_name)
    finally:
        register_conn.close()

    update_sponsor_verdict(
        jobs_conn,
        job_id,
        status=verdict.status,
        reason=verdict.reason,
        matched_name=verdict.matched_name,
        rating=verdict.rating,
        route=verdict.route,
        town_city=verdict.town_city,
        county=verdict.county,
    )

    print("  --- Sponsor check ---")
    if job_location:
        print(f"  Job posting location: {job_location}")

    if verdict.status == CONFIRMED:
        print(f"  Status:           CONFIRMED - {verdict.matched_name} ({verdict.rating}, {verdict.route})")
        print(f"  Register location: {verdict.town_city or '-'}, {verdict.county or '-'}")
        print(f"  Note:             {verdict.reason}")
    elif verdict.status == FUZZY_MATCH:
        print(f"  Status:           FUZZY_MATCH - {len(verdict.candidates)} candidate(s), compare location against the job posting:")
        for c in verdict.candidates:
            print(f"    - {c.name} | {c.town_city or '-'}, {c.county or '-'} | {c.rating}, {c.route}")
        print(f"  Reason:           {verdict.reason}")
    else:
        print(f"  Status:           {verdict.status.upper()}")
        print(f"  Reason:           {verdict.reason}")


def _run_salary_check(jobs_conn, job_id: int, job_title: str, salary_raw) -> None:
    verdict = check_salary_threshold(job_title, salary_raw)

    update_salary_verdict(
        jobs_conn,
        job_id,
        status=verdict.status,
        reason=verdict.reason,
        offered=verdict.offered_salary,
        threshold=verdict.threshold,
        soc_code=verdict.soc_code,
        soc_job_type=verdict.soc_job_type,
    )

    print("  --- Salary threshold check ---")
    if verdict.status == MEETS_THRESHOLD:
        print(f"  Status:           MEETS THRESHOLD - {verdict.reason}")
    else:
        print(f"  Status:           {verdict.status.upper()}")
        print(f"  Reason:           {verdict.reason}")


def _run_match_score(jobs_conn, profile_db: str, job_id: int, job_raw_text: str) -> None:
    profile_conn = connect_profile(profile_db)
    try:
        profile = get_latest_profile(profile_conn)
    finally:
        profile_conn.close()

    print("  --- Match score ---")
    if profile is None:
        print("  Skipped - no resume on file yet. Run `python -m resume.cli add --file <resume.txt>` first.")
        return

    result = score_job_match(job_raw_text, profile)
    verdict = match_verdict(result.score)

    update_match_verdict(
        jobs_conn,
        job_id,
        score=result.score,
        verdict=verdict,
        matched_skills=result.matched_skills,
        missing_skills=result.missing_skills,
        reasoning=result.reasoning,
    )

    label = "STRONG MATCH" if verdict == STRONG_MATCH else "WEAK MATCH"
    print(f"  Score:            {result.score}/100 ({label}, threshold {MATCH_THRESHOLD})")
    print(f"  Matched skills:   {', '.join(result.matched_skills) or '(none)'}")
    print(f"  Missing skills:   {', '.join(result.missing_skills) or '(none)'}")
    print(f"  Reasoning:        {result.reasoning}")


def _cmd_intake(args: argparse.Namespace) -> None:
    raw_text = _read_input(args)
    extraction = extract_job(raw_text)

    conn = connect(args.db)
    try:
        job_id = insert_job(conn, raw_text, extraction)

        print(f"Stored job #{job_id}")
        print(f"  Title:            {extraction.job_title}")
        print(f"  Company:          {extraction.company_name or '(not stated)'}")
        print(f"  Agency posting:   {extraction.is_agency_posting}")
        if extraction.is_agency_posting:
            print(f"  Agency:           {extraction.agency_name or '(unnamed)'}")
            print(f"  Client:           {extraction.client_name or '(not stated)'}")
        print(f"  Recruiter:        {extraction.recruiter_name or '(none given)'}")
        print(f"  Contact:          {extraction.recruiter_contact or '(none given)'}")
        print(f"  Location:         {extraction.location or '(not stated)'}")
        print(f"  Salary:           {extraction.salary_raw or '(not stated)'}")

        _run_sponsor_check(conn, args.sponsor_db, job_id, extraction.employer_name_for_sponsor_check, extraction.location)
        _run_salary_check(conn, job_id, extraction.job_title, extraction.salary_raw)
        _run_match_score(conn, args.profile_db, job_id, raw_text)
    finally:
        conn.close()


def _cmd_sponsor_check(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")
        print(f"Job #{job['id']}: {job['job_title']}")
        _run_sponsor_check(conn, args.sponsor_db, args.job_id, job["employer_name_for_sponsor_check"], job["location"])
    finally:
        conn.close()


def _cmd_salary_check(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")
        print(f"Job #{job['id']}: {job['job_title']}")
        _run_salary_check(conn, args.job_id, job["job_title"], job["salary_raw"])
    finally:
        conn.close()


def _cmd_match_score(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")
        print(f"Job #{job['id']}: {job['job_title']}")
        _run_match_score(conn, args.profile_db, args.job_id, job["raw_text"])
    finally:
        conn.close()


def _atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to `path` atomically for a single writer - a crash or
    failure at any point before the final rename leaves `path` with its full
    prior content (or absent), never truncated. Does not arbitrate between
    concurrent writers targeting the same `path`; the tmp filename includes
    a pid+random suffix so overlapping calls don't share one tmp file, but
    if two calls race to completion, the final `os.replace` is still
    last-writer-wins (as any rename-based scheme is, absent external
    locking - out of scope here). Temp file is a same-directory sibling so
    `os.replace` stays a same-filesystem rename; mirrors
    `_bmad/scripts/memlog.py`'s own `write_atomic()` pattern.

    On POSIX, best-effort fsyncs the containing directory after a successful
    rename too (see `jobs.atomic_fs._fsync_directory`) - this never raises,
    so an exception from this function still always means the write itself
    didn't land, exactly as before.
    """
    tmp = path.parent / f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except (OSError, ValueError):
        tmp.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def _write_tailoring_files(out_dir: str, job_id: int, tailored_resume: str, cover_letter: str) -> None:
    # Deliberately no try/except here (or in _migrate_legacy_text below): only the
    # outreach draft write (see _draft_and_store_outreach) runs after a DB commit
    # that would otherwise silently desync, so only that site needs a distinct
    # failure message. A raised OSError here propagates uncaught, same as before
    # this file's writes became atomic - unchanged behavior, just no longer able
    # to leave a truncated file behind.
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    resume_path = out_path / f"{job_id}_resume.txt"
    cover_letter_path = out_path / f"{job_id}_cover_letter.txt"
    _atomic_write_text(resume_path, tailored_resume)
    _atomic_write_text(cover_letter_path, cover_letter)
    print(f"  Written to: {resume_path}")
    print(f"              {cover_letter_path}")


def _fetch_github_evidence(raw_resume_text: str) -> list:
    """Best-effort GitHub repo evidence for tailoring - a plain API fetch, not
    a cache-check, so it's safe to share between the plain-text `tailor`
    path and the docx path without recreating the caching bug this refactor
    fixes (see Spec Change Log)."""
    username = extract_github_username(raw_resume_text)
    if not username:
        print("  (no GitHub username found in resume - continuing without repo evidence)")
        return []
    try:
        return fetch_public_repos(username)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"  (couldn't fetch GitHub repos for '{username}': {exc} - continuing without repo evidence)")
        return []


@dataclass
class TailorTextResult:
    cover_letter: Optional[str]
    evidence_notes: list
    portfolio_gaps: list
    page_risk_warning: Optional[str]
    freshly_generated: bool


def _get_or_generate_tailor_text(
    conn, job, raw_resume_text: str, tailor_hash: str, resume_path: Path, cover_letter_path: Path, force: bool
) -> TailorTextResult:
    """Docx-path cache-check ONLY - the plain-text `tailor` command never
    calls this; it has its own always-fresh path (see `_cmd_tailor`).

    A cache hit requires the resume+job hash to match AND both job_id-keyed
    docx output files to already exist on disk (job_id-keyed, so a second
    role at the same company never collides with the first). On a hit,
    evidence_notes/portfolio_gaps/page_risk_warning are read back from the
    DB verbatim - no file *content* read of any kind, only an existence
    check (`Path.exists()`) on the two docx files themselves."""
    if job["tailor_hash"] == tailor_hash and not force and resume_path.exists() and cover_letter_path.exists():
        return TailorTextResult(
            cover_letter=None,  # unused on a cache hit - the docx isn't rebuilt
            evidence_notes=json.loads(job["tailor_evidence_notes"] or "[]"),
            portfolio_gaps=json.loads(job["tailor_portfolio_gaps"] or "[]"),
            # Known, accepted transitional limitation: for a job migrated by
            # `migrate-legacy-tailoring` (tailor_hash set pre-refactor, docx
            # files renamed into the job_id-keyed scheme), this column is
            # NULL because it didn't exist when that job was last tailored -
            # indistinguishable here from `estimate_page_risk`'s own quiet
            # "genuinely no risk" fallback. Not fixable without an LLM call
            # or reintroducing docx-diffing (the original pre-tailoring
            # source docx isn't retained); self-heals the next time this
            # job's resume or job text actually changes and regenerates.
            page_risk_warning=job["tailor_page_risk_warning"],
            freshly_generated=False,
        )

    repos = _fetch_github_evidence(raw_resume_text)
    result = generate_tailored_application(job["raw_text"], job["company_name"], raw_resume_text, repos)
    return TailorTextResult(
        cover_letter=result.cover_letter,
        evidence_notes=result.evidence_notes,
        portfolio_gaps=result.portfolio_gaps,
        page_risk_warning=None,  # not known yet - set by `_tailor_docx_for_job` after the docx rewrite
        freshly_generated=True,
    )


def _require_raw_resume_text(profile_db: str) -> str:
    profile_conn = connect_profile(profile_db)
    try:
        raw_resume_text = get_latest_raw_resume_text(profile_conn)
    finally:
        profile_conn.close()
    if raw_resume_text is None:
        raise SystemExit("No resume on file yet - run `python -m resume.cli add --file <resume.txt>` first.")
    return raw_resume_text


def _cmd_tailor(args: argparse.Namespace) -> None:
    """Plain-text tailoring output (`.txt`, `args.out_dir`). Deliberately
    uncached - always calls the LLM fresh and always (over)writes its
    output files. This is a separate, rarely-used output format from the
    docx path (different directory, different artifact); see Spec Change
    Log for why sharing one cache-check across both formats was the bug."""
    conn = connect(args.db)
    try:
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")

        if job["match_verdict"] == WEAK_MATCH and not args.force:
            print(
                f"Note: job #{args.job_id} scored {job['match_score']}/100, below the "
                f"{MATCH_THRESHOLD} match threshold. Tailoring anyway."
            )

        raw_resume_text = _require_raw_resume_text(args.profile_db)
        repos = _fetch_github_evidence(raw_resume_text)
        result = generate_tailored_application(job["raw_text"], job["company_name"], raw_resume_text, repos)

        print(f"Job #{args.job_id}: tailored resume + cover letter generated.")
        print("  --- Evidence notes ---")
        for note in result.evidence_notes:
            print(f"  - {note}")
        print("  --- Portfolio gaps ---")
        for gap in result.portfolio_gaps:
            print(f"  - {gap}")

        _write_tailoring_files(args.out_dir, args.job_id, result.tailored_resume, result.cover_letter)
    finally:
        conn.close()


def _sanitize_filename(name: str) -> str:
    slug = re.sub(r"[^\w\- ]", "", name).strip()
    slug = re.sub(r"\s+", "_", slug)
    return slug or "unknown_company"


def _company_slug(company_name: Optional[str], job_id: int) -> str:
    """Shared fallback-slug logic: sanitize `company_name`, or fall back to
    `job_{job_id}` (then sanitize that too) when there's no company name.
    Used by BOTH `_tailored_docx_paths` (to build the output path for a job)
    and `_migrate_legacy_docx`'s job-matching (to figure out which job a
    legacy company-only-keyed folder belongs to) - a single shared helper so
    the two can never independently drift apart on how the fallback is
    computed."""
    return _sanitize_filename(company_name or f"job_{job_id}")


def _tailored_docx_paths(company_name: Optional[str], job_id: int, out_dir: str) -> tuple[Path, Path]:
    """job_id-keyed docx output paths - matches the existing
    `{job_id}_resume.txt` txt-export convention, just extended to docx.
    Keying by job_id (not just company) is what lets a second role at the
    same company get its own files instead of silently reusing/overwriting
    the first role's stale ones."""
    company_dir = Path(out_dir) / _company_slug(company_name, job_id)
    return company_dir / f"{job_id}_resume.docx", company_dir / f"{job_id}_cover_letter.docx"


def _outreach_message_path(company_name: Optional[str], job_id: int, channel: str, message_id: int, out_dir: str) -> Path:
    """job_id- AND message_id-keyed outreach message file path -
    `outreach_messages` is an insert-only history table (multiple drafts
    per job/channel, e.g. to different contacts), unlike the job_id-only
    keying used for tailored resume/cover-letter output, so the message id
    must be part of the filename too or a second draft to the same job+
    channel would silently overwrite the first one's file."""
    company_dir = Path(out_dir) / _company_slug(company_name, job_id)
    return company_dir / f"{job_id}_outreach_{channel}_{message_id}.txt"


def _read_outreach_message_text(
    company_name: Optional[str], job_id: int, channel: str, message_id: int, out_dir: str
) -> Optional[str]:
    """Read a past drafted outreach message back off disk for display (the
    "Message history" expander in `views/jobs_list.py`/`views/intake.py`) -
    `None` if the file isn't there (moved/deleted externally), letting the
    caller show a fallback instead of crashing."""
    path = _outreach_message_path(company_name, job_id, channel, message_id, out_dir)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _find_source_resume_docx(directory: str) -> Path:
    dir_path = Path(directory)
    candidates = sorted(dir_path.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise SystemExit(f"No .docx resume found in {directory} - place your resume file there first.")
    if len(candidates) > 1:
        print(f"  ({len(candidates)} .docx files found in {directory} - using the most recently modified: {candidates[0].name})")
    return candidates[0]


@dataclass
class TailorDocxResult:
    resume_path: Path
    cover_letter_path: Path
    page_risk_warning: Optional[str]
    freshly_generated: bool


def _tailor_docx_for_job(
    conn, job, raw_resume_text: str, resume_dir: str, out_dir: str, force: bool
) -> TailorDocxResult:
    """Shared by `tailor-docx` CLI and `ui_actions.generate_tailored_docx_for_job`.

    Cache-check (job_id-keyed hash + file existence, see
    `_get_or_generate_tailor_text`) covers the WHOLE docx path - both the
    cover-letter/evidence-notes text generation AND the paragraph-level
    docx rewrite - so a cache hit makes no LLM call and reads no file at
    all (not even the source .docx). `estimate_page_risk` is computed ONLY
    on a fresh generation, right where `rewritten` is already in hand, and
    persisted via `update_tailoring` for exact recall on the next hit -
    never recomputed by diffing docx files (see Spec Change Log)."""
    resume_path, cover_letter_path = _tailored_docx_paths(job["company_name"], job["id"], out_dir)
    tailor_hash = compute_tailor_hash(raw_resume_text, job["raw_text"])
    text_result = _get_or_generate_tailor_text(
        conn, job, raw_resume_text, tailor_hash, resume_path, cover_letter_path, force
    )

    if not text_result.freshly_generated:
        return TailorDocxResult(
            resume_path=resume_path,
            cover_letter_path=cover_letter_path,
            page_risk_warning=text_result.page_risk_warning,
            freshly_generated=False,
        )

    source_docx = _find_source_resume_docx(resume_dir)
    paragraphs = extract_paragraphs(source_docx)
    rewritten = generate_paragraph_edits(paragraphs, job["raw_text"], job["company_name"])

    build_tailored_docx(source_docx, rewritten, resume_path)
    write_plain_docx(text_result.cover_letter, cover_letter_path)

    page_risk_warning = estimate_page_risk(source_docx, rewritten)

    update_tailoring(
        conn,
        job["id"],
        tailor_hash=tailor_hash,
        evidence_notes=text_result.evidence_notes,
        portfolio_gaps=text_result.portfolio_gaps,
        page_risk_warning=page_risk_warning,
    )

    return TailorDocxResult(
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
        page_risk_warning=page_risk_warning,
        freshly_generated=True,
    )


def _cmd_tailor_docx(args: argparse.Namespace) -> None:
    """Generate a tailored resume that keeps the original .docx's exact
    fonts/styles/formatting (only wording changes) plus a cover letter,
    saved under cv/generated_cv/<company>/{job_id}_*.docx for the UI to
    serve as downloads."""
    conn = connect(args.db)
    try:
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")

        if job["match_verdict"] == WEAK_MATCH and not args.force:
            print(
                f"Note: job #{args.job_id} scored {job['match_score']}/100, below the "
                f"{MATCH_THRESHOLD} match threshold. Tailoring anyway."
            )

        raw_resume_text = _require_raw_resume_text(args.profile_db)
        result = _tailor_docx_for_job(conn, job, raw_resume_text, args.resume_dir, args.out_dir, args.force)

        if result.freshly_generated:
            print(f"Job #{args.job_id}: tailored .docx resume + cover letter written to {result.resume_path.parent}/")
        else:
            print(
                f"Job #{args.job_id}: tailoring already generated for this exact resume+job pair "
                f"(cached) - {result.resume_path.parent}/"
            )
        print(f"  - {result.resume_path.name}")
        print(f"  - {result.cover_letter_path.name}")

        if result.page_risk_warning:
            print(f"  Warning: {result.page_risk_warning}")
    finally:
        conn.close()


def _migrate_legacy_text(conn, out_dir: str) -> None:
    """Part 1 of the migration: back up any pre-existing DB-resident
    tailored text (from before `update_tailoring` stopped writing it) to
    `.txt` files, matching the plain `tailor` command's own output
    convention. Idempotent: skips a file that's already there."""
    rows = list_legacy_tailored_rows(conn)
    if not rows:
        print("No legacy DB-resident tailored text found - nothing to do.")
        return

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    wrote_any = False
    for row in rows:
        resume_path = out_path / f"{row['id']}_resume.txt"
        cover_letter_path = out_path / f"{row['id']}_cover_letter.txt"
        if row["tailored_resume"] and not resume_path.exists():
            _atomic_write_text(resume_path, row["tailored_resume"])
            print(f"  Wrote {resume_path}")
            wrote_any = True
        if row["cover_letter"] and not cover_letter_path.exists():
            _atomic_write_text(cover_letter_path, row["cover_letter"])
            print(f"  Wrote {cover_letter_path}")
            wrote_any = True

    if not wrote_any:
        print("Legacy DB-resident tailored text already backed up to disk - nothing to do.")


def _migrate_legacy_docx(conn, generated_cv_dir: str) -> None:
    """Part 2 of the migration: rename pre-existing old-format
    company-only-keyed docx files (`resume.docx`/`cover_letter.docx`) to
    the new job_id-keyed names, when the mapping to a job is unambiguous.
    Company-less jobs are matched via their `job_{id}` fallback slug too
    (via the shared `_company_slug` helper, same one `_tailored_docx_paths`
    uses), so a legacy folder created for a job with no company_name isn't
    permanently reported ambiguous. Zero matching jobs -> nothing to
    disambiguate, just orphaned data with no corresponding job: warn "no
    matching job found" and skip. Multiple matching jobs -> genuinely
    ambiguous: warn "ambiguous" and skip. Never guess either way. Each
    company folder's entire processing block (existence checks, match
    lookup, renames) is wrapped in its own `try/except OSError` so one bad
    folder (locked file, permission denied, broken entry) can't abort
    processing of the rest."""
    root = Path(generated_cv_dir)
    if not root.exists():
        print(f"No {generated_cv_dir}/ directory found - nothing to do.")
        return

    jobs_by_slug: dict[str, list[int]] = {}
    for row in list_job_ids_and_company_names(conn):
        slug = _company_slug(row["company_name"], row["id"])
        jobs_by_slug.setdefault(slug, []).append(row["id"])

    found_old_format = False
    renamed_any = False

    try:
        candidate_dirs = sorted(root.iterdir())
    except OSError as exc:
        print(f"  Warning: failed to list {root}: {exc} - aborting migration scan.")
        return

    for company_dir in candidate_dirs:
        try:
            if not company_dir.is_dir():
                continue

            old_resume = company_dir / "resume.docx"
            old_cover = company_dir / "cover_letter.docx"
            if not old_resume.exists() and not old_cover.exists():
                continue
            found_old_format = True

            matches = jobs_by_slug.get(company_dir.name, [])
            if not matches:
                print(
                    f"  Warning: no matching job found for legacy docx folder '{company_dir}' - "
                    "skipping (not renamed, not deleted)."
                )
                continue
            if len(matches) > 1:
                print(
                    f"  Warning: ambiguous legacy docx folder '{company_dir}' - {len(matches)} matching "
                    "job(s) in jobs.db - leaving untouched (not renamed, not deleted)."
                )
                continue

            job_id = matches[0]
            for old_path, new_name in (
                (old_resume, f"{job_id}_resume.docx"),
                (old_cover, f"{job_id}_cover_letter.docx"),
            ):
                if not old_path.exists():
                    continue
                new_path = company_dir / new_name
                if new_path.exists():
                    print(f"  Skipped {old_path} - {new_path} already exists.")
                    continue
                try:
                    old_path.rename(new_path)
                    print(f"  Renamed {old_path} -> {new_path}")
                    renamed_any = True
                except OSError as exc:
                    print(f"  Warning: failed to rename {old_path}: {exc} - leaving it untouched, continuing.")
        except OSError as exc:
            print(f"  Warning: failed to process legacy docx folder '{company_dir}': {exc} - skipping, continuing with the rest.")
            continue

    if not found_old_format:
        print(f"No old-format company-only-keyed docx files found under {generated_cv_dir}/ - nothing to do.")
    elif not renamed_any:
        print("Legacy docx files already migrated (or all remaining ones could not be matched to a job) - nothing further to do.")


def _cmd_migrate_legacy_tailoring(args: argparse.Namespace) -> None:
    """One-time, idempotent migration: (1) back up DB-resident tailored text
    to `.txt` files, (2) rename old-format company-only-keyed docx files to
    job_id-keyed names where the company->job mapping is unambiguous. Safe
    to re-run - every step skips anything already migrated."""
    conn = connect(args.db)
    try:
        _migrate_legacy_text(conn, args.out_dir)
        _migrate_legacy_docx(conn, args.generated_cv_dir)
    finally:
        conn.close()


def _migrate_legacy_outreach_text(conn, out_dir: str) -> None:
    """Back up any pre-existing DB-resident outreach message text (from
    before `insert_outreach_message` stopped writing it) to `.txt` files,
    matching `_outreach_message_path`'s own output convention. Idempotent:
    skips a file that's already there."""
    rows = list_legacy_outreach_message_rows(conn)
    if not rows:
        print("No legacy DB-resident outreach message text found - nothing to do.")
        return

    wrote_any = False
    for row in rows:
        path = _outreach_message_path(row["company_name"], row["job_id"], row["channel"], row["id"], out_dir)
        if path.exists():
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(path, row["message"])
        except OSError as exc:
            print(f"  Warning: failed to back up message #{row['id']} to {path}: {exc}")
            continue
        print(f"  Wrote {path}")
        wrote_any = True

    if not wrote_any:
        print("Legacy DB-resident outreach message text already backed up to disk - nothing to do.")


def _cmd_migrate_legacy_outreach(args: argparse.Namespace) -> None:
    """One-time, idempotent migration: back up any DB-resident outreach
    message text to `.txt` files, then drop the now-unused `message` column
    (required before new inserts can succeed against a pre-existing table).
    Safe to re-run - a fresh DB that never had the column is a no-op."""
    conn = connect(args.db)
    try:
        _migrate_legacy_outreach_text(conn, args.out_dir)
        drop_legacy_message_column(conn)
    finally:
        conn.close()


def _cmd_add_contact(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        ensure_outreach_schema(conn)
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")

        contact_id = insert_contact(
            conn, args.job_id, args.name, title=args.title, linkedin_url=args.linkedin_url, email=args.email
        )
        print(f"Added contact #{contact_id} to job #{args.job_id}: {args.name} ({args.title or 'no title given'})")
    finally:
        conn.close()


def _cmd_contacts(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        ensure_outreach_schema(conn)
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")

        if job["recruiter_name"]:
            print(f"From job posting: {job['recruiter_name']} ({job['recruiter_contact'] or 'no contact given'})")

        for row in list_contacts(conn, args.job_id):
            print(f"#{row['id']:>4}  {row['name']:<25} {row['title'] or '-':<25} {row['email'] or row['linkedin_url'] or '-'}")
    finally:
        conn.close()


def _resolve_contact(conn, job, contact_id: Optional[int]):
    """Returns (contact_id, contact_name, contact_title). Falls back to the
    job's own recruiter (from the posting) when no explicit contact is given."""
    if contact_id is not None:
        contact = get_contact(conn, contact_id)
        if contact is None:
            raise SystemExit(f"No contact #{contact_id} found.")
        return contact["id"], contact["name"], contact["title"]
    if job["recruiter_name"]:
        return None, job["recruiter_name"], "Recruiter"
    raise SystemExit(
        "No contact to draft for - the job posting has no recruiter name, and no --contact-id given. "
        f"Add one first: `jobs add-contact {job['id']} --name \"...\"`."
    )


def _load_resume_and_narrative(profile_db: str):
    profile_conn = connect_profile(profile_db)
    try:
        raw_resume_text = get_latest_raw_resume_text(profile_conn)
        narrative_core = get_latest_narrative(profile_conn)
    finally:
        profile_conn.close()

    if raw_resume_text is None:
        raise SystemExit("No resume on file yet - run `python -m resume.cli add --file <resume.txt>` first.")
    if narrative_core is None:
        raise SystemExit(
            "No narrative core on file yet - run `python -m resume.cli narrative-add --file <narrative.txt>` first."
        )
    return raw_resume_text, narrative_core


def _draft_and_store_outreach(
    conn,
    job,
    channel: str,
    contact_id,
    contact_name,
    contact_title,
    purpose: Optional[str],
    profile_db: str,
    out_dir: str = DEFAULT_GENERATED_CV_DIR,
):
    raw_resume_text, narrative_core = _load_resume_and_narrative(profile_db)

    try:
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
    except OutreachLengthError as exc:
        print(f"Draft rejected: {exc}")
        print("  --- Over-length draft (not saved) ---")
        print(f"  {exc.draft_text}")
        return None

    try:
        message_id = insert_outreach_message(
            conn, job["id"], contact_id=contact_id, contact_name=contact_name, channel=channel, message=draft.message
        )
    except sqlite3.IntegrityError:
        raise SystemExit(
            "This jobs.db has a pre-existing outreach_messages table from before message text moved to disk - "
            "run `migrate-legacy-outreach` first."
        )
    path = _outreach_message_path(job["company_name"], job["id"], channel, message_id, out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _atomic_write_text(path, draft.message)
    except (OSError, ValueError) as exc:
        # draft.message is still in memory here - print it so the operator can
        # recover it by copy-paste instead of re-running a non-deterministic,
        # LLM-backed redraft from scratch.
        print(f"  --- Drafted message text (recover this before it's gone) ---")
        print(f"  {draft.message}")
        raise SystemExit(
            f"Job #{job['id']}: outreach message #{message_id} ({channel}, {len(draft.message)} chars) "
            f"was logged to the database, but writing its text to {path} failed: {exc}. "
            "The drafted text itself was not saved to disk - printed above for manual recovery."
        )

    print(f"Job #{job['id']}: {channel} draft for {contact_name} ({len(draft.message)} chars)")
    print("  ---")
    print(f"  {draft.message}")
    return draft


def _cmd_outreach(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        ensure_outreach_schema(conn)
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")

        contact_id, contact_name, contact_title = _resolve_contact(conn, job, args.contact_id)
        _draft_and_store_outreach(
            conn, job, args.channel, contact_id, contact_name, contact_title, args.purpose, args.profile_db, args.out_dir
        )
    finally:
        conn.close()


def _cmd_mark_applied(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")
        mark_applied(conn, args.job_id)
        print(f"Job #{args.job_id} ({job['job_title']} @ {job['company_name'] or '-'}): marked applied.")
    finally:
        conn.close()


def _cmd_discard(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")
        mark_discarded(conn, args.job_id)
        print(f"Job #{args.job_id} ({job['job_title']} @ {job['company_name'] or '-'}): discarded.")
    finally:
        conn.close()


def _cmd_due(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        applied = list_applied_jobs(conn)
    finally:
        conn.close()

    due_any = False
    for job in applied:
        milestone = due_milestone(
            job["applied_at"], job["reminder_3_sent_at"], job["reminder_7_sent_at"], job["reminder_14_sent_at"]
        )
        if milestone is None:
            continue
        due_any = True
        days = days_since(job["applied_at"])
        print(
            f"#{job['id']:>4}  {job['job_title']:<40} {job['company_name'] or '-':<30} "
            f"day {days} (day-{milestone} follow-up due)"
        )

    if not due_any:
        print("Nothing due right now.")


def _cmd_follow_up(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        ensure_outreach_schema(conn)
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")
        if job["applied_status"] != "applied":
            raise SystemExit(f"Job #{args.job_id} isn't marked applied yet - run `jobs mark-applied {args.job_id}` first.")

        milestone = due_milestone(
            job["applied_at"], job["reminder_3_sent_at"], job["reminder_7_sent_at"], job["reminder_14_sent_at"]
        )
        if milestone is None and not args.force:
            days = days_since(job["applied_at"])
            print(f"Nothing due yet for job #{args.job_id} - day {days} since applying. Pass --force to draft anyway.")
            return

        default_purpose = (
            f"Day {milestone or 0} polite follow-up: you applied to this role "
            f"{days_since(job['applied_at'])} days ago and haven't heard back. Check in on status "
            f"without being pushy, and restate genuine interest."
        )

        contact_id, contact_name, contact_title = _resolve_contact(conn, job, args.contact_id)
        draft = _draft_and_store_outreach(
            conn,
            job,
            args.channel,
            contact_id,
            contact_name,
            contact_title,
            args.purpose or default_purpose,
            args.profile_db,
            args.out_dir,
        )

        if draft is not None and milestone is not None:
            mark_reminders_sent_through(conn, args.job_id, milestone)
            print(f"  (reminders marked sent through day {milestone})")
    finally:
        conn.close()


def _cmd_set_employer(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")
        update_employer_name(conn, args.job_id, args.name)
        print(f"Job #{args.job_id}: employer set to '{args.name}'")
        if not args.no_check:
            _run_sponsor_check(conn, args.sponsor_db, args.job_id, args.name, job["location"])
    finally:
        conn.close()


def _cmd_confirm_sponsor(args: argparse.Namespace) -> None:
    """Manually assert a sponsor verdict after verifying it yourself (location
    match against the register, a browser extension, etc.) - for when neither
    an exact nor fuzzy register match resolved confidently enough."""
    conn = connect(args.db)
    try:
        job = get_job(conn, args.job_id)
        if job is None:
            raise SystemExit(f"No job #{args.job_id} found in {args.db}")

        update_sponsor_verdict(
            conn,
            args.job_id,
            status=USER_CONFIRMED,
            reason=f"Manually confirmed by user{f' via {args.source}' if args.source else ''} - not verified directly against the register lookup.",
            matched_name=args.name,
            rating=args.rating,
            route=args.route,
            town_city=args.town_city,
            county=args.county,
        )
        print(f"Job #{args.job_id}: sponsor manually confirmed as '{args.name}' ({args.town_city or '-'}).")
    finally:
        conn.close()


def _cmd_list(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        rows = list_jobs(conn, limit=args.limit)
    finally:
        conn.close()
    for row in rows:
        agency = " [agency]" if row["is_agency_posting"] else ""
        sponsor = row["sponsor_status"] or "unchecked"
        salary = row["salary_status"] or "unchecked"
        match = f"{row['match_score']}/100 {row['match_verdict']}" if row["match_score"] is not None else "unchecked"
        applied = row["applied_status"] or "pending"
        print(
            f"#{row['id']:>4}  {row['job_title']:<40} {row['company_name'] or '-':<30}"
            f"{agency:<9} [sponsor:{sponsor}] [salary:{salary}] [match:{match}] [{applied}]"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobs", description="Job posting intake")
    subparsers = parser.add_subparsers(dest="command", required=True)

    intake_parser = subparsers.add_parser(
        "intake",
        help="Paste a job posting in, extract fields, and check sponsor status + salary threshold + match score",
    )
    intake_parser.add_argument("--file", help="Path to a text file containing the job posting (else reads stdin)")
    intake_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    intake_parser.add_argument("--sponsor-db", default=DEFAULT_SPONSOR_DB, help="Sponsor register SQLite db path")
    intake_parser.add_argument("--profile-db", default=DEFAULT_PROFILE_DB, help="Candidate profile SQLite db path")
    intake_parser.set_defaults(func=_cmd_intake)

    sponsor_check_parser = subparsers.add_parser("sponsor-check", help="Re-run the sponsor status check for a stored job")
    sponsor_check_parser.add_argument("job_id", type=int)
    sponsor_check_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    sponsor_check_parser.add_argument("--sponsor-db", default=DEFAULT_SPONSOR_DB, help="Sponsor register SQLite db path")
    sponsor_check_parser.set_defaults(func=_cmd_sponsor_check)

    confirm_sponsor_parser = subparsers.add_parser(
        "confirm-sponsor",
        help="Manually assert a sponsor verdict after verifying it yourself (location match, browser extension, etc.)",
    )
    confirm_sponsor_parser.add_argument("job_id", type=int)
    confirm_sponsor_parser.add_argument("--name", required=True, help="The register entry name you confirmed")
    confirm_sponsor_parser.add_argument("--town-city", help="The register entry's town/city, for your own record")
    confirm_sponsor_parser.add_argument("--county", help="The register entry's county, for your own record")
    confirm_sponsor_parser.add_argument("--rating", default="Worker (A rating)")
    confirm_sponsor_parser.add_argument("--route", default="Skilled Worker")
    confirm_sponsor_parser.add_argument("--source", help="How you verified it, e.g. 'browser extension' - stored in the reason")
    confirm_sponsor_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    confirm_sponsor_parser.set_defaults(func=_cmd_confirm_sponsor)

    salary_check_parser = subparsers.add_parser("salary-check", help="Re-run the salary threshold check for a stored job")
    salary_check_parser.add_argument("job_id", type=int)
    salary_check_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    salary_check_parser.set_defaults(func=_cmd_salary_check)

    match_score_parser = subparsers.add_parser("match-score", help="Re-run match scoring for a stored job")
    match_score_parser.add_argument("job_id", type=int)
    match_score_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    match_score_parser.add_argument("--profile-db", default=DEFAULT_PROFILE_DB, help="Candidate profile SQLite db path")
    match_score_parser.set_defaults(func=_cmd_match_score)

    tailor_parser = subparsers.add_parser(
        "tailor", help="Generate a tailored resume + cover letter for a stored job (run after match-score)"
    )
    tailor_parser.add_argument("job_id", type=int)
    tailor_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    tailor_parser.add_argument("--profile-db", default=DEFAULT_PROFILE_DB, help="Candidate profile SQLite db path")
    tailor_parser.add_argument("--out-dir", default=DEFAULT_TAILOR_OUT_DIR, help="Directory to write the output files to")
    tailor_parser.add_argument("--force", action="store_true", help="Regenerate even if cached for this resume+job pair")
    tailor_parser.set_defaults(func=_cmd_tailor)

    tailor_docx_parser = subparsers.add_parser(
        "tailor-docx",
        help="Generate a tailored .docx resume (same fonts/formatting as your source file) + cover letter, saved under cv/generated_cv/<company>/",
    )
    tailor_docx_parser.add_argument("job_id", type=int)
    tailor_docx_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    tailor_docx_parser.add_argument("--profile-db", default=DEFAULT_PROFILE_DB, help="Candidate profile SQLite db path")
    tailor_docx_parser.add_argument("--resume-dir", default=DEFAULT_SOURCE_RESUME_DIR, help="Directory containing your source .docx resume")
    tailor_docx_parser.add_argument("--out-dir", default=DEFAULT_GENERATED_CV_DIR, help="Directory to write generated_cv/<company>/ into")
    tailor_docx_parser.add_argument("--force", action="store_true", help="Regenerate even if cached for this resume+job pair")
    tailor_docx_parser.set_defaults(func=_cmd_tailor_docx)

    migrate_legacy_tailoring_parser = subparsers.add_parser(
        "migrate-legacy-tailoring",
        help=(
            "One-time migration: back up DB-resident tailored text to .txt files, and rename "
            "old-format company-only-keyed docx files to job_id-keyed names where unambiguous"
        ),
    )
    migrate_legacy_tailoring_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    migrate_legacy_tailoring_parser.add_argument(
        "--out-dir", default=DEFAULT_TAILOR_OUT_DIR, help="Directory for legacy .txt backups (same default as `tailor`)"
    )
    migrate_legacy_tailoring_parser.add_argument(
        "--generated-cv-dir", default=DEFAULT_GENERATED_CV_DIR, help="Directory containing generated_cv/<company>/ old-format docx files"
    )
    migrate_legacy_tailoring_parser.set_defaults(func=_cmd_migrate_legacy_tailoring)

    migrate_legacy_outreach_parser = subparsers.add_parser(
        "migrate-legacy-outreach",
        help="One-time migration: back up DB-resident outreach message text to .txt files, then drop the legacy column",
    )
    migrate_legacy_outreach_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    migrate_legacy_outreach_parser.add_argument(
        "--out-dir", default=DEFAULT_GENERATED_CV_DIR, help="Directory for legacy outreach message .txt backups"
    )
    migrate_legacy_outreach_parser.set_defaults(func=_cmd_migrate_legacy_outreach)

    add_contact_parser = subparsers.add_parser(
        "add-contact", help="Add a contact you found yourself (LinkedIn, Apollo.io, etc.) for a job"
    )
    add_contact_parser.add_argument("job_id", type=int)
    add_contact_parser.add_argument("--name", required=True)
    add_contact_parser.add_argument("--title")
    add_contact_parser.add_argument("--linkedin-url")
    add_contact_parser.add_argument("--email")
    add_contact_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    add_contact_parser.set_defaults(func=_cmd_add_contact)

    contacts_parser = subparsers.add_parser("contacts", help="List contacts for a job")
    contacts_parser.add_argument("job_id", type=int)
    contacts_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    contacts_parser.set_defaults(func=_cmd_contacts)

    outreach_parser = subparsers.add_parser(
        "outreach", help="Draft a channel-aware cold outreach message for a job"
    )
    outreach_parser.add_argument("job_id", type=int)
    outreach_parser.add_argument("--channel", required=True, choices=[LINKEDIN_NOTE, EMAIL])
    outreach_parser.add_argument("--contact-id", type=int, help="Use a contact added via add-contact (else falls back to the job's own recruiter)")
    outreach_parser.add_argument("--purpose", help="e.g. 'ask who the redacted client is' - defaults to expressing interest")
    outreach_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    outreach_parser.add_argument("--profile-db", default=DEFAULT_PROFILE_DB, help="Candidate profile SQLite db path")
    outreach_parser.add_argument("--out-dir", default=DEFAULT_GENERATED_CV_DIR, help="Directory to write the drafted message .txt file into")
    outreach_parser.set_defaults(func=_cmd_outreach)

    mark_applied_parser = subparsers.add_parser("mark-applied", help="Mark a job applied and start its reminder clock")
    mark_applied_parser.add_argument("job_id", type=int)
    mark_applied_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    mark_applied_parser.set_defaults(func=_cmd_mark_applied)

    discard_parser = subparsers.add_parser("discard", help="Discard a job (not applying)")
    discard_parser.add_argument("job_id", type=int)
    discard_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    discard_parser.set_defaults(func=_cmd_discard)

    due_parser = subparsers.add_parser("due", help="List applied jobs with a day 3/7/14 follow-up due")
    due_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    due_parser.set_defaults(func=_cmd_due)

    follow_up_parser = subparsers.add_parser(
        "follow-up", help="Draft a follow-up for an applied job's due reminder (or --force to draft anyway)"
    )
    follow_up_parser.add_argument("job_id", type=int)
    follow_up_parser.add_argument("--channel", default=EMAIL, choices=[LINKEDIN_NOTE, EMAIL])
    follow_up_parser.add_argument("--contact-id", type=int)
    follow_up_parser.add_argument("--purpose", help="Override the default day-N check-in purpose")
    follow_up_parser.add_argument("--force", action="store_true", help="Draft even if no reminder is currently due")
    follow_up_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    follow_up_parser.add_argument("--profile-db", default=DEFAULT_PROFILE_DB, help="Candidate profile SQLite db path")
    follow_up_parser.add_argument("--out-dir", default=DEFAULT_GENERATED_CV_DIR, help="Directory to write the drafted message .txt file into")
    follow_up_parser.set_defaults(func=_cmd_follow_up)

    set_employer_parser = subparsers.add_parser(
        "set-employer",
        help="Manually set the real employer for a job (case c: you found it yourself) and re-check",
    )
    set_employer_parser.add_argument("job_id", type=int)
    set_employer_parser.add_argument("name", help="The real employer's name")
    set_employer_parser.add_argument("--db", default=DEFAULT_DB, help="Jobs SQLite db path")
    set_employer_parser.add_argument("--sponsor-db", default=DEFAULT_SPONSOR_DB, help="Sponsor register SQLite db path")
    set_employer_parser.add_argument("--no-check", action="store_true", help="Set the name without re-running the sponsor check")
    set_employer_parser.set_defaults(func=_cmd_set_employer)

    list_parser = subparsers.add_parser("list", help="List stored jobs")
    list_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite db path")
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.set_defaults(func=_cmd_list)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
