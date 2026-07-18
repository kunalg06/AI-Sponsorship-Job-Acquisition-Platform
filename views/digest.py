"""Streamlit page: the daily coach digest - "what should I do today," per
docs/v1-scope.md's V2 fast-follow scope. Deterministic (no LLM call): every
line renders straight from `jobs.digest.build_digest`'s query results, the
same object the `jobs digest` CLI command renders as plain text - the two
surfaces can't drift since they share one source of truth.
"""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from jobs.db import connect as connect_jobs
from jobs.digest import build_digest
from views.theme import mono, set_page_wonk

JOBS_DB = "data/jobs.db"

set_page_wonk("high")  # the "coach" page - read like a note left on your desk
st.title("\U0001f9ed Daily Coach Digest")
st.markdown(mono(datetime.now(timezone.utc).strftime("%A · %d %b %Y")), unsafe_allow_html=True)
st.divider()

jobs_conn = connect_jobs(JOBS_DB)
try:
    digest = build_digest(jobs_conn)
finally:
    jobs_conn.close()

st.subheader("Due for follow-up")
if not digest.due_reminders:
    st.caption("Nothing due right now.")
else:
    for r in digest.due_reminders:
        st.markdown(
            f"**#{r.job_id} {r.job_title}** @ {r.company_name or '-'} "
            f"— day {r.days} (day-{r.milestone} follow-up due)"
        )

st.divider()
st.subheader("Match queue (scored, not yet decided)")
if not digest.match_queue:
    st.caption("Nothing waiting on a decision.")
else:
    for m in digest.match_queue:
        st.markdown(f"**#{m.job_id} {m.job_title}** @ {m.company_name or '-'} — {m.match_score}/100 {m.match_verdict}")

st.divider()
st.subheader("Recurring portfolio gaps")
if not digest.gap_themes:
    st.caption("No repeated gaps yet.")
else:
    for g in digest.gap_themes:
        st.markdown(f"- ({g.count}x) {g.gap}")

st.divider()
st.subheader("Momentum")
count = digest.momentum.applications_last_7_days
applications_line = "No applications" if count == 0 else f"{count} application{'s' if count != 1 else ''}"
st.markdown(f"> *{applications_line} this week.*")
st.caption(f"Last outreach drafted: {digest.momentum.last_outreach_drafted_at or 'none yet'}")
st.caption(f"Last tailored: {digest.momentum.last_tailored_at or 'none yet'}")
