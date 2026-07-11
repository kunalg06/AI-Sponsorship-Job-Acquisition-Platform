import pytest

from register.db import (
    OVERRIDE_ACTIVE,
    OVERRIDE_INACTIVE,
    connect,
    lookup_override,
    list_overrides,
    upsert_override,
)


def test_lookup_override_returns_none_when_absent(tmp_path):
    conn = connect(tmp_path / "sponsors.db")
    try:
        assert lookup_override(conn, "ACME AI") is None
    finally:
        conn.close()


def test_upsert_override_creates_new_entry(tmp_path):
    conn = connect(tmp_path / "sponsors.db")
    try:
        upsert_override(
            conn,
            organisation_name="Acme AI Ltd",
            match_key="ACME AI",
            status=OVERRIDE_ACTIVE,
            town_city="London",
            county="",
            rating="Worker (A rating)",
            route="Skilled Worker",
            notes="Confirmed via recruiter call",
        )

        row = lookup_override(conn, "ACME AI")
        assert row["organisation_name"] == "Acme AI Ltd"
        assert row["status"] == OVERRIDE_ACTIVE
        assert row["notes"] == "Confirmed via recruiter call"
    finally:
        conn.close()


def test_upsert_override_updates_existing_entry_in_place(tmp_path):
    conn = connect(tmp_path / "sponsors.db")
    try:
        upsert_override(conn, organisation_name="Acme AI Ltd", match_key="ACME AI", status=OVERRIDE_ACTIVE)
        upsert_override(
            conn,
            organisation_name="Acme AI Ltd",
            match_key="ACME AI",
            status=OVERRIDE_INACTIVE,
            notes="Haven't sponsored anyone in 2 years per Glassdoor",
        )

        rows = list_overrides(conn)
        assert len(rows) == 1  # updated, not duplicated
        assert rows[0]["status"] == OVERRIDE_INACTIVE
        assert "Glassdoor" in rows[0]["notes"]
    finally:
        conn.close()


def test_upsert_override_rejects_unknown_status(tmp_path):
    conn = connect(tmp_path / "sponsors.db")
    try:
        with pytest.raises(ValueError):
            upsert_override(conn, organisation_name="Acme AI Ltd", match_key="ACME AI", status="definitely_sponsoring")
    finally:
        conn.close()


def test_list_overrides_orders_by_name(tmp_path):
    conn = connect(tmp_path / "sponsors.db")
    try:
        upsert_override(conn, organisation_name="Zeta Ltd", match_key="ZETA", status=OVERRIDE_ACTIVE)
        upsert_override(conn, organisation_name="Acme Ltd", match_key="ACME", status=OVERRIDE_ACTIVE)

        rows = list_overrides(conn)
        assert [r["organisation_name"] for r in rows] == ["Acme Ltd", "Zeta Ltd"]
    finally:
        conn.close()
