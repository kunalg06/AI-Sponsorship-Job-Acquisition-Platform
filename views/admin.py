"""Streamlit page: admin/maintenance actions for this app.

Two things: loading the UK sponsor register from the source CSV, and
registering a resume/CV profile. Streamlit Community Cloud has no shell
access, and data/*.db is gitignored, so a fresh Cloud deploy starts with
empty sponsors.db/profile.db with no way to load them except CLI commands
from a local terminal - which Cloud doesn't offer. This page wraps those
same pipelines (`register.ingest.ingest`, `resume.extract.extract_profile`
+ `resume.db.insert_profile`) behind buttons instead.

Both actions are destructive/mutating in ways the app's other single-click
actions aren't (a whole-table wipe+reload; an insert that silently becomes
the new "latest" profile every match/tailor call reads), so both are gated
behind an `st.dialog` confirmation, and the CV-upload path additionally
guards against a double-submit re-registering the same file.

Note: `register.cli.DEFAULT_SOURCE` is a specific dated gov.uk CSV
snapshot, not an auto-updating "latest register" endpoint - clicking
"Refresh" re-fetches that same file every time, so this only bootstraps
an empty Cloud deploy rather than keeping the register current over time.
The refresh flow does detect and report when a fetch returned the same
snapshot that was already loaded, so a no-op refresh isn't mistaken for
a real update.
"""

from __future__ import annotations

import hashlib

import streamlit as st

from jobs.ui_actions import error_display_text
from register.cli import DEFAULT_DB, DEFAULT_SOURCE
from register.db import connect, count, get_current_source_updated, is_noop_refresh
from register.ingest import ingest
from resume.db import connect as connect_profile
from resume.db import get_latest_profile, insert_profile
from resume.extract import ResumeProfile, extract_profile, extract_text_from_docx

PROFILE_DB = "data/profile.db"

st.title("⚙ Admin")

st.subheader("Sponsor Register")

try:
    conn = connect(DEFAULT_DB)
    try:
        sponsor_count = count(conn)
    finally:
        conn.close()
except Exception as exc:
    st.error(error_display_text(exc))
    st.stop()


@st.dialog("Confirm sponsor register refresh")
def _confirm_refresh_dialog() -> None:
    st.write(
        f"This replaces all {sponsor_count} currently loaded sponsor rows with a fresh "
        "download from the source register. This can take a while."
    )
    col1, col2 = st.columns(2)
    if col1.button("Cancel"):
        st.rerun()
    if col2.button("Yes, refresh now", type="primary"):
        with st.spinner("Fetching and loading the sponsor register - this can take a while..."):
            try:
                # Captured here, immediately before the mutation, not at page-load
                # time - a page-load-time capture would already reflect the *new*
                # state by the time this dialog's own rerun redraws the page.
                fetch_conn = connect(DEFAULT_DB)
                try:
                    previous_source_updated = get_current_source_updated(fetch_conn)
                finally:
                    fetch_conn.close()
                summary = ingest(DEFAULT_SOURCE, DEFAULT_DB)
            except Exception as exc:
                st.error(error_display_text(exc))
            else:
                summary["previous_source_updated"] = previous_source_updated
                st.session_state["register_refresh_result"] = summary
                st.rerun()


st.markdown(f"**{sponsor_count} sponsors currently loaded**")

if st.button("Refresh sponsor register now", type="primary"):
    _confirm_refresh_dialog()

refresh_result = st.session_state.pop("register_refresh_result", None)
if refresh_result:
    if is_noop_refresh(refresh_result["previous_source_updated"], refresh_result["source_updated"]):
        st.info(
            f"Already up to date (register dated {refresh_result['source_updated']}). "
            f"Rows in db: {refresh_result['rows_in_db']}."
        )
    else:
        st.success(
            f"Loaded {refresh_result['rows_loaded']} sponsors "
            f"(register dated {refresh_result['source_updated'] or 'unknown'}). "
            f"Rows now in db: {refresh_result['rows_in_db']}."
        )

st.divider()
st.subheader("Resume / CV Profile")

profile_conn = connect_profile(PROFILE_DB)
try:
    latest_profile = get_latest_profile(profile_conn)
finally:
    profile_conn.close()

if latest_profile:
    st.markdown(f"**Latest profile on file:** {latest_profile.full_name or '(name not stated)'} — {latest_profile.seniority}")
else:
    st.markdown("No profile stored yet")


def _register_pending_profile() -> None:
    pending = st.session_state.pop("pending_cv_profile", None)
    if not pending:
        return
    try:
        conn = connect_profile(PROFILE_DB)
        try:
            profile_id = insert_profile(conn, pending["raw_text"], pending["profile"])
        finally:
            conn.close()
    except Exception as exc:
        st.error(error_display_text(exc))
        st.session_state["cv_registration_in_progress"] = False
        return
    st.session_state["last_registered_cv_hash"] = pending["content_hash"]
    st.session_state["cv_registration_in_progress"] = False
    st.session_state["cv_registration_result"] = {
        "profile_id": profile_id,
        "full_name": pending["profile"].full_name,
        "seniority": pending["profile"].seniority,
    }
    st.rerun()


def _clear_pending_cv_profile() -> None:
    """Shared by the Cancel button and the dialog's `on_dismiss` - X/backdrop/
    ESC dismissal must clear the same state Cancel does, or the dialog
    reopens on the next rerun (it's gated on `pending_cv_profile` staying
    set). Idempotent (safe to call more than once for one dismissal) since
    both operations are already a no-op on an already-cleared state."""
    st.session_state.pop("pending_cv_profile", None)
    st.session_state["cv_registration_in_progress"] = False


@st.dialog("Confirm new profile replaces current one", on_dismiss=_clear_pending_cv_profile)
def _confirm_supersede_dialog(pending: dict, current: ResumeProfile) -> None:
    st.write(
        f"**Current latest profile:** {current.full_name or '(name not stated)'} — {current.seniority}\n\n"
        f"**New profile:** {pending['profile'].full_name or '(name not stated)'} — {pending['profile'].seniority}\n\n"
        "Match-scoring and tailoring always read the latest profile - every job "
        "already in the pipeline would start using this one. Replace it?"
    )
    col1, col2 = st.columns(2)
    if col1.button("Cancel"):
        _clear_pending_cv_profile()
        st.rerun()
    if col2.button("Yes, replace it", type="primary"):
        _register_pending_profile()


uploaded_file = st.file_uploader("Upload your CV", type=["docx", "txt"])

# Hash of the raw bytes, not the extracted text - can't fail the way text
# extraction can (no parsing), so this identity check costs nothing extra
# and can't change when a corrupt file's error surfaces. Content-based (not
# `uploaded_file.file_id`, a widget identity that changes on every fresh
# pick from disk) so re-selecting the *same bytes* via the OS file picker is
# still recognized as already registered. Narrower than "same logical CV":
# a re-save by a different Word/LibreOffice version can change bytes (e.g.
# XML metadata/timestamps) without changing visible content, and would hash
# differently - accepted, not fixed, since catching that needs the extracted
# text this check deliberately avoids depending on.
uploaded_content_hash = hashlib.sha256(uploaded_file.getvalue()).hexdigest() if uploaded_file is not None else None

already_registered = (
    # The `uploaded_file is not None` check isn't redundant with the hash
    # comparison - drop it and a no-file state (both sides None) would
    # misread as "already registered".
    uploaded_file is not None
    and st.session_state.get("last_registered_cv_hash") == uploaded_content_hash
)
cv_registration_in_progress = st.session_state.get("cv_registration_in_progress", False)

register_clicked = st.button(
    "Extract & Register Profile",
    type="primary",
    disabled=uploaded_file is None or already_registered or cv_registration_in_progress,
)

if already_registered:
    st.info("This file has already been registered as the latest profile.")

# Re-check the guard flags here, not just in the button's `disabled=` kwarg:
# `disabled` only affects how the button renders on the *next* frame - a
# click event already in flight (a fast double-click racing the disabled
# state back to the browser) still reports `register_clicked=True` regardless
# of what this run computes, so the actual work must be skipped explicitly.
if register_clicked and not already_registered and not cv_registration_in_progress:
    st.session_state["cv_registration_in_progress"] = True
    try:
        uploaded_file.seek(0)  # a prior failed attempt on the same upload may have already consumed the stream
        if uploaded_file.name.lower().endswith(".docx"):
            raw_text = extract_text_from_docx(uploaded_file)
        else:
            raw_text = uploaded_file.read().decode("utf-8")

        if not raw_text.strip():
            raise ValueError("No text found in the uploaded file.")

        with st.spinner("Extracting profile from your CV..."):
            profile = extract_profile(raw_text)
    except Exception as exc:
        st.error(error_display_text(exc))
        st.session_state["cv_registration_in_progress"] = False
    else:
        st.session_state["pending_cv_profile"] = {
            "raw_text": raw_text,
            "profile": profile,
            "content_hash": uploaded_content_hash,
        }
        if latest_profile is None:
            # Nothing to supersede yet - register directly, no confirmation needed.
            _register_pending_profile()

pending_cv_profile = st.session_state.get("pending_cv_profile")
if pending_cv_profile and latest_profile is not None:
    _confirm_supersede_dialog(pending_cv_profile, latest_profile)

cv_registration_result = st.session_state.pop("cv_registration_result", None)
if cv_registration_result:
    st.success(
        f"Stored profile #{cv_registration_result['profile_id']} for "
        f"{cv_registration_result['full_name'] or '(name not stated)'} "
        f"({cv_registration_result['seniority']})."
    )
