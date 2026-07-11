"""Streamlit page: goal/roadmap planner - milestone tracking, and grounded
evaluation of new goals against real job posting data.

Mirrors `python -m roadmap.cli` (init/status/start/done/evaluate).
"""

from __future__ import annotations

import streamlit as st

from jobs.db import connect as connect_jobs
from roadmap.db import (
    connect as connect_roadmap,
)
from roadmap.db import (
    create_goal,
    get_goal,
    insert_milestone,
    list_milestones,
    update_milestone_status,
)
from roadmap.planner import (
    DEFAULT_GOAL_DESCRIPTION,
    DEFAULT_MILESTONES,
    DEFAULT_TARGET_DATE,
    RISKY,
    SKIP,
    WORTH_IT,
    days_until,
    evaluate_new_goal,
)

ROADMAP_DB = "data/roadmap.db"
JOBS_DB = "data/jobs.db"

STATUS_MARKER = {"done": "✅", "in_progress": "\U0001f7e1"}
VERDICT_COLOR = {WORTH_IT: "green", RISKY: "orange", SKIP: "red"}

st.title("\U0001f5fa Goal & Roadmap")

conn = connect_roadmap(ROADMAP_DB)
try:
    goal = get_goal(conn)
    milestones = list_milestones(conn) if goal else []
finally:
    conn.close()

if goal is None:
    st.info("No goal set yet.")
    with st.form("init_goal_form"):
        description = st.text_input("Goal", value=DEFAULT_GOAL_DESCRIPTION)
        target_date = st.text_input("Target date (YYYY-MM-DD)", value=DEFAULT_TARGET_DATE)
        if st.form_submit_button("Set goal & seed milestone plan") and description.strip() and target_date.strip():
            conn = connect_roadmap(ROADMAP_DB)
            try:
                create_goal(conn, description, target_date)
                for i, (month_label, title) in enumerate(DEFAULT_MILESTONES):
                    insert_milestone(conn, month_label, title, i)
            finally:
                conn.close()
            st.rerun()
else:
    remaining = days_until(goal["target_date"])
    st.subheader(goal["description"])
    if remaining <= 0:
        st.error(f"Target date {goal['target_date']} has passed or is today.")
    else:
        st.metric("Days remaining", remaining, help=f"Target: {goal['target_date']}")

    done_count = sum(1 for m in milestones if m["status"] == "done")
    if milestones:
        st.progress(done_count / len(milestones), text=f"{done_count}/{len(milestones)} milestones done")

    st.divider()
    st.markdown("### Milestones")

    current_month = None
    for m in milestones:
        if m["month_label"] != current_month:
            current_month = m["month_label"]
            st.markdown(f"**{current_month}**")
        cols = st.columns([6, 1, 1])
        marker = STATUS_MARKER.get(m["status"], "⬜")
        cols[0].write(f"{marker} #{m['id']} {m['title']}")
        if m["status"] == "pending":
            if cols[1].button("Start", key=f"start_{m['id']}"):
                roadmap_conn = connect_roadmap(ROADMAP_DB)
                try:
                    update_milestone_status(roadmap_conn, m["id"], "in_progress")
                finally:
                    roadmap_conn.close()
                st.rerun()
        if m["status"] != "done":
            if cols[2].button("Done", key=f"done_{m['id']}"):
                roadmap_conn = connect_roadmap(ROADMAP_DB)
                try:
                    update_milestone_status(roadmap_conn, m["id"], "done")
                finally:
                    roadmap_conn.close()
                st.rerun()

    st.divider()
    st.markdown("### Evaluate a New Goal")
    st.caption(
        "Weigh a proposed detour (e.g. \"should I get a certification\") against real "
        "job posting data and your remaining runway - grounded, not encouraging by default."
    )
    with st.form("evaluate_goal_form"):
        keywords_raw = st.text_input("Keywords (comma-separated)", placeholder="e.g. AWS, certified")
        time_cost_days = st.number_input("Estimated time cost (days)", min_value=0.0, step=0.5)
        submitted = st.form_submit_button("Evaluate")

    if submitted and keywords_raw.strip():
        jobs_conn = connect_jobs(JOBS_DB)
        try:
            job_rows = [
                (row["id"], row["job_title"], row["raw_text"])
                for row in jobs_conn.execute("SELECT id, job_title, raw_text FROM jobs")
            ]
        finally:
            jobs_conn.close()

        keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        evaluation = evaluate_new_goal(job_rows, keywords, time_cost_days, goal["target_date"])

        color = VERDICT_COLOR.get(evaluation.verdict, "gray")
        st.markdown(f":{color}[**{evaluation.verdict.upper()}**]")
        st.write(evaluation.reasoning)
        if evaluation.matching_jobs:
            st.caption("Matching postings:")
            for job_id, job_title in evaluation.matching_jobs:
                st.caption(f"  #{job_id} {job_title}")
