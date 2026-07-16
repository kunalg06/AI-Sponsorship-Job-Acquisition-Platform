import sqlite3
import threading
import time

import pytest

from register import ingest as ingest_module
from register.db import (
    BUSY_TIMEOUT_MS,
    SponsorRecord,
    connect,
    count,
    get_current_source_updated,
    is_noop_refresh,
    lookup,
    lookup_contains,
    replace_all,
)
from register.normalize import make_match_key

SAMPLE_CSV = (
    "Organisation Name,Town/City,County,Type & Rating,Route\n"
    " BOLTWHIZ LIMITED,Dunfermline,Scotland,Worker (A rating),Skilled Worker\n"
    " HAH Hospitality Limited t/a Indian Affair Ancoats,Manchester,,Worker (A rating),Skilled Worker\n"
    " COST CUTTER RUGBY LIMITED    ,RUGBY,WARWICKSHIRE ,Worker (A rating),Skilled Worker\n"
    " F-Secure (UK) Limited,Gerrards Cross,Buckinghamshire,Worker (A rating),Skilled Worker\n"
)


def test_guess_source_updated_from_filename():
    source = (
        "https://assets.publishing.service.gov.uk/media/x/"
        "SP_-_Worker_and_Temporary_Worker_Web_Register_-_2026-07-03.csv"
    )
    assert ingest_module.guess_source_updated(source) == "2026-07-03"


def test_guess_source_updated_returns_none_when_absent():
    assert ingest_module.guess_source_updated("https://example.com/register.csv") is None


def test_parse_rows_trims_every_field():
    rows = ingest_module.parse_rows(SAMPLE_CSV)
    assert rows[2]["Organisation Name"] == "COST CUTTER RUGBY LIMITED"
    assert rows[2]["County"] == "WARWICKSHIRE"


def test_parse_rows_rejects_missing_columns():
    with pytest.raises(ValueError, match="missing expected columns"):
        ingest_module.parse_rows("Organisation Name,Route\nFoo,Skilled Worker\n")


def test_build_records_normalizes_names():
    rows = ingest_module.parse_rows(SAMPLE_CSV)
    records = ingest_module.build_records(rows, source_updated="2026-07-03")
    by_match_key = {r.match_key: r for r in records}

    assert "HAH HOSPITALITY" in by_match_key
    assert by_match_key["HAH HOSPITALITY"].trading_name == "Indian Affair Ancoats"
    assert "COST CUTTER RUGBY" in by_match_key
    assert by_match_key["F-SECURE UK"].town_city == "Gerrards Cross"
    assert all(r.source_updated == "2026-07-03" for r in records)


def test_full_ingest_pipeline_from_local_csv_then_lookup(tmp_path):
    csv_path = tmp_path / "register.csv"
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    db_path = tmp_path / "sponsors.db"

    summary = ingest_module.ingest(str(csv_path), str(db_path))

    assert summary["rows_loaded"] == 4
    assert summary["rows_in_db"] == 4

    conn = connect(db_path)
    try:
        # A job posting might spell the company differently in case/whitespace
        # and without the legal suffix - the lookup still has to find it.
        rows = lookup(conn, make_match_key("Cost Cutter Rugby"))
        assert len(rows) == 1
        assert rows[0]["organisation_name"] == "COST CUTTER RUGBY LIMITED"

        rows = lookup(conn, make_match_key("Some Company Nobody Sponsors"))
        assert rows == []
    finally:
        conn.close()


def test_lookup_contains_finds_brand_name_inside_full_legal_entity(tmp_path):
    csv_path = tmp_path / "register.csv"
    csv_path.write_text(
        "Organisation Name,Town/City,County,Type & Rating,Route\n"
        " Bending Spoons Operations S.P.A.(UK Branch),London,,Worker (A rating),Skilled Worker\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "sponsors.db"
    ingest_module.ingest(str(csv_path), str(db_path))

    conn = connect(db_path)
    try:
        # Exact lookup fails - the register has the full legal entity name.
        assert lookup(conn, make_match_key("Bending Spoons")) == []

        rows = lookup_contains(conn, make_match_key("Bending Spoons"))
        assert len(rows) == 1
        assert "Bending Spoons Operations" in rows[0]["organisation_name"]
    finally:
        conn.close()


def test_lookup_contains_escapes_sql_wildcard_characters(tmp_path):
    csv_path = tmp_path / "register.csv"
    csv_path.write_text(
        "Organisation Name,Town/City,County,Type & Rating,Route\n"
        " Some Normal Company Ltd,London,,Worker (A rating),Skilled Worker\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "sponsors.db"
    ingest_module.ingest(str(csv_path), str(db_path))

    conn = connect(db_path)
    try:
        # A literal "%" or "_" in the query must not act as a SQL wildcard.
        assert lookup_contains(conn, "100%_MATCH") == []
    finally:
        conn.close()


def test_reingest_replaces_rather_than_appends(tmp_path):
    csv_path = tmp_path / "register.csv"
    db_path = tmp_path / "sponsors.db"

    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    ingest_module.ingest(str(csv_path), str(db_path))

    # Simulate a refreshed register with fewer rows.
    csv_path.write_text(SAMPLE_CSV.splitlines()[0] + "\n" + SAMPLE_CSV.splitlines()[1] + "\n", encoding="utf-8")
    summary = ingest_module.ingest(str(csv_path), str(db_path))

    assert summary["rows_loaded"] == 1
    assert summary["rows_in_db"] == 1


def test_connect_sets_busy_timeout_pragma(tmp_path):
    db_path = tmp_path / "sponsors.db"
    conn = connect(db_path)
    try:
        # PRAGMA busy_timeout with no argument returns the current value (ms).
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
    finally:
        conn.close()


def test_busy_timeout_lets_a_concurrent_writer_wait_out_a_held_lock(tmp_path):
    # Exercises what busy_timeout is actually for - a duration proxy alone
    # (see test_replace_all_completes_well_within_busy_timeout below) never
    # touches real lock contention. conn1 holds the write lock; a second
    # connection's write must wait for it to release, not immediately raise
    # "database is locked".
    db_path = tmp_path / "sponsors.db"
    conn1 = connect(db_path)
    conn1.execute("BEGIN IMMEDIATE")
    conn1.execute(
        "INSERT INTO sponsors (organisation_name, match_key, route) VALUES (?, ?, ?)",
        ("Holder Ltd", "holderltd", "Skilled Worker"),
    )

    result: dict = {}

    def waiting_writer():
        # Its own connection, opened and used entirely on this thread -
        # sqlite3 connections aren't safe to share across threads.
        conn2 = connect(db_path)
        start = time.perf_counter()
        try:
            conn2.execute(
                "INSERT INTO sponsors (organisation_name, match_key, route) VALUES (?, ?, ?)",
                ("Waiter Ltd", "waiterltd", "Skilled Worker"),
            )
            conn2.commit()
            result["elapsed"] = time.perf_counter() - start
            result["error"] = None
        except sqlite3.OperationalError as exc:
            result["error"] = exc
        finally:
            conn2.close()

    waiter = threading.Thread(target=waiting_writer)
    waiter.start()

    hold_seconds = 0.5
    time.sleep(hold_seconds)
    conn1.commit()
    conn1.close()
    waiter.join(timeout=BUSY_TIMEOUT_MS / 1000)

    assert result.get("error") is None
    # Proves the writer actually waited for the lock rather than getting
    # lucky - it couldn't have completed before conn1 released it.
    assert result["elapsed"] >= hold_seconds


def test_replace_all_completes_well_within_busy_timeout(tmp_path):
    # register/db.py's busy_timeout is sized against replace_all()'s
    # real-world cost - this guards that assumption against a future
    # regression (e.g. a schema change adding an expensive trigger/index)
    # eroding the safety margin without anyone noticing. A mix of NULL
    # optional fields and varying name lengths, not uniform rows, since a
    # regression tied to data shape (not just row count) should show up too.
    records = [
        SponsorRecord(
            organisation_name=f"Company {i} International Holdings Ltd" if i % 5 == 0 else f"Company {i} Ltd",
            trading_name=f"Co{i}" if i % 3 == 0 else None,
            match_key=f"company{i}ltd",
            town_city="London" if i % 2 == 0 else None,
            county="Greater London" if i % 2 == 0 else None,
            rating="A rating",
            route="Skilled Worker",
            source_updated="2026-07-01",
        )
        for i in range(100_000)
    ]

    conn = connect(tmp_path / "sponsors.db")
    try:
        start = time.perf_counter()
        loaded = replace_all(conn, records)
        elapsed_ms = (time.perf_counter() - start) * 1000
        row_count = count(conn)
    finally:
        conn.close()

    assert loaded == 100_000
    assert row_count == 100_000  # loaded is just len(records) - this confirms it actually persisted
    # Order-of-magnitude margin, not a hair's-breadth pass: a one-off manual
    # measurement against the real 142k-row register found its worst of 3
    # trials at 635ms, well under a third of BUSY_TIMEOUT_MS.
    assert elapsed_ms < BUSY_TIMEOUT_MS / 3


def test_get_current_source_updated_returns_none_for_empty_table(tmp_path):
    db_path = tmp_path / "sponsors.db"
    conn = connect(db_path)
    try:
        assert get_current_source_updated(conn) is None
    finally:
        conn.close()


def test_get_current_source_updated_returns_value_after_ingest(tmp_path):
    csv_path = tmp_path / "register-2026-07-03.csv"
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    db_path = tmp_path / "sponsors.db"

    ingest_module.ingest(str(csv_path), str(db_path))

    conn = connect(db_path)
    try:
        assert get_current_source_updated(conn) == "2026-07-03"
    finally:
        conn.close()


def test_is_noop_refresh_true_when_dates_match():
    assert is_noop_refresh("2026-07-03", "2026-07-03") is True


def test_is_noop_refresh_false_when_dates_differ():
    assert is_noop_refresh("2026-06-01", "2026-07-03") is False


def test_is_noop_refresh_false_when_previous_is_none():
    assert is_noop_refresh(None, "2026-07-03") is False


def test_is_noop_refresh_false_when_both_unparseable():
    # None (fresh ingest()) and "" (a DB round-trip of the same unparseable
    # case) must not be treated as a match just because they're both falsy.
    assert is_noop_refresh(None, None) is False
    assert is_noop_refresh("", "") is False
    assert is_noop_refresh("", None) is False
