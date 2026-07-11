"""CLI for ingesting and querying the UK sponsor register."""

from __future__ import annotations

import argparse

from register import ingest as ingest_module
from register.db import connect, lookup
from register.normalize import make_match_key

DEFAULT_SOURCE = (
    "https://assets.publishing.service.gov.uk/media/6a47768c1c8bd7ce25a5ea44/"
    "SP_-_Worker_and_Temporary_Worker_Web_Register_-_2026-07-03.csv"
)
DEFAULT_DB = "data/sponsors.db"


def _cmd_ingest(args: argparse.Namespace) -> None:
    summary = ingest_module.ingest(args.source, args.db)
    print(
        f"Loaded {summary['rows_loaded']} sponsors from {summary['source']} "
        f"(register dated {summary['source_updated'] or 'unknown'}) into {args.db}. "
        f"Rows now in db: {summary['rows_in_db']}."
    )


def _cmd_lookup(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    try:
        key = make_match_key(args.name)
        rows = lookup(conn, key)
    finally:
        conn.close()

    if not rows:
        print(f"No sponsor match for '{args.name}' (match_key={key!r}).")
        return

    for row in rows:
        # organisation_name is stored verbatim from the register, so it
        # already includes any "... t/a ..." trading name - don't repeat it.
        print(
            f"MATCH: {row['organisation_name']} "
            f"| {row['town_city']}, {row['county']} "
            f"| {row['rating']} | {row['route']}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="register", description="UK sponsor register tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Download/import and load the register")
    ingest_parser.add_argument("--source", default=DEFAULT_SOURCE, help="URL or local CSV path")
    ingest_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite db path")
    ingest_parser.set_defaults(func=_cmd_ingest)

    lookup_parser = subparsers.add_parser("lookup", help="Check whether a company is a licensed sponsor")
    lookup_parser.add_argument("name", help="Company name as it appears on a job posting")
    lookup_parser.add_argument("--db", default=DEFAULT_DB, help="SQLite db path")
    lookup_parser.set_defaults(func=_cmd_lookup)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
