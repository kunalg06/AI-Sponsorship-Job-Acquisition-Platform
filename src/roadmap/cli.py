"""CLI for the goal/roadmap planner."""

from __future__ import annotations

import argparse

from jobs.db import connect as connect_jobs
from roadmap.db import (
    clear_milestones,
    connect,
    create_goal,
    get_goal,
    get_milestone,
    insert_milestone,
    list_milestones,
    update_milestone_status,
)
from roadmap.planner import DEFAULT_GOAL_DESCRIPTION, DEFAULT_MILESTONES, DEFAULT_TARGET_DATE, days_until, evaluate_new_goal

DEFAULT_DB = "data/roadmap.db"
DEFAULT_JOBS_DB = "data/jobs.db"


def _cmd_init(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        existing = get_goal(conn)
        if existing is not None and not args.force:
            print(f"Goal already set: {existing['description']} (target {existing['target_date']}). Use --force to reset.")
            return

        if existing is not None:
            clear_milestones(conn)
        create_goal(conn, args.description, args.target_date)
        for i, (month_label, title) in enumerate(DEFAULT_MILESTONES):
            insert_milestone(conn, month_label, title, i)

        print(f"Goal set: {args.description}")
        print(f"Target date: {args.target_date} ({days_until(args.target_date)} days from today)")
        print(f"Seeded {len(DEFAULT_MILESTONES)} milestones across {args.target_date[:4]}.")
    finally:
        conn.close()


def _cmd_status(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        goal = get_goal(conn)
        if goal is None:
            print("No goal set yet - run `roadmap init` first.")
            return
        remaining = days_until(goal["target_date"])
        milestones = list_milestones(conn)
    finally:
        conn.close()

    print(f"Goal: {goal['description']}")
    print(f"Target date: {goal['target_date']} ({remaining} days remaining)")
    if remaining <= 0:
        print("  ** Deadline has passed or is today. **")
    print()

    current_month = None
    done = 0
    for m in milestones:
        if m["month_label"] != current_month:
            current_month = m["month_label"]
            print(f"{current_month}:")
        marker = {"done": "[x]", "in_progress": "[~]"}.get(m["status"], "[ ]")
        print(f"  {marker} #{m['id']} {m['title']}")
        if m["status"] == "done":
            done += 1

    print(f"\n{done}/{len(milestones)} milestones done.")


def _cmd_start(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        milestone = get_milestone(conn, args.milestone_id)
        if milestone is None:
            raise SystemExit(f"No milestone #{args.milestone_id} found.")
        update_milestone_status(conn, args.milestone_id, "in_progress")
        print(f"Milestone #{args.milestone_id} marked in progress: {milestone['title']}")
    finally:
        conn.close()


def _cmd_done(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        milestone = get_milestone(conn, args.milestone_id)
        if milestone is None:
            raise SystemExit(f"No milestone #{args.milestone_id} found.")
        update_milestone_status(conn, args.milestone_id, "done")
        print(f"Milestone #{args.milestone_id} marked done: {milestone['title']}")
    finally:
        conn.close()


def _cmd_evaluate(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        goal = get_goal(conn)
        if goal is None:
            raise SystemExit("No goal set yet - run `roadmap init` first.")
        target_date = goal["target_date"]
    finally:
        conn.close()

    jobs_conn = connect_jobs(args.jobs_db)
    try:
        job_rows = [
            (row["id"], row["job_title"], row["raw_text"])
            for row in jobs_conn.execute("SELECT id, job_title, raw_text FROM jobs")
        ]
    finally:
        jobs_conn.close()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    evaluation = evaluate_new_goal(job_rows, keywords, args.time_cost_days, target_date)

    print(f"Evaluating: {', '.join(keywords)} ({args.time_cost_days:g} days estimated cost)")
    print(f"Checked against {evaluation.jobs_checked} stored job postings.")
    print(f"Matches ({len(evaluation.matching_jobs)}):")
    for job_id, job_title in evaluation.matching_jobs:
        print(f"  - #{job_id} {job_title}")
    print(f"Days remaining to deadline: {evaluation.days_remaining}")
    print(f"Verdict: {evaluation.verdict.upper()}")
    print(f"Reasoning: {evaluation.reasoning}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="roadmap", description="Goal/roadmap planner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Set the goal + deadline and seed the default milestone plan")
    init_parser.add_argument("--target-date", default=DEFAULT_TARGET_DATE, help="ISO date - the real effective deadline")
    init_parser.add_argument("--description", default=DEFAULT_GOAL_DESCRIPTION)
    init_parser.add_argument("--db", default=DEFAULT_DB)
    init_parser.add_argument("--force", action="store_true", help="Reset the goal and milestones even if one exists")
    init_parser.set_defaults(func=_cmd_init)

    status_parser = subparsers.add_parser("status", help="Show days remaining and milestone progress")
    status_parser.add_argument("--db", default=DEFAULT_DB)
    status_parser.set_defaults(func=_cmd_status)

    start_parser = subparsers.add_parser("start", help="Mark a milestone in progress")
    start_parser.add_argument("milestone_id", type=int)
    start_parser.add_argument("--db", default=DEFAULT_DB)
    start_parser.set_defaults(func=_cmd_start)

    done_parser = subparsers.add_parser("done", help="Mark a milestone done")
    done_parser.add_argument("milestone_id", type=int)
    done_parser.add_argument("--db", default=DEFAULT_DB)
    done_parser.set_defaults(func=_cmd_done)

    evaluate_parser = subparsers.add_parser(
        "evaluate", help="Weigh a proposed new goal (e.g. a certification) against real job posting data"
    )
    evaluate_parser.add_argument("--keywords", required=True, help="Comma-separated terms, e.g. 'AWS,certified'")
    evaluate_parser.add_argument("--time-cost-days", type=float, required=True)
    evaluate_parser.add_argument("--db", default=DEFAULT_DB)
    evaluate_parser.add_argument("--jobs-db", default=DEFAULT_JOBS_DB)
    evaluate_parser.set_defaults(func=_cmd_evaluate)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
