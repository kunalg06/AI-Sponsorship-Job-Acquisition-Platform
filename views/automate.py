"""Streamlit page: the Automate review queue - Indeed-sourced postings
staged by `jobs stage-indeed` (run by a daily scheduled discovery agent, or
on demand as a live-session fallback) that haven't been reviewed yet. Each
row already went through the exact same sponsor-check/salary-check/
match-score pipeline a manually pasted job goes through - see
`_bmad-output/implementation-artifacts/spec-indeed-job-discovery.md`.

"Review" is deliberately shallow: clicking "Mark Reviewed" only clears
`discovery_reviewed_at` (see `jobs.db.mark_discovery_reviewed`) so the row
drops off this queue - it stays fully visible and unchanged in Jobs List
from then on, behaving exactly like any manually-pasted job. Applying stays
a manual click on the real Indeed apply link; nothing here submits an
application on the user's behalf.
"""

from __future__ import annotations

import streamlit as st

from jobs.db import connect as connect_jobs
from jobs.db import list_discovery_queue, mark_discovery_reviewed
from jobs.sponsor_check import CANNOT_VERIFY, CONFIRMED, FUZZY_MATCH, NOT_FOUND, SKIPPED, USER_CONFIRMED, USER_FLAGGED
from views.theme import set_page_wonk

JOBS_DB = "data/jobs.db"

# Mirrors views/jobs_list.py's own STATUS_COLOR exactly - same verdicts,
# same colors, so a sponsor badge never means something different depending
# on which page the user happens to be looking at.
STATUS_COLOR = {
    CONFIRMED: "green",
    USER_CONFIRMED: "green",
    FUZZY_MATCH: "orange",
    USER_FLAGGED: "red",
    NOT_FOUND: "red",
    CANNOT_VERIFY: "gray",
    SKIPPED: "blue",
}

set_page_wonk("low")  # a review queue is a working table, same register as Jobs List
st.title("\U0001f916 Automate")
st.caption(
    "Indeed postings found by the daily discovery search, already sponsor-checked, "
    "salary-checked, and match-scored - sorted by match score, then newest posted first. "
    "Nothing is hidden or hard-filtered here: review each candidate yourself and decide."
)

conn = connect_jobs(JOBS_DB)
try:
    queue = list_discovery_queue(conn)
finally:
    conn.close()

if not queue:
    st.info(
        "Nothing waiting for review right now - either the discovery agent hasn't run "
        "yet, or every staged candidate so far has been reviewed."
    )
else:
    st.caption(
        f"Showing up to 20 unreviewed candidates ({len(queue)} shown now), highest match first. "
        "There may be more waiting below these."
    )

    for job in queue:
        with st.container(border=True):
            st.subheader(job["job_title"])
            meta_cols = st.columns(3)
            meta_cols[0].markdown(f"**Company**\n\n{job['company_name'] or '-'}")
            meta_cols[1].markdown(f"**Location**\n\n{job['location'] or '-'}")
            meta_cols[2].markdown(f"**Posted**\n\n{job['source_posted_at'] or '-'}")

            if job["sponsor_status"]:
                color = STATUS_COLOR.get(job["sponsor_status"], "gray")
                st.markdown(
                    f"**Sponsor:** :{color}[{job['sponsor_status'].upper()}] — {job['sponsor_matched_name'] or '-'}"
                )
                st.caption(
                    "Checked against the listed company name. If this was posted by a recruiting "
                    "agency, verify the actual hiring employer yourself before relying on this."
                )
            if job["salary_status"]:
                st.markdown(f"**Salary check:** {job['salary_status'].upper()} — {job['salary_reason'] or ''}")
            if job["match_score"] is not None:
                st.markdown(f"**Match:** {job['match_score']}/100 ({job['match_verdict'] or '-'})")
            else:
                st.caption("Match score unavailable - no resume was on file yet when this was staged.")

            action_cols = st.columns(2)
            if job["apply_url"]:
                action_cols[0].link_button("Apply on Indeed", job["apply_url"])
            if action_cols[1].button("Mark Reviewed", key=f"mark_reviewed_{job['id']}"):
                jobs_conn = connect_jobs(JOBS_DB)
                try:
                    mark_discovery_reviewed(jobs_conn, job["id"])
                finally:
                    jobs_conn.close()
                st.rerun()
