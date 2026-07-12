import ast
import sqlite3
from pathlib import Path

import mcp_server.tools as tools_module
import pytest

from jobs.db import connect as connect_jobs
from jobs.db import insert_job
from jobs.extract import JobExtraction
from jobs.tracker import APPLIED
from mcp_server.tools import (
    _ACTIONS,
    check_salary_threshold,
    check_sponsor,
    list_applications,
    track_application,
)
from register.db import SponsorRecord
from register.db import connect as connect_register
from register.db import replace_all
from register.normalize import make_match_key


def _register_with(tmp_path, records):
    conn = connect_register(tmp_path / "sponsors.db")
    replace_all(conn, records)
    conn.close()
    return tmp_path / "sponsors.db"


def _jobs_db_with_one_job(tmp_path, job_title="AI Engineer"):
    db_path = tmp_path / "jobs.db"
    conn = connect_jobs(db_path)
    try:
        job_id = insert_job(conn, "raw text", JobExtraction(job_title=job_title, is_agency_posting=False))
    finally:
        conn.close()
    return db_path, job_id


def _audit_rows(jobs_db):
    """Raw read of every `mcp_audit_log` row, ordered by insertion - a plain
    sqlite3 connection (not `jobs.db.connect`) so these assertions don't
    depend on `track_application`'s own table-creation logic under test."""
    conn = sqlite3.connect(jobs_db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM mcp_audit_log ORDER BY id").fetchall()
    finally:
        conn.close()


def test_check_sponsor_confirmed_when_employer_name_matches_register_under_a_different_suffix_and_case(tmp_path):
    record = SponsorRecord(
        organisation_name="Acme AI Limited",
        trading_name=None,
        match_key=make_match_key("Acme AI Limited"),
        town_city="London",
        county="Greater London",
        rating="Worker (A rating)",
        route="Skilled Worker",
        source_updated="2026-07-03",
    )
    sponsor_db = _register_with(tmp_path, [record])

    result = check_sponsor("Acme AI Ltd", sponsor_db=sponsor_db)

    assert result["status"] == "confirmed"
    assert result["matched_name"] == "Acme AI Limited"
    assert result["town_city"] == "London"
    assert result["county"] == "Greater London"
    assert result["rating"] == "Worker (A rating)"
    assert result["route"] == "Skilled Worker"


def test_check_sponsor_cannot_verify_when_employer_name_is_none_eg_agency_redacted_client(tmp_path):
    sponsor_db = _register_with(tmp_path, [])

    result = check_sponsor(None, sponsor_db=sponsor_db)

    assert result["status"] == "cannot_verify"


def test_check_salary_threshold_below_threshold_for_a_low_ai_engineer_salary():
    result = check_salary_threshold("AI Engineer", "£30,000")

    assert result["status"] == "below_threshold"


def test_track_application_mark_applied_sets_status_and_a_non_null_applied_at(tmp_path):
    jobs_db, job_id = _jobs_db_with_one_job(tmp_path)

    result = track_application(job_id, "applied", jobs_db=jobs_db)

    assert result["applied_status"] == "applied"
    assert result["applied_at"] is not None

    rows = _audit_rows(jobs_db)
    assert len(rows) == 1
    assert rows[0]["job_id"] == job_id
    assert rows[0]["action"] == "applied"
    assert rows[0]["previous_status"] is None  # job had no applied_status before this call
    assert rows[0]["result"] == "success"
    assert rows[0]["error"] is None
    assert rows[0]["timestamp"] is not None


def test_track_application_mark_discarded_writes_a_success_audit_row(tmp_path):
    jobs_db, job_id = _jobs_db_with_one_job(tmp_path)

    result = track_application(job_id, "discarded", jobs_db=jobs_db)

    assert result["applied_status"] == "discarded"

    rows = _audit_rows(jobs_db)
    assert len(rows) == 1
    assert rows[0]["job_id"] == job_id
    assert rows[0]["action"] == "discarded"
    assert rows[0]["previous_status"] is None  # job had no applied_status before this call
    assert rows[0]["result"] == "success"
    assert rows[0]["error"] is None


def test_track_application_records_the_real_prior_status_when_re_tracking_an_already_applied_job(tmp_path):
    jobs_db, job_id = _jobs_db_with_one_job(tmp_path)
    track_application(job_id, "applied", jobs_db=jobs_db)

    result = track_application(job_id, "discarded", jobs_db=jobs_db)

    assert result["applied_status"] == "discarded"

    rows = _audit_rows(jobs_db)
    assert len(rows) == 2
    assert rows[1]["action"] == "discarded"
    assert rows[1]["previous_status"] == "applied"  # captured from the job's state before this mutation


def test_track_application_raises_value_error_naming_the_bad_action(tmp_path):
    jobs_db, job_id = _jobs_db_with_one_job(tmp_path)

    with pytest.raises(ValueError, match="maybe"):
        track_application(job_id, "maybe", jobs_db=jobs_db)


def test_track_application_with_invalid_action_opens_no_connection_and_creates_no_file_and_logs_nothing(tmp_path):
    # Deliberately NOT using _jobs_db_with_one_job (which would create the
    # file via connect_jobs) - this path must stay a zero-I/O fast-fail, so
    # we need a path that is provably untouched both before and after the
    # call, not the shared tmp_path fixture in a state some other helper
    # already mutated.
    jobs_db = tmp_path / "never_created.db"
    assert not jobs_db.exists()

    with pytest.raises(ValueError, match="maybe"):
        track_application(1, "maybe", jobs_db=jobs_db)

    assert not jobs_db.exists()  # no connection was opened - connect_jobs() would have created this file


def test_track_application_with_invalid_action_against_an_existing_db_logs_nothing(tmp_path):
    # Same zero-I/O contract as the never-created-file case above, but against
    # a jobs_db that already exists (and already has rows) - the action-validity
    # check must short-circuit before any audit table is created here too.
    jobs_db, job_id = _jobs_db_with_one_job(tmp_path)

    with pytest.raises(ValueError, match="maybe"):
        track_application(job_id, "maybe", jobs_db=jobs_db)

    conn = sqlite3.connect(jobs_db)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "mcp_audit_log" not in tables


def test_track_application_raises_value_error_for_an_unknown_job_id(tmp_path):
    jobs_db, _job_id = _jobs_db_with_one_job(tmp_path)

    with pytest.raises(ValueError, match="no job with id 999999"):
        track_application(999999, "applied", jobs_db=jobs_db)


def test_track_application_logs_an_error_audit_row_for_an_unknown_job_id_before_raising(tmp_path):
    jobs_db, _job_id = _jobs_db_with_one_job(tmp_path)

    with pytest.raises(ValueError, match="no job with id 999999"):
        track_application(999999, "applied", jobs_db=jobs_db)

    rows = _audit_rows(jobs_db)
    assert len(rows) == 1
    assert rows[0]["job_id"] == 999999
    assert rows[0]["action"] == "applied"
    assert rows[0]["previous_status"] is None
    assert rows[0]["result"] == "error"
    assert "no job with id 999999" in rows[0]["error"]


def test_track_application_logs_an_error_audit_row_when_the_mutation_itself_raises_and_still_reraises(
    tmp_path, monkeypatch
):
    # Simulates mark_applied/mark_discarded itself failing after a successful
    # job lookup - the case the first (reverted) implementation missed.
    jobs_db, job_id = _jobs_db_with_one_job(tmp_path)

    def _boom(conn, job_id):
        raise RuntimeError("disk full")

    monkeypatch.setitem(_ACTIONS, APPLIED, _boom)

    with pytest.raises(RuntimeError, match="disk full"):
        track_application(job_id, "applied", jobs_db=jobs_db)

    rows = _audit_rows(jobs_db)
    assert len(rows) == 1
    assert rows[0]["job_id"] == job_id
    assert rows[0]["action"] == "applied"
    assert rows[0]["previous_status"] is None  # captured before the mutation raised
    assert rows[0]["result"] == "error"
    assert rows[0]["error"] == "RuntimeError: disk full"


def test_track_application_backfills_a_missing_column_on_a_pre_existing_differently_shaped_audit_table(tmp_path):
    jobs_db, job_id = _jobs_db_with_one_job(tmp_path)

    conn = connect_jobs(jobs_db)
    try:
        # A pre-existing mcp_audit_log table shaped like an older version of
        # this feature - missing the (nullable) `error` column entirely.
        conn.executescript(
            """
            CREATE TABLE mcp_audit_log (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                job_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                previous_status TEXT,
                result TEXT NOT NULL
            );
            """
        )
    finally:
        conn.close()

    result = track_application(job_id, "applied", jobs_db=jobs_db)

    assert result["applied_status"] == "applied"  # no error despite the differently-shaped pre-existing table

    rows = _audit_rows(jobs_db)
    assert len(rows) == 1
    assert rows[0]["result"] == "success"
    assert rows[0]["error"] is None  # backfilled column accepted the write normally


def test_track_application_success_return_value_survives_a_logging_failure(tmp_path, monkeypatch):
    jobs_db, job_id = _jobs_db_with_one_job(tmp_path)

    def _boom(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(tools_module, "_record_audit", _boom)

    result = track_application(job_id, "applied", jobs_db=jobs_db)

    assert result["applied_status"] == "applied"  # mutation already committed - logging failure must not mask it


def test_track_application_unknown_job_id_still_raises_original_error_when_logging_fails(tmp_path, monkeypatch):
    jobs_db, _job_id = _jobs_db_with_one_job(tmp_path)

    def _boom(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(tools_module, "_record_audit", _boom)

    with pytest.raises(ValueError, match="no job with id 999999"):
        track_application(999999, "applied", jobs_db=jobs_db)


def test_track_application_mutation_raises_still_raises_original_error_when_logging_also_fails(tmp_path, monkeypatch):
    jobs_db, job_id = _jobs_db_with_one_job(tmp_path)

    def _mutation_boom(conn, job_id):
        raise RuntimeError("disk full")

    def _logging_boom(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setitem(_ACTIONS, APPLIED, _mutation_boom)
    monkeypatch.setattr(tools_module, "_record_audit", _logging_boom)

    with pytest.raises(RuntimeError, match="disk full"):
        track_application(job_id, "applied", jobs_db=jobs_db)


def test_list_applications_due_only_returns_empty_list_when_only_recently_applied_jobs(tmp_path):
    jobs_db, job_id = _jobs_db_with_one_job(tmp_path)
    track_application(job_id, "applied", jobs_db=jobs_db)

    assert list_applications(due_only=True, jobs_db=jobs_db) == []


def test_list_applications_without_due_only_returns_the_applied_job_annotated_with_its_milestone(tmp_path):
    jobs_db, job_id = _jobs_db_with_one_job(tmp_path)
    track_application(job_id, "applied", jobs_db=jobs_db)

    results = list_applications(jobs_db=jobs_db)

    assert len(results) == 1
    assert results[0]["id"] == job_id
    assert results[0]["due_milestone"] is None  # applied moments ago - nothing due yet


def test_tools_module_source_contains_no_mcp_import_so_it_stays_importable_without_the_sdk():
    # Structural check for the tools.py/server.py split described in the spec:
    # mcp_server.tools must be importable and unit-testable even if the `mcp`
    # SDK isn't installed - only mcp_server.server needs it. Parsing the
    # source (rather than checking sys.modules) avoids a false pass caused by
    # some other test module importing `mcp` earlier in the same pytest
    # process.
    tree = ast.parse(Path(tools_module.__file__).read_text())
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any(name == "mcp" or name.startswith("mcp.") for name in imported_modules)
