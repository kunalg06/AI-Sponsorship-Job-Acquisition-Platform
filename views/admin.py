"""Streamlit page: admin/maintenance actions for this app.

Currently just one thing: loading the UK sponsor register from the
source CSV. Streamlit Community Cloud has no shell access, and data/*.db
is gitignored, so a fresh Cloud deploy starts with an empty sponsors.db
with no way to load it except `uv run python -m register.cli ingest` from
a local terminal - which Cloud doesn't offer. This page wraps that exact
same pipeline (`register.ingest.ingest`) behind a button instead.

Note: `register.cli.DEFAULT_SOURCE` is a specific dated gov.uk CSV
snapshot, not an auto-updating "latest register" endpoint - clicking
"Refresh" re-fetches that same file every time, so this only bootstraps
an empty Cloud deploy rather than keeping the register current over time.
"""

from __future__ import annotations

import streamlit as st

from register.cli import DEFAULT_DB, DEFAULT_SOURCE
from register.db import connect, count
from register.ingest import ingest
from resume.db import connect as connect_profile
from resume.db import get_latest_profile, insert_profile
from resume.extract import extract_profile, extract_text_from_docx

PROFILE_DB = "data/profile.db"

st.title("\u2699 Admin")

st.subheader("Sponsor Register")

try:
    conn = connect(DEFAULT_DB)
    try:
        sponsor_count = count(conn)
    finally:
        conn.close()
except Exception as exc:
    st.error(str(exc))
    st.stop()

st.markdown(f"**{sponsor_count} sponsors currently loaded**")

if st.button("Refresh sponsor register now", type="primary"):
    with st.spinner("Fetching and loading the sponsor register - this can take a while..."):
        try:
            summary = ingest(DEFAULT_SOURCE, DEFAULT_DB)
        except Exception as exc:
            st.error(str(exc))
        else:
            st.success(
                f"Loaded {summary['rows_loaded']} sponsors "
                f"(register dated {summary['source_updated'] or 'unknown'}). "
                f"Rows now in db: {summary['rows_in_db']}."
            )
            st.rerun()

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

uploaded_file = st.file_uploader("Upload your CV", type=["docx", "txt"])

if st.button("Extract & Register Profile", type="primary", disabled=uploaded_file is None):
    with st.spinner("Extracting profile from your CV..."):
        try:
            uploaded_file.seek(0)  # a prior failed attempt on the same upload may have already consumed the stream
            if uploaded_file.name.lower().endswith(".docx"):
                raw_text = extract_text_from_docx(uploaded_file)
            else:
                raw_text = uploaded_file.read().decode("utf-8")

            if not raw_text.strip():
                raise ValueError("No text found in the uploaded file.")

            profile = extract_profile(raw_text)

            conn = connect_profile(PROFILE_DB)
            try:
                profile_id = insert_profile(conn, raw_text, profile)
            finally:
                conn.close()
        except Exception as exc:
            st.error(str(exc))
        else:
            st.success(
                f"Stored profile #{profile_id} for {profile.full_name or '(name not stated)'} ({profile.seniority})."
            )
            st.rerun()
