"""Streamlit page: paste a job posting, resolve its sponsor status against
the real register (plus your own company notes), then save and run the rest
of the pipeline (salary threshold + match score + tailoring + outreach).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from jobs.cli import DEFAULT_GENERATED_CV_DIR, _sanitize_filename
from jobs.db import connect as connect_jobs
from jobs.db import get_job, insert_job, mark_applied, mark_discarded, update_match_verdict, update_salary_verdict, update_sponsor_verdict
from jobs.extract import extract_job
from jobs.match_score import MATCH_THRESHOLD, STRONG_MATCH, match_verdict, score_job_match
from jobs.outreach import CHANNELS, EMAIL, LINKEDIN_NOTE, OutreachLengthError
from jobs.outreach_db import ensure_schema as ensure_outreach_schema
from jobs.outreach_db import insert_contact, list_contacts, list_outreach_messages
from jobs.salary_check import MEETS_THRESHOLD, check_salary_threshold
from jobs.sponsor_check import (
    CANNOT_VERIFY,
    CONFIRMED,
    FUZZY_MATCH,
    NOT_FOUND,
    USER_CONFIRMED,
    USER_FLAGGED,
    check_sponsor_status,
)
from jobs.tracker import APPLIED, DISCARDED, days_since, due_milestone
from jobs.ui_actions import draft_and_save_outreach, generate_tailored_docx_for_job
from register.db import OVERRIDE_ACTIVE, OVERRIDE_INACTIVE, OVERRIDE_LAPSED, OVERRIDE_UNCONFIRMED
from register.db import connect as connect_register
from register.db import lookup as register_lookup
from register.db import lookup_contains as register_lookup_contains
from register.db import lookup_override, upsert_override
from register.normalize import make_match_key
from resume.db import connect as connect_profile
from resume.db import get_latest_profile

JOBS_DB = "data/jobs.db"
SPONSOR_DB = "data/sponsors.db"
PROFILE_DB = "data/profile.db"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

STATUS_COLOR = {
    CONFIRMED: "green",
    USER_CONFIRMED: "green",
    FUZZY_MATCH: "orange",
    USER_FLAGGED: "red",
    NOT_FOUND: "red",
    CANNOT_VERIFY: "gray",
}

STATUS_LABELS = {
    OVERRIDE_ACTIVE: "Active - confirmed sponsoring",
    OVERRIDE_INACTIVE: "Licensed but not sponsoring anyone recently",
    OVERRIDE_LAPSED: "License lapsed / not renewed",
    OVERRIDE_UNCONFIRMED: "Unconfirmed - just noting this for now",
}
STATUS_ORDER = [OVERRIDE_ACTIVE, OVERRIDE_INACTIVE, OVERRIDE_LAPSED, OVERRIDE_UNCONFIRMED]

CHANNEL_LABELS = {
    LINKEDIN_NOTE: "LinkedIn connection note (≤300 chars)",
    EMAIL: "Email",
}
CHANNEL_ORDER = [LINKEDIN_NOTE, EMAIL]


def _reset_job_state() -> None:
    for key in ("extraction", "raw_text", "resolved_employer", "saved_job_id"):
        st.session_state.pop(key, None)


def _collect_candidates(employer_query: str) -> list[dict]:
    """Every plausible company for this name: your own override (if any),
    exact register matches, then fuzzy register matches - deduped by name."""
    conn = connect_register(SPONSOR_DB)
    try:
        match_key = make_match_key(employer_query)
        override = lookup_override(conn, match_key)
        exact_rows = register_lookup(conn, match_key)
        fuzzy_rows = [] if exact_rows else register_lookup_contains(conn, match_key)
    finally:
        conn.close()

    candidates = []
    seen_names = set()

    if override:
        candidates.append(
            {
                "name": override["organisation_name"],
                "town_city": override["town_city"] or "",
                "county": override["county"] or "",
                "rating": override["rating"] or "-",
                "route": override["route"] or "-",
                "status": override["status"],
            }
        )
        seen_names.add(override["organisation_name"])

    for row in list(exact_rows) + list(fuzzy_rows):
        if row["organisation_name"] in seen_names:
            continue
        seen_names.add(row["organisation_name"])
        candidates.append(
            {
                "name": row["organisation_name"],
                "town_city": row["town_city"] or "",
                "county": row["county"] or "",
                "rating": row["rating"],
                "route": row["route"],
                "status": None,
            }
        )
    return candidates


def _candidate_label(candidate: dict) -> str:
    location = f"{candidate['town_city'] or '-'}, {candidate['county'] or '-'}"
    tag = f" [your note: {STATUS_LABELS.get(candidate['status'], candidate['status'])}]" if candidate["status"] else ""
    return f"{candidate['name']} — {location} ({candidate['rating']}, {candidate['route']}){tag}"


def _render_status_update_form(matched_name: str, town_city: str, county: str, rating: str, route: str) -> None:
    with st.expander("Update this company's sponsorship status"):
        with st.form(f"update_status_form_{matched_name}"):
            st.caption("Register data can be stale, or a licensed company may have quietly stopped sponsoring.")
            status_choice = st.radio(
                "Current status (per your own knowledge)",
                options=STATUS_ORDER,
                format_func=lambda s: STATUS_LABELS[s],
            )
            notes = st.text_area("Notes (how did you find out?)", placeholder="e.g. checked via browser extension, recruiter told me, Companies House record")
            submitted = st.form_submit_button("Save status")
            if submitted:
                conn = connect_register(SPONSOR_DB)
                try:
                    upsert_override(
                        conn,
                        organisation_name=matched_name,
                        match_key=make_match_key(matched_name),
                        status=status_choice,
                        town_city=town_city,
                        county=county,
                        rating=rating if status_choice == OVERRIDE_ACTIVE else None,
                        route=route if status_choice == OVERRIDE_ACTIVE else None,
                        notes=notes,
                    )
                finally:
                    conn.close()
                st.success("Saved. Re-checking...")
                st.rerun()


def _render_download_buttons(out_dir: Path, key_prefix: str) -> None:
    resume_path = out_dir / "resume.docx"
    cover_letter_path = out_dir / "cover_letter.docx"
    cols = st.columns(2)
    if resume_path.exists():
        cols[0].download_button(
            "\U0001f4c4 Download resume (.docx)",
            data=resume_path.read_bytes(),
            file_name=f"{out_dir.name}_resume.docx",
            mime=DOCX_MIME,
            key=f"{key_prefix}_resume",
        )
    if cover_letter_path.exists():
        cols[1].download_button(
            "\U0001f4c4 Download cover letter (.docx)",
            data=cover_letter_path.read_bytes(),
            file_name=f"{out_dir.name}_cover_letter.docx",
            mime=DOCX_MIME,
            key=f"{key_prefix}_cover",
        )


st.title("\U0001f9ed Paste a Job Posting")

raw_text = st.text_area("Job posting text", height=250, key="raw_text_input")

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("Extract & Check Sponsor", type="primary", disabled=not raw_text.strip()):
        _reset_job_state()
        with st.spinner("Extracting job details..."):
            st.session_state.extraction = extract_job(raw_text)
        st.session_state.raw_text = raw_text
with col2:
    if st.button("Clear"):
        _reset_job_state()
        st.rerun()

extraction = st.session_state.get("extraction")

if extraction:
    st.divider()
    st.subheader(extraction.job_title)
    meta_cols = st.columns(3)
    meta_cols[0].markdown(f"**Company (as stated)**\n\n{extraction.company_name or '(not stated)'}")
    meta_cols[1].markdown(f"**Location**\n\n{extraction.location or '(not stated)'}")
    meta_cols[2].markdown(f"**Salary**\n\n{extraction.salary_raw or '(not stated)'}")

    employer_query = extraction.employer_name_for_sponsor_check or extraction.company_name

    if not employer_query:
        st.warning(
            "No employer name identified - likely an agency listing with the client redacted. "
            "Find the real employer yourself, then re-paste the posting with it included."
        )
    else:
        if st.session_state.get("resolved_employer") is None:
            candidates = _collect_candidates(employer_query)

            st.markdown("### Which company is this?")
            st.caption(f"Job posting states location: **{extraction.location or 'not stated'}** — compare each candidate below before picking one.")

            labels = [_candidate_label(c) for c in candidates]
            labels.append("❌ None of these match — add a new company")

            choice = st.radio("Candidates", options=range(len(labels)), format_func=lambda i: labels[i], key="candidate_choice", label_visibility="collapsed")

            if choice < len(candidates):
                if st.button("Confirm this company"):
                    st.session_state.resolved_employer = candidates[choice]["name"]
                    st.rerun()
            else:
                with st.form("add_new_company_form"):
                    st.write("Add a new company entry")
                    new_name = st.text_input("Company name", value=employer_query)
                    new_town = st.text_input("Town/City", value="")
                    new_county = st.text_input("County", value="")
                    new_status = st.radio("Sponsorship status", options=STATUS_ORDER, format_func=lambda s: STATUS_LABELS[s])
                    new_notes = st.text_area("Notes (how did you verify this?)")
                    submitted = st.form_submit_button("Save company & continue")
                    if submitted and new_name.strip():
                        conn = connect_register(SPONSOR_DB)
                        try:
                            upsert_override(
                                conn,
                                organisation_name=new_name,
                                match_key=make_match_key(new_name),
                                status=new_status,
                                town_city=new_town,
                                county=new_county,
                                rating="Worker (A rating)" if new_status == OVERRIDE_ACTIVE else None,
                                route="Skilled Worker" if new_status == OVERRIDE_ACTIVE else None,
                                notes=new_notes,
                            )
                        finally:
                            conn.close()
                        st.session_state.resolved_employer = new_name
                        st.rerun()

        resolved_employer = st.session_state.get("resolved_employer")
        if resolved_employer:
            conn = connect_register(SPONSOR_DB)
            try:
                verdict = check_sponsor_status(conn, resolved_employer)
            finally:
                conn.close()

            st.markdown("### Sponsor Verdict")
            color = STATUS_COLOR.get(verdict.status, "gray")
            st.markdown(f":{color}[**{verdict.status.upper()}**] — {verdict.matched_name or resolved_employer}")
            if verdict.town_city:
                st.caption(f"Register location: {verdict.town_city}, {verdict.county}")
            st.write(verdict.reason or "")

            if st.button("Choose a different company"):
                st.session_state.resolved_employer = None
                st.rerun()

            _render_status_update_form(
                verdict.matched_name or resolved_employer,
                verdict.town_city or "",
                verdict.county or "",
                verdict.rating or "Worker (A rating)",
                verdict.route or "Skilled Worker",
            )

            st.divider()
            if st.session_state.get("saved_job_id"):
                st.success(f"Saved as job #{st.session_state.saved_job_id}")
            elif st.button("Save job & run salary/match checks", type="primary"):
                jobs_conn = connect_jobs(JOBS_DB)
                try:
                    job_id = insert_job(jobs_conn, st.session_state.raw_text, extraction)
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

                    salary_verdict = check_salary_threshold(extraction.job_title, extraction.salary_raw)
                    update_salary_verdict(
                        jobs_conn,
                        job_id,
                        status=salary_verdict.status,
                        reason=salary_verdict.reason,
                        offered=salary_verdict.offered_salary,
                        threshold=salary_verdict.threshold,
                        soc_code=salary_verdict.soc_code,
                        soc_job_type=salary_verdict.soc_job_type,
                    )

                    profile_conn = connect_profile(PROFILE_DB)
                    try:
                        profile = get_latest_profile(profile_conn)
                    finally:
                        profile_conn.close()

                    match_result = None
                    if profile:
                        with st.spinner("Scoring match against your resume..."):
                            match_result = score_job_match(st.session_state.raw_text, profile)
                        verdict_label = match_verdict(match_result.score)
                        update_match_verdict(
                            jobs_conn,
                            job_id,
                            score=match_result.score,
                            verdict=verdict_label,
                            matched_skills=match_result.matched_skills,
                            missing_skills=match_result.missing_skills,
                            reasoning=match_result.reasoning,
                        )
                finally:
                    jobs_conn.close()

                st.session_state.saved_job_id = job_id
                st.success(f"Saved as job #{job_id}")

                st.markdown(f"**Salary check:** {salary_verdict.status.upper()} — {salary_verdict.reason}")
                if match_result:
                    label = "STRONG MATCH" if verdict_label == STRONG_MATCH else "WEAK MATCH"
                    st.markdown(f"**Match score:** {match_result.score}/100 ({label}, threshold {MATCH_THRESHOLD})")
                    st.caption(match_result.reasoning)
                else:
                    st.info("No resume on file yet - match score skipped. Add one via `resume add`.")

            saved_job_id = st.session_state.get("saved_job_id")
            if saved_job_id:
                jobs_conn = connect_jobs(JOBS_DB)
                try:
                    saved_job = get_job(jobs_conn, saved_job_id)
                finally:
                    jobs_conn.close()

                company_slug = _sanitize_filename(saved_job["company_name"] or f"job_{saved_job_id}")
                out_dir = Path(DEFAULT_GENERATED_CV_DIR) / company_slug
                already_generated = (out_dir / "resume.docx").exists() and (out_dir / "cover_letter.docx").exists()

                st.divider()
                st.markdown("### Tailored Resume & Cover Letter")
                st.caption("Same fonts/styles as your source resume - only the wording changes, capped at 2 pages.")

                label = "Regenerate tailored resume & cover letter" if already_generated else "Generate tailored resume & cover letter"
                if st.button(label):
                    with st.spinner("Tailoring your resume - keeping your original formatting..."):
                        try:
                            out_dir, warning = generate_tailored_docx_for_job(saved_job_id, JOBS_DB, PROFILE_DB)
                        except SystemExit as exc:
                            st.error(str(exc))
                        else:
                            st.success(f"Saved to {out_dir}/")
                            if warning:
                                st.warning(warning)
                            st.rerun()

                if already_generated:
                    _render_download_buttons(out_dir, key_prefix="current")

                st.divider()
                st.markdown("### Recruiter Outreach")

                jobs_conn = connect_jobs(JOBS_DB)
                try:
                    ensure_outreach_schema(jobs_conn)
                    contacts = list_contacts(jobs_conn, saved_job_id)
                    past_messages = list_outreach_messages(jobs_conn, saved_job_id)
                finally:
                    jobs_conn.close()

                contact_options = []
                if saved_job["recruiter_name"]:
                    contact_options.append({"id": None, "name": saved_job["recruiter_name"], "title": "Recruiter (from posting)"})
                for contact in contacts:
                    contact_options.append({"id": contact["id"], "name": contact["name"], "title": contact["title"] or "-"})

                contact_labels = [f"{c['name']} — {c['title']}" for c in contact_options]
                contact_labels.append("+ Add a new contact")

                contact_choice = st.radio(
                    "Who are you messaging?",
                    options=range(len(contact_labels)),
                    format_func=lambda i: contact_labels[i],
                    key=f"outreach_contact_choice_{saved_job_id}",
                )

                if contact_choice == len(contact_options):
                    with st.form("add_contact_form"):
                        new_contact_name = st.text_input("Name")
                        new_contact_title = st.text_input("Title (optional)")
                        new_contact_linkedin = st.text_input("LinkedIn URL (optional)")
                        new_contact_email = st.text_input("Email (optional)")
                        if st.form_submit_button("Save contact") and new_contact_name.strip():
                            jobs_conn = connect_jobs(JOBS_DB)
                            try:
                                ensure_outreach_schema(jobs_conn)
                                insert_contact(
                                    jobs_conn,
                                    saved_job_id,
                                    new_contact_name,
                                    title=new_contact_title or None,
                                    linkedin_url=new_contact_linkedin or None,
                                    email=new_contact_email or None,
                                )
                            finally:
                                jobs_conn.close()
                            st.rerun()
                else:
                    selected_contact = contact_options[contact_choice]
                    channel = st.radio(
                        "Channel",
                        options=CHANNEL_ORDER,
                        format_func=lambda c: CHANNEL_LABELS[c],
                        key=f"outreach_channel_{saved_job_id}",
                    )
                    purpose = st.text_input(
                        "Purpose (optional)",
                        placeholder="e.g. Following up after applying online",
                        key=f"outreach_purpose_{saved_job_id}",
                    )

                    if st.button("Draft outreach message"):
                        with st.spinner("Drafting your message..."):
                            try:
                                draft = draft_and_save_outreach(
                                    saved_job_id,
                                    channel,
                                    selected_contact["id"],
                                    selected_contact["name"],
                                    selected_contact["title"],
                                    purpose or None,
                                    JOBS_DB,
                                    PROFILE_DB,
                                )
                            except SystemExit as exc:
                                st.error(str(exc))
                            except OutreachLengthError as exc:
                                st.error(
                                    f"Draft rejected: {exc.char_count} chars, over the {exc.limit}-char "
                                    "limit for this channel. Not saved."
                                )
                                st.text_area("Over-length draft (not saved)", exc.draft_text, height=150)
                            else:
                                st.session_state[f"outreach_draft_{saved_job_id}"] = draft.message
                                st.success(f"Drafted ({len(draft.message)} chars) and saved.")
                                st.rerun()

                    drafted_message = st.session_state.get(f"outreach_draft_{saved_job_id}")
                    if drafted_message:
                        st.text_area("Drafted message", drafted_message, height=200, key=f"outreach_draft_display_{saved_job_id}")

                if past_messages:
                    with st.expander(f"Message history ({len(past_messages)})"):
                        for msg in past_messages:
                            channel_label = CHANNEL_LABELS.get(msg["channel"], msg["channel"])
                            st.caption(f"{msg['created_at'][:10]} - {channel_label} to {msg['contact_name']} ({msg['char_count']} chars)")
                            st.text(msg["message"])
                            st.divider()

                st.divider()
                st.markdown("### Application Status")

                if saved_job["applied_status"] == APPLIED:
                    days = days_since(saved_job["applied_at"])
                    st.success(f"Applied {days} day{'s' if days != 1 else ''} ago.")
                    milestone = due_milestone(
                        saved_job["applied_at"],
                        saved_job["reminder_3_sent_at"],
                        saved_job["reminder_7_sent_at"],
                        saved_job["reminder_14_sent_at"],
                    )
                    if milestone:
                        st.warning(f"Day-{milestone} follow-up is due - see the Application Tracker on the Jobs List page.")
                    if st.button("Mark discarded", key=f"discard_{saved_job_id}"):
                        jobs_conn = connect_jobs(JOBS_DB)
                        try:
                            mark_discarded(jobs_conn, saved_job_id)
                        finally:
                            jobs_conn.close()
                        st.rerun()
                elif saved_job["applied_status"] == DISCARDED:
                    st.info("Discarded.")
                    if st.button("Re-mark as applied", key=f"reapply_{saved_job_id}"):
                        jobs_conn = connect_jobs(JOBS_DB)
                        try:
                            mark_applied(jobs_conn, saved_job_id)
                        finally:
                            jobs_conn.close()
                        st.rerun()
                else:
                    if st.button("Mark as applied", key=f"apply_{saved_job_id}", type="primary"):
                        jobs_conn = connect_jobs(JOBS_DB)
                        try:
                            mark_applied(jobs_conn, saved_job_id)
                        finally:
                            jobs_conn.close()
                        st.rerun()

st.divider()
st.caption("Looking for your application tracker or past generated documents? They've moved to the **Jobs List** page.")
