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
