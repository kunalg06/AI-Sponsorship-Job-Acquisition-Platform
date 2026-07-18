"""Streamlit page: the dashboard half of the app - browse every pasted job,
inspect its verdicts, manage application status, tailor a resume, draft
outreach, and download tailored docs for any stored job. Also hosts the two
global views that don't belong to a single job: the day 3/7/14 follow-up
tracker and the generated-documents browser.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from jobs.cli import DEFAULT_GENERATED_CV_DIR, _read_outreach_message_text, _resolve_contact, _tailored_docx_paths
from jobs.db import connect as connect_jobs
from jobs.db import get_job, list_applied_jobs, mark_applied, mark_discarded, mark_reminders_sent_through
from jobs.digest import list_due_reminders
from jobs.outreach import EMAIL, LINKEDIN_NOTE, OutreachLengthError
from jobs.outreach_db import ensure_schema as ensure_outreach_schema
from jobs.outreach_db import insert_contact, list_contacts, list_outreach_messages
from jobs.sponsor_check import CANNOT_VERIFY, CONFIRMED, FUZZY_MATCH, NOT_FOUND, USER_CONFIRMED, USER_FLAGGED
from jobs.tracker import APPLIED, DISCARDED, days_since, due_milestone
from jobs.ui_actions import draft_and_save_outreach, error_display_text, generate_tailored_docx_for_job

JOBS_DB = "data/jobs.db"
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

CHANNEL_LABELS = {
    LINKEDIN_NOTE: "LinkedIn connection note (≤300 chars)",
    EMAIL: "Email",
}
CHANNEL_ORDER = [LINKEDIN_NOTE, EMAIL]


def _render_download_buttons(resume_path: Path, cover_letter_path: Path, key_prefix: str) -> None:
    cols = st.columns(2)
    if resume_path.exists():
        cols[0].download_button(
            "\U0001f4c4 Download resume (.docx)",
            data=resume_path.read_bytes(),
            file_name=resume_path.name,
            mime=DOCX_MIME,
            key=f"{key_prefix}_resume",
        )
    if cover_letter_path.exists():
        cols[1].download_button(
            "\U0001f4c4 Download cover letter (.docx)",
            data=cover_letter_path.read_bytes(),
            file_name=cover_letter_path.name,
            mime=DOCX_MIME,
            key=f"{key_prefix}_cover",
        )


st.title("\U0001f4cb Jobs")

with st.expander("\U0001f4ec Application Tracker (day 3 / 7 / 14 follow-ups)"):
    jobs_conn = connect_jobs(JOBS_DB)
    try:
        applied_jobs = list_applied_jobs(jobs_conn)
        due_reminders = list_due_reminders(applied_jobs)
    finally:
        jobs_conn.close()

    if not applied_jobs:
        st.caption("No applications marked yet - use \"Mark as applied\" below once you've applied to a job.")
    else:
        jobs_by_id = {job["id"]: job for job in applied_jobs}

        if due_reminders:
            st.markdown("**Due for follow-up:**")
            for reminder in due_reminders:
                tracked_job = jobs_by_id[reminder.job_id]
                milestone = reminder.milestone
                days = reminder.days
                st.markdown(
                    f"**#{tracked_job['id']} {tracked_job['job_title']}** @ {tracked_job['company_name'] or '-'} "
                    f"— day {days} (day-{milestone} follow-up due)"
                )

                tracker_channel = st.radio(
                    "Channel",
                    options=CHANNEL_ORDER,
                    format_func=lambda c: CHANNEL_LABELS[c],
                    key=f"tracker_channel_{tracked_job['id']}",
                    horizontal=True,
                )
                if st.button(f"Draft day-{milestone} follow-up", key=f"tracker_followup_{tracked_job['id']}"):
                    with st.spinner("Drafting follow-up..."):
                        jobs_conn = connect_jobs(JOBS_DB)
                        try:
                            contact_id, contact_name, contact_title = _resolve_contact(jobs_conn, tracked_job, None)
                        except SystemExit as exc:
                            st.error(error_display_text(exc))
                        else:
                            tracker_purpose = (
                                f"Day {milestone} polite follow-up: you applied to this role {days} days "
                                "ago and haven't heard back. Check in on status without being pushy, and "
                                "restate genuine interest."
                            )
                            try:
                                tracker_draft = draft_and_save_outreach(
                                    tracked_job["id"],
                                    tracker_channel,
                                    contact_id,
                                    contact_name,
                                    contact_title,
                                    tracker_purpose,
                                    JOBS_DB,
                                    PROFILE_DB,
                                )
                            except SystemExit as exc:
                                st.error(error_display_text(exc))
                            except OutreachLengthError as exc:
                                st.error(
                                    f"Draft rejected: {exc.char_count} chars, over the {exc.limit}-char "
                                    "limit for this channel. Not saved."
                                )
                                st.text_area("Over-length draft (not saved)", exc.draft_text, height=150)
                            else:
                                mark_reminders_sent_through(jobs_conn, tracked_job["id"], milestone)
                                st.success(f"Drafted ({len(tracker_draft.message)} chars) and marked day-{milestone} follow-up sent.")
                                st.text_area(
                                    "Drafted follow-up",
                                    tracker_draft.message,
                                    height=200,
                                    key=f"tracker_draft_{tracked_job['id']}",
                                )
                        finally:
                            jobs_conn.close()
                st.divider()
        else:
            st.caption("Nothing due right now.")

        st.markdown("**All applied jobs:**")
        for job in applied_jobs:
            st.caption(
                f"#{job['id']} {job['job_title']} @ {job['company_name'] or '-'} — day {days_since(job['applied_at'])}"
            )

with st.expander("\U0001f4c1 All previously generated resumes & cover letters"):
    generated_root = Path(DEFAULT_GENERATED_CV_DIR)
    company_dirs = sorted(d for d in generated_root.iterdir() if d.is_dir()) if generated_root.exists() else []
    if not company_dirs:
        st.caption("Nothing generated yet.")
    for company_dir in company_dirs:
        # job_id-keyed filenames mean a company can have more than one
        # generated resume (one per role) - list each one separately rather
        # than assuming a single resume.docx/cover_letter.docx pair.
        resume_files = sorted(company_dir.glob("*_resume.docx"))
        if not resume_files:
            continue
        st.markdown(f"**{company_dir.name.replace('_', ' ')}**")
        for resume_path in resume_files:
            job_id_prefix = resume_path.name[: -len("_resume.docx")]
            cover_letter_path = company_dir / f"{job_id_prefix}_cover_letter.docx"
            st.caption(f"Job #{job_id_prefix}")
            _render_download_buttons(
                resume_path, cover_letter_path, key_prefix=f"browse_{company_dir.name}_{job_id_prefix}"
            )

st.divider()

conn = connect_jobs(JOBS_DB)
try:
    jobs = conn.execute(
        """
        SELECT id, job_title, company_name, applied_status
        FROM jobs ORDER BY id DESC
        """
    ).fetchall()
finally:
    conn.close()

if not jobs:
    st.info("No jobs pasted yet - go to the Paste a Job Posting page to paste your first job posting.")
else:
    filter_choice = st.radio(
        "Filter",
        options=["All", "Not yet decided", "Applied", "Discarded"],
        horizontal=True,
        label_visibility="collapsed",
    )

    def _matches_filter(job) -> bool:
        if filter_choice == "All":
            return True
        if filter_choice == "Applied":
            return job["applied_status"] == APPLIED
        if filter_choice == "Discarded":
            return job["applied_status"] == DISCARDED
        return job["applied_status"] not in (APPLIED, DISCARDED)

    filtered = [j for j in jobs if _matches_filter(j)]
    st.caption(f"{len(filtered)} of {len(jobs)} jobs")

    if not filtered:
        st.caption("Nothing matches this filter.")
    else:
        labels = [f"#{j['id']} {j['job_title']} @ {j['company_name'] or '-'}" for j in filtered]
        selected_index = st.radio(
            "Select a job", options=range(len(labels)), format_func=lambda i: labels[i], label_visibility="collapsed"
        )
        selected_id = filtered[selected_index]["id"]

        conn = connect_jobs(JOBS_DB)
        try:
            job = get_job(conn, selected_id)
        finally:
            conn.close()

        st.divider()
        st.subheader(job["job_title"])
        meta_cols = st.columns(3)
        meta_cols[0].markdown(f"**Company**\n\n{job['company_name'] or '-'}")
        meta_cols[1].markdown(f"**Location**\n\n{job['location'] or '-'}")
        meta_cols[2].markdown(f"**Salary**\n\n{job['salary_raw'] or '-'}")

        if job["sponsor_status"]:
            color = STATUS_COLOR.get(job["sponsor_status"], "gray")
            st.markdown(f"**Sponsor:** :{color}[{job['sponsor_status'].upper()}] — {job['sponsor_matched_name'] or '-'}")
            if job["sponsor_reason"]:
                st.caption(job["sponsor_reason"])
        if job["salary_status"]:
            st.markdown(f"**Salary check:** {job['salary_status'].upper()} — {job['salary_reason'] or ''}")
        if job["match_score"] is not None:
            st.markdown(f"**Match:** {job['match_score']}/100 ({job['match_verdict'] or '-'})")
            if job["match_reasoning"]:
                st.caption(job["match_reasoning"])

        st.divider()
        st.markdown("### Application Status")
        if job["applied_status"] == APPLIED:
            days = days_since(job["applied_at"])
            st.success(f"Applied {days} day{'s' if days != 1 else ''} ago.")
            milestone = due_milestone(
                job["applied_at"], job["reminder_3_sent_at"], job["reminder_7_sent_at"], job["reminder_14_sent_at"]
            )
            if milestone:
                st.warning(f"Day-{milestone} follow-up is due - see the Application Tracker above.")
            if st.button("Mark discarded", key=f"discard_{job['id']}"):
                jobs_conn = connect_jobs(JOBS_DB)
                try:
                    mark_discarded(jobs_conn, job["id"])
                finally:
                    jobs_conn.close()
                st.rerun()
        elif job["applied_status"] == DISCARDED:
            st.info("Discarded.")
            if st.button("Re-mark as applied", key=f"reapply_{job['id']}"):
                jobs_conn = connect_jobs(JOBS_DB)
                try:
                    mark_applied(jobs_conn, job["id"])
                finally:
                    jobs_conn.close()
                st.rerun()
        else:
            if st.button("Mark as applied", key=f"apply_{job['id']}", type="primary"):
                jobs_conn = connect_jobs(JOBS_DB)
                try:
                    mark_applied(jobs_conn, job["id"])
                finally:
                    jobs_conn.close()
                st.rerun()

        resume_path, cover_letter_path = _tailored_docx_paths(job["company_name"], job["id"], DEFAULT_GENERATED_CV_DIR)
        already_generated = resume_path.exists() and cover_letter_path.exists()

        st.divider()
        st.markdown("### Tailored Resume & Cover Letter")
        st.caption("Same fonts/styles as your source resume - only the wording changes, capped at 2 pages.")

        tailor_label = "Regenerate tailored resume & cover letter" if already_generated else "Generate tailored resume & cover letter"
        if st.button(tailor_label, key=f"tailor_{job['id']}"):
            with st.spinner("Tailoring your resume - keeping your original formatting..."):
                try:
                    out_dir, warning = generate_tailored_docx_for_job(
                        job["id"], JOBS_DB, PROFILE_DB, force=already_generated
                    )
                except SystemExit as exc:
                    st.error(error_display_text(exc))
                else:
                    st.success(f"Saved to {out_dir}/")
                    if warning:
                        st.warning(warning)
                    st.rerun()

        if already_generated:
            _render_download_buttons(resume_path, cover_letter_path, key_prefix=f"list_tailored_{job['id']}")

        st.divider()
        st.markdown("### Recruiter Outreach")

        jobs_conn = connect_jobs(JOBS_DB)
        try:
            ensure_outreach_schema(jobs_conn)
            contacts = list_contacts(jobs_conn, job["id"])
            past_messages = list_outreach_messages(jobs_conn, job["id"])
        finally:
            jobs_conn.close()

        contact_options = []
        if job["recruiter_name"]:
            contact_options.append({"id": None, "name": job["recruiter_name"], "title": "Recruiter (from posting)"})
        for contact in contacts:
            contact_options.append({"id": contact["id"], "name": contact["name"], "title": contact["title"] or "-"})

        contact_labels = [f"{c['name']} — {c['title']}" for c in contact_options]
        contact_labels.append("+ Add a new contact")

        contact_choice = st.radio(
            "Who are you messaging?",
            options=range(len(contact_labels)),
            format_func=lambda i: contact_labels[i],
            key=f"list_outreach_contact_choice_{job['id']}",
        )

        if contact_choice == len(contact_options):
            with st.form(f"list_add_contact_form_{job['id']}"):
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
                            job["id"],
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
                key=f"list_outreach_channel_{job['id']}",
            )
            purpose = st.text_input(
                "Purpose (optional)",
                placeholder="e.g. Following up after applying online",
                key=f"list_outreach_purpose_{job['id']}",
            )

            if st.button("Draft outreach message", key=f"list_draft_{job['id']}"):
                with st.spinner("Drafting your message..."):
                    try:
                        draft = draft_and_save_outreach(
                            job["id"],
                            channel,
                            selected_contact["id"],
                            selected_contact["name"],
                            selected_contact["title"],
                            purpose or None,
                            JOBS_DB,
                            PROFILE_DB,
                        )
                    except SystemExit as exc:
                        st.error(error_display_text(exc))
                    except OutreachLengthError as exc:
                        st.error(
                            f"Draft rejected: {exc.char_count} chars, over the {exc.limit}-char "
                            "limit for this channel. Not saved."
                        )
                        st.text_area("Over-length draft (not saved)", exc.draft_text, height=150)
                    else:
                        st.session_state[f"list_outreach_draft_{job['id']}"] = draft.message
                        st.success(f"Drafted ({len(draft.message)} chars) and saved.")
                        st.rerun()

            drafted_message = st.session_state.get(f"list_outreach_draft_{job['id']}")
            if drafted_message:
                st.text_area("Drafted message", drafted_message, height=200, key=f"list_outreach_draft_display_{job['id']}")

        if past_messages:
            with st.expander(f"Message history ({len(past_messages)})"):
                for msg in past_messages:
                    channel_label = CHANNEL_LABELS.get(msg["channel"], msg["channel"])
                    st.caption(f"{msg['created_at'][:10]} - {channel_label} to {msg['contact_name']} ({msg['char_count']} chars)")
                    message_text = _read_outreach_message_text(
                        job["company_name"], job["id"], msg["channel"], msg["id"], DEFAULT_GENERATED_CV_DIR
                    )
                    if message_text is not None:
                        st.text(message_text)
                    elif msg["write_failed_at"]:
                        st.caption("(drafted text failed to save to disk at the time - not recoverable)")
                    else:
                        st.caption("(message file not found)")
                    st.divider()

        with st.expander("Raw posting text"):
            st.text(job["raw_text"])
