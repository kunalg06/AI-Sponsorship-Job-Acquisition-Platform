from jobs.sponsor_check import (
    CANNOT_VERIFY,
    CONFIRMED,
    FUZZY_MATCH,
    NOT_FOUND,
    USER_CONFIRMED,
    USER_FLAGGED,
    check_sponsor_status,
)
from register.db import (
    OVERRIDE_ACTIVE,
    OVERRIDE_LAPSED,
    SponsorRecord,
    connect as connect_register,
    replace_all,
    upsert_override,
)
from register.normalize import make_match_key


def _register_with(tmp_path, records):
    conn = connect_register(tmp_path / "sponsors.db")
    replace_all(conn, records)
    return conn


def test_confirmed_when_employer_matches_register(tmp_path):
    record = SponsorRecord(
        organisation_name="Acme AI Limited",
        trading_name=None,
        match_key=make_match_key("Acme AI Limited"),
        town_city="London",
        county="",
        rating="Worker (A rating)",
        route="Skilled Worker",
        source_updated="2026-07-03",
    )
    conn = _register_with(tmp_path, [record])
    try:
        verdict = check_sponsor_status(conn, "Acme AI Ltd")  # different suffix/case on purpose
        assert verdict.status == CONFIRMED
        assert verdict.matched_name == "Acme AI Limited"
        assert verdict.route == "Skilled Worker"
        assert verdict.town_city == "London"
        # A confirmed licence is a floor, not a guarantee the employer will
        # actually sponsor this candidate for this role - must say so.
        assert "does not mean" in verdict.reason
    finally:
        conn.close()


def test_not_found_when_no_register_match(tmp_path):
    conn = _register_with(tmp_path, [])
    try:
        verdict = check_sponsor_status(conn, "Totally Made Up Company Ltd")
        assert verdict.status == NOT_FOUND
        assert "Totally Made Up Company Ltd" in verdict.reason
    finally:
        conn.close()


def test_cannot_verify_when_employer_name_missing_or_blank(tmp_path):
    conn = _register_with(tmp_path, [])
    try:
        assert check_sponsor_status(conn, None).status == CANNOT_VERIFY
        assert check_sponsor_status(conn, "   ").status == CANNOT_VERIFY
    finally:
        conn.close()


def test_fuzzy_match_when_posting_names_brand_but_register_has_full_legal_entity(tmp_path):
    # Real case found live: job posting says "Bending Spoons", register lists
    # "Bending Spoons Operations S.P.A.(UK Branch)" - an exact match_key
    # lookup finds nothing, but the brand name is a substring of the real entry.
    record = SponsorRecord(
        organisation_name="Bending Spoons Operations S.P.A.(UK Branch)",
        trading_name=None,
        match_key=make_match_key("Bending Spoons Operations S.P.A.(UK Branch)"),
        town_city="London",
        county="",
        rating="Worker (A rating)",
        route="Skilled Worker",
        source_updated="2026-07-03",
    )
    conn = _register_with(tmp_path, [record])
    try:
        verdict = check_sponsor_status(conn, "Bending Spoons")
        assert verdict.status == FUZZY_MATCH
        assert verdict.matched_name == "Bending Spoons Operations S.P.A.(UK Branch)"
        assert verdict.town_city == "London"
        assert len(verdict.candidates) == 1
        assert verdict.candidates[0].town_city == "London"
        assert "Bending Spoons Operations" not in verdict.reason  # names live in `candidates` now, not the prose
    finally:
        conn.close()


def test_fuzzy_match_surfaces_multiple_candidates_with_distinct_locations(tmp_path):
    # Two unrelated companies could both contain the same brand-ish substring -
    # the caller needs every candidate's location to pick the right one, not
    # just whichever the query happened to return first.
    records = [
        SponsorRecord(
            organisation_name="Acme Global Holdings Ltd",
            trading_name=None,
            match_key=make_match_key("Acme Global Holdings Ltd"),
            town_city="Manchester",
            county="",
            rating="Worker (A rating)",
            route="Skilled Worker",
            source_updated="2026-07-03",
        ),
        SponsorRecord(
            organisation_name="Acme Consulting Group Ltd",
            trading_name=None,
            match_key=make_match_key("Acme Consulting Group Ltd"),
            town_city="London",
            county="",
            rating="Worker (A rating)",
            route="Skilled Worker",
            source_updated="2026-07-03",
        ),
    ]
    conn = _register_with(tmp_path, records)
    try:
        verdict = check_sponsor_status(conn, "Acme")
        assert verdict.status == FUZZY_MATCH
        assert len(verdict.candidates) == 2
        locations = {c.town_city for c in verdict.candidates}
        assert locations == {"Manchester", "London"}
    finally:
        conn.close()


def test_not_found_stays_not_found_when_no_fuzzy_match_either(tmp_path):
    record = SponsorRecord(
        organisation_name="Completely Unrelated Ltd",
        trading_name=None,
        match_key=make_match_key("Completely Unrelated Ltd"),
        town_city="London",
        county="",
        rating="Worker (A rating)",
        route="Skilled Worker",
        source_updated="2026-07-03",
    )
    conn = _register_with(tmp_path, [record])
    try:
        verdict = check_sponsor_status(conn, "Totally Different Company")
        assert verdict.status == NOT_FOUND
    finally:
        conn.close()


def test_prefers_skilled_worker_route_when_company_has_multiple_routes(tmp_path):
    match_key = make_match_key("Acme AI Limited")
    records = [
        SponsorRecord(
            organisation_name="Acme AI Limited",
            trading_name=None,
            match_key=match_key,
            town_city="London",
            county="",
            rating="Worker (A rating)",
            route="Global Business Mobility: Senior or Specialist Worker",
            source_updated="2026-07-03",
        ),
        SponsorRecord(
            organisation_name="Acme AI Limited",
            trading_name=None,
            match_key=match_key,
            town_city="London",
            county="",
            rating="Worker (A rating)",
            route="Skilled Worker",
            source_updated="2026-07-03",
        ),
    ]
    conn = _register_with(tmp_path, records)
    try:
        verdict = check_sponsor_status(conn, "Acme AI Ltd")
        assert verdict.status == CONFIRMED
        assert verdict.route == "Skilled Worker"
    finally:
        conn.close()


def test_active_override_wins_over_register_and_returns_user_confirmed(tmp_path):
    conn = _register_with(tmp_path, [])
    try:
        upsert_override(
            conn,
            organisation_name="Acme AI Ltd",
            match_key=make_match_key("Acme AI Ltd"),
            status=OVERRIDE_ACTIVE,
            town_city="London",
            notes="Confirmed via recruiter call",
        )
        verdict = check_sponsor_status(conn, "Acme AI Ltd")
        assert verdict.status == USER_CONFIRMED
        assert verdict.override_status == OVERRIDE_ACTIVE
        assert "Confirmed via recruiter call" in verdict.reason
    finally:
        conn.close()


def test_lapsed_override_wins_over_an_otherwise_confirmed_register_match(tmp_path):
    # Even though the official register still lists them, the user's own
    # up-to-date knowledge (license lapsed) must take precedence.
    record = SponsorRecord(
        organisation_name="Acme AI Limited",
        trading_name=None,
        match_key=make_match_key("Acme AI Limited"),
        town_city="London",
        county="",
        rating="Worker (A rating)",
        route="Skilled Worker",
        source_updated="2026-07-03",
    )
    conn = _register_with(tmp_path, [record])
    try:
        upsert_override(
            conn,
            organisation_name="Acme AI Limited",
            match_key=make_match_key("Acme AI Limited"),
            status=OVERRIDE_LAPSED,
            notes="Checked Companies House - licence expired last quarter",
        )
        verdict = check_sponsor_status(conn, "Acme AI Ltd")
        assert verdict.status == USER_FLAGGED
        assert verdict.override_status == OVERRIDE_LAPSED
        assert "lapsed" in verdict.reason.lower()
    finally:
        conn.close()
