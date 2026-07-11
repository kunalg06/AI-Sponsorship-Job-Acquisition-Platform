"""Sponsor status check: resolve a job's employer against the cleaned sponsor register.

Three cases, handled explicitly - never guess:
  (a) Direct employer named clearly -> normalize + look up -> a real verdict.
  (b) Agency-only posting, client redacted -> CANNOT_VERIFY, not a guess.
  (c) User later found the real employer (e.g. via LinkedIn) -> treated as (a)
      once the name is set on the job record (see jobs.db.update_employer_name).

A fourth, human-only case: when neither an exact nor a fuzzy register match
resolves confidently, you can verify sponsorship yourself (comparing the
register's town/city against the job's stated location, a browser extension,
etc.) and assert the result directly - see USER_CONFIRMED and
jobs.cli's `confirm-sponsor` command. The system never guesses on your
behalf; it just makes room for you to record what you found.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from register.db import OVERRIDE_ACTIVE
from register.db import lookup as register_lookup
from register.db import lookup_contains as register_lookup_contains
from register.db import lookup_override as register_lookup_override
from register.normalize import make_match_key

CONFIRMED = "confirmed"
FUZZY_MATCH = "fuzzy_match"
NOT_FOUND = "not_found"
CANNOT_VERIFY = "cannot_verify"
USER_CONFIRMED = "user_confirmed"
USER_FLAGGED = "user_flagged"

MAX_FUZZY_CANDIDATES = 10

_OVERRIDE_LABELS = {
    "inactive": "not currently sponsoring anyone, per your own notes",
    "lapsed": "license lapsed / not renewed, per your own notes",
    "unconfirmed": "manually added by you without confirming yet - treat as unverified",
}

# A licence on the register means sponsorship is legally possible, not that
# this employer will actually use it for you - companies routinely hold a
# valid licence and still decline to sponsor a given hire (cost, seniority
# bar, internal policy). Confirmed is a floor, not a guarantee.
LICENCE_CAVEAT = (
    "This confirms the employer holds a valid sponsor licence - it does not mean "
    "they will sponsor you for this specific role. Licensed companies routinely "
    "decline to sponsor a given hire."
)


@dataclass(frozen=True)
class SponsorCandidate:
    name: str
    town_city: str
    county: str
    rating: str
    route: str


@dataclass(frozen=True)
class SponsorVerdict:
    status: str  # CONFIRMED / FUZZY_MATCH / NOT_FOUND / CANNOT_VERIFY / USER_CONFIRMED
    reason: Optional[str] = None
    matched_name: Optional[str] = None
    rating: Optional[str] = None
    route: Optional[str] = None
    town_city: Optional[str] = None
    county: Optional[str] = None
    # Populated for FUZZY_MATCH when there's more than one plausible register
    # entry - compare each candidate's location against the job posting's
    # stated location yourself before picking one (or none).
    candidates: tuple[SponsorCandidate, ...] = ()
    # Populated when the verdict came from a user-maintained company override
    # (see register.db.sponsor_overrides) - the raw status category
    # (active/inactive/lapsed/unconfirmed), for the UI to badge distinctly.
    override_status: Optional[str] = None


def _dedupe_candidates(rows) -> list[SponsorCandidate]:
    by_name: dict[str, SponsorCandidate] = {}
    for row in rows:
        name = row["organisation_name"]
        if name in by_name and by_name[name].route == "Skilled Worker":
            continue  # already have this company's Skilled Worker row - keep it
        by_name[name] = SponsorCandidate(
            name=name,
            town_city=row["town_city"] or "",
            county=row["county"] or "",
            rating=row["rating"],
            route=row["route"],
        )
    return list(by_name.values())[:MAX_FUZZY_CANDIDATES]


def check_sponsor_status(register_conn: sqlite3.Connection, employer_name: Optional[str]) -> SponsorVerdict:
    """Look up whether `employer_name` is a licensed UK sponsor.

    `employer_name` should be the value the job's `employer_name_for_sponsor_check`
    field resolved to - None means the real employer isn't known yet (case b).
    """
    if not employer_name or not employer_name.strip():
        return SponsorVerdict(
            status=CANNOT_VERIFY,
            reason=(
                "No employer name identified for this posting - likely an agency "
                "listing with the real client redacted, or the employer wasn't "
                "stated. Cannot check sponsor status until the real employer is "
                "known (find it yourself, then set it on this job)."
            ),
        )

    match_key = make_match_key(employer_name)

    # Your own notes about this company (if any) take precedence over the
    # register snapshot - the register only refreshes periodically and never
    # tells you if a licensed company simply stopped sponsoring people.
    override = register_lookup_override(register_conn, match_key)
    if override:
        note_suffix = f" - {override['notes']}" if override["notes"] else ""
        if override["status"] == OVERRIDE_ACTIVE:
            return SponsorVerdict(
                status=USER_CONFIRMED,
                reason=f"Manually confirmed as an active sponsor by you{note_suffix}.",
                matched_name=override["organisation_name"],
                rating=override["rating"],
                route=override["route"],
                town_city=override["town_city"] or "",
                county=override["county"] or "",
                override_status=override["status"],
            )
        label = _OVERRIDE_LABELS.get(override["status"], override["status"])
        return SponsorVerdict(
            status=USER_FLAGGED,
            reason=f"You flagged this company as {label}{note_suffix} (last updated {override['updated_at'][:10]}).",
            matched_name=override["organisation_name"],
            rating=override["rating"],
            route=override["route"],
            town_city=override["town_city"] or "",
            county=override["county"] or "",
            override_status=override["status"],
        )

    rows = register_lookup(register_conn, match_key)
    if rows:
        # Prefer a Skilled Worker route match if the company has more than one
        # register entry (e.g. also licensed for Global Business Mobility etc).
        row = next((r for r in rows if r["route"] == "Skilled Worker"), rows[0])
        return SponsorVerdict(
            status=CONFIRMED,
            reason=LICENCE_CAVEAT,
            matched_name=row["organisation_name"],
            rating=row["rating"],
            route=row["route"],
            town_city=row["town_city"] or "",
            county=row["county"] or "",
        )

    # No exact match - a job posting often names the brand/parent while the
    # register lists the full legal entity (e.g. "Bending Spoons" vs.
    # "Bending Spoons Operations S.p.A. (UK Branch)"). Try a substring
    # fallback rather than asserting NOT_FOUND on a name-formatting mismatch.
    fuzzy_rows = register_lookup_contains(register_conn, match_key)
    if fuzzy_rows:
        candidates = _dedupe_candidates(fuzzy_rows)
        best = candidates[0]
        return SponsorVerdict(
            status=FUZZY_MATCH,
            reason=(
                f"No exact match for '{employer_name}' - {len(candidates)} similar register "
                f"entr{'y' if len(candidates) == 1 else 'ies'} found. Compare each candidate's "
                f"location against the job posting's stated location before treating any as "
                f"verified. {LICENCE_CAVEAT}"
            ),
            matched_name=best.name,
            rating=best.rating,
            route=best.route,
            town_city=best.town_city,
            county=best.county,
            candidates=tuple(candidates),
        )

    return SponsorVerdict(
        status=NOT_FOUND,
        reason=f"'{employer_name}' was not found on the UK sponsor register.",
    )
