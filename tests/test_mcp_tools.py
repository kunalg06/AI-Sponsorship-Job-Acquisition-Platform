import ast
from pathlib import Path

import mcp_server.tools as tools_module
import pytest

from jobs.db import connect as connect_jobs
from jobs.db import insert_job
from jobs.extract import JobExtraction
from mcp_server.tools import (
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


def test_track_application_raises_value_error_naming_the_bad_action(tmp_path):
    jobs_db, job_id = _jobs_db_with_one_job(tmp_path)

    with pytest.raises(ValueError, match="maybe"):
        track_application(job_id, "maybe", jobs_db=jobs_db)


def test_track_application_raises_value_error_for_an_unknown_job_id(tmp_path):
    jobs_db, _job_id = _jobs_db_with_one_job(tmp_path)

    with pytest.raises(ValueError, match="no job with id 999999"):
        track_application(999999, "applied", jobs_db=jobs_db)


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
