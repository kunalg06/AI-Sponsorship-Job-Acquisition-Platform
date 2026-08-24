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

import json

import streamlit as st

from jobs.db import connect as connect_jobs
from jobs.db import list_discovery_queue, mark_discarded, mark_discovery_reviewed
from jobs.match_score import DISCOVERY_TRIAGE_THRESHOLD, partition_discovery_queue
from jobs.sponsor_check import CANNOT_VERIFY, CONFIRMED, FUZZY_MATCH, NOT_FOUND, SKIPPED, USER_CONFIRMED, USER_FLAGGED
from views.theme import set_page_wonk

JOBS_DB = "data/jobs.db"

# How many queue rows this page renders. The triage control below deliberately
# does NOT use this number - see the whole-queue comment in the triage block.
DISPLAY_LIMIT = 20

# Session-state keys holding a previewed triage. The commit button acts on the
# ids stored here rather than re-partitioning, so it can only ever discard the
# exact set the user was shown - a threshold change (or a discovery run landing
# between the two clicks) can't silently widen the blast radius.
_TRIAGE_PREVIEW = "automate_triage_preview"
_TRIAGE_THRESHOLD = "automate_triage_threshold"

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


def _skill_list(raw) -> list[str]:
    """`match_matched_skills`/`match_missing_skills` are stored as JSON text
    (`update_match_verdict` json.dumps them), so they need decoding before
    display. Returns [] for NULL, empty text, or malformed JSON rather than
    raising: a review queue must still render every other field of a row even
    if this one column is unreadable, and an unparseable skills list is
    exactly the kind of thing that should degrade quietly to "no detail
    shown" instead of taking the whole page down."""
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(s) for s in decoded] if isinstance(decoded, list) else []

set_page_wonk("low")  # a review queue is a working table, same register as Jobs List
st.title("\U0001f916 Automate")
st.caption(
    "Indeed postings found by the daily discovery search, already sponsor-checked, "
    "salary-checked, and match-scored - sorted by match score, then newest posted first. "
    "Nothing is hidden or hard-filtered here: review each candidate yourself and decide."
)

conn = connect_jobs(JOBS_DB)
try:
    # The WHOLE queue, not DISPLAY_LIMIT rows: the triage control partitions
    # every unreviewed row, and the header below reports the real depth so a
    # capped list can never read as "that's all of them".
    full_queue = list_discovery_queue(conn, limit=None)
finally:
    conn.close()

queue = full_queue[:DISPLAY_LIMIT]

if full_queue:
    with st.expander(f"Bulk triage ({len(full_queue)} unreviewed)", expanded=False):
        st.caption(
            "Discards everything scoring below the threshold so the queue is worth reading again. "
            "Acts on all "
            f"{len(full_queue)} unreviewed candidates, not just the {min(len(full_queue), DISPLAY_LIMIT)} listed below. "
            "Discarding is reversible - rows stay readable under Jobs List's Discarded filter."
        )
        threshold = st.slider(
            "Keep candidates scoring at or above",
            min_value=50,
            max_value=95,
            value=st.session_state.get(_TRIAGE_THRESHOLD, DISCOVERY_TRIAGE_THRESHOLD),
            step=5,
            help=(
                "Neither this default nor the 70 used for STRONG MATCH has been validated against "
                "real interview outcomes - preview before committing."
            ),
        )
        keep, discard, unscored = partition_discovery_queue(full_queue, threshold)

        if st.button("Preview triage", key="triage_preview"):
            st.session_state[_TRIAGE_THRESHOLD] = threshold
            st.session_state[_TRIAGE_PREVIEW] = [row["id"] for row in discard]
            st.rerun()

        preview_ids = st.session_state.get(_TRIAGE_PREVIEW)
        if preview_ids is not None:
            shown_threshold = st.session_state.get(_TRIAGE_THRESHOLD, threshold)
            st.markdown(
                f"**Keep {len(keep)}** &nbsp;·&nbsp; **Discard {len(preview_ids)}** &nbsp;·&nbsp; "
                f"**Leave {len(unscored)} unscored** — at threshold {shown_threshold}/100"
            )
            if unscored:
                st.caption(
                    f"{len(unscored)} row(s) were never scored (no resume on file when they were staged). "
                    "An unscored row is unjudged, not rejected - it stays in the queue either way."
                )
            if preview_ids:
                with st.container(border=True):
                    for row in discard[:10]:
                        st.caption(f"#{row['id']} · {row['match_score']}/100 · {row['job_title']} @ {row['company_name'] or '-'}")
                    if len(discard) > 10:
                        st.caption(f"...and {len(discard) - 10} more")
                cols = st.columns(2)
                if cols[0].button(f"Discard {len(preview_ids)} now", key="triage_apply", type="primary"):
                    apply_conn = connect_jobs(JOBS_DB)
                    try:
                        for job_id in preview_ids:
                            mark_discarded(apply_conn, job_id)
                    finally:
                        apply_conn.close()
                    st.session_state.pop(_TRIAGE_PREVIEW, None)
                    st.rerun()
                if cols[1].button("Cancel", key="triage_cancel"):
                    st.session_state.pop(_TRIAGE_PREVIEW, None)
                    st.rerun()
            else:
                st.caption("Nothing scores below this threshold - nothing to discard.")

if not queue:
    st.info(
        "Nothing waiting for review right now - either the discovery agent hasn't run "
        "yet, or every staged candidate so far has been reviewed."
    )
else:
    st.caption(
        f"Showing {len(queue)} of {len(full_queue)} unreviewed candidates, highest match first."
        + (
            f" The other {len(full_queue) - len(queue)} are still queued - use Bulk triage above to thin them out."
            if len(full_queue) > len(queue)
            else ""
        )
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
                # The score alone is not an auditable verdict, and this is the
                # page the user triages from - so the evidence behind it is
                # shown here rather than only on Jobs List. A run that staged
                # truncated descriptions produced a queue of confident-looking
                # 0/100s whose reasoning and skills lists were empty; had they
                # been rendered, the bug would have been obvious on sight
                # instead of needing a raw_text length query to find. Also note
                # the scorer never distinguishes required from nice-to-have
                # (see match_score.py's system instruction), so a low score
                # needs its missing_skills visible before it's acted on.
                missing = _skill_list(job["match_missing_skills"])
                matched = _skill_list(job["match_matched_skills"])
                if matched:
                    st.markdown(f"**Has:** {', '.join(matched)}")
                if missing:
                    st.markdown(f"**Missing:** {', '.join(missing)}")
                if job["match_reasoning"]:
                    st.caption(job["match_reasoning"])
                if not matched and not missing and not job["match_reasoning"]:
                    st.caption(
                        ":orange[No scoring detail was recorded for this row - treat the score "
                        "above as unverified and check the posting yourself before acting on it.]"
                    )
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
