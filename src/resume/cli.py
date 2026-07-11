"""CLI for adding and viewing the candidate resume/profile."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from resume.db import connect, get_latest_narrative, get_latest_profile, insert_narrative, insert_profile
from resume.extract import extract_profile

load_dotenv()

DEFAULT_DB = "data/profile.db"


def _read_input(args: argparse.Namespace) -> str:
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    text = sys.stdin.read()
    if not text.strip():
        raise SystemExit("No resume text provided - pass --file or pipe text via stdin.")
    return text


def _print_profile(profile) -> None:
    print(f"  Name:             {profile.full_name or '(not stated)'}")
    print(f"  Seniority:        {profile.seniority}")
    print(f"  Years experience: {profile.years_experience if profile.years_experience is not None else '(not stated)'}")
    print(f"  Core skills:      {', '.join(profile.core_skills) or '(none extracted)'}")
    print(f"  Domains:          {', '.join(profile.domains) or '(none extracted)'}")
    print(f"  Past roles:       {', '.join(profile.past_roles) or '(none extracted)'}")
    print(f"  Summary:          {profile.summary}")


def _cmd_add(args: argparse.Namespace) -> None:
    raw_text = _read_input(args)
    profile = extract_profile(raw_text)

    conn = connect(args.db)
    try:
        profile_id = insert_profile(conn, raw_text, profile)
    finally:
        conn.close()

    print(f"Stored profile #{profile_id}")
    _print_profile(profile)


def _cmd_show(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        profile = get_latest_profile(conn)
    finally:
        conn.close()

    if profile is None:
        print(f"No profile stored yet in {args.db} - run `resume add` first.")
        return
    _print_profile(profile)


def _cmd_narrative_add(args: argparse.Namespace) -> None:
    text = _read_input(args)
    conn = connect(args.db)
    try:
        narrative_id = insert_narrative(conn, text)
    finally:
        conn.close()
    print(f"Stored narrative core #{narrative_id}")


def _cmd_narrative_show(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        text = get_latest_narrative(conn)
    finally:
        conn.close()

    if text is None:
        print(f"No narrative core stored yet in {args.db} - run `resume narrative add` first.")
        return
    print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="resume", description="Candidate resume/profile management")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Paste a resume in and extract a structured profile")
    add_parser.add_argument("--file", help="Path to a text file containing the resume (else reads stdin)")
    add_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite db path")
    add_parser.set_defaults(func=_cmd_add)

    show_parser = subparsers.add_parser("show", help="Show the latest stored profile")
    show_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite db path")
    show_parser.set_defaults(func=_cmd_show)

    narrative_add_parser = subparsers.add_parser(
        "narrative-add", help="Paste your narrative core (why AI, why UK, why you) - reused across all outreach"
    )
    narrative_add_parser.add_argument("--file", help="Path to a text file (else reads stdin)")
    narrative_add_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite db path")
    narrative_add_parser.set_defaults(func=_cmd_narrative_add)

    narrative_show_parser = subparsers.add_parser("narrative-show", help="Show the latest stored narrative core")
    narrative_show_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite db path")
    narrative_show_parser.set_defaults(func=_cmd_narrative_show)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
