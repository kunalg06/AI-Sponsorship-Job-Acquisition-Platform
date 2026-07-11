import pytest

from register import ingest as ingest_module
from register.db import connect, lookup, lookup_contains
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
