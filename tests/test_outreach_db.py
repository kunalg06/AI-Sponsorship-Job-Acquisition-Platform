import sqlite3
from datetime import datetime, timezone

from jobs.db import connect, insert_job
from jobs.extract import JobExtraction
from jobs.outreach_db import (
    drop_legacy_message_column,
    ensure_schema,
    get_contact,
    insert_contact,
    insert_outreach_message,
    list_contacts,
    list_legacy_outreach_message_rows,
    list_outreach_messages,
    mark_outreach_write_failed,
)


def _job_db(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    ensure_schema(conn)
    return conn


def test_insert_and_get_contact_round_trips(tmp_path):
    conn = _job_db(tmp_path)
    try:
        job_id = insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
        contact_id = insert_contact(
            conn, job_id, "Sarah Cole", title="Talent Partner", linkedin_url="https://linkedin.com/in/sarahcole", email=None
        )

        contact = get_contact(conn, contact_id)
        assert contact["name"] == "Sarah Cole"
        assert contact["title"] == "Talent Partner"
        assert contact["linkedin_url"] == "https://linkedin.com/in/sarahcole"
        assert contact["job_id"] == job_id
    finally:
        conn.close()


def test_list_contacts_orders_newest_first(tmp_path):
    conn = _job_db(tmp_path)
    try:
        job_id = insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
        insert_contact(conn, job_id, "First Contact")
        insert_contact(conn, job_id, "Second Contact")

        contacts = list_contacts(conn, job_id)
        assert [c["name"] for c in contacts] == ["Second Contact", "First Contact"]
    finally:
        conn.close()


def test_insert_and_list_outreach_messages(tmp_path):
    conn = _job_db(tmp_path)
    try:
        job_id = insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
        insert_outreach_message(
            conn, job_id, contact_id=None, contact_name="Sarah Cole", channel="linkedin_note", message="Hi Sarah!"
        )

        messages = list_outreach_messages(conn, job_id)
        assert len(messages) == 1
        assert messages[0]["contact_name"] == "Sarah Cole"
        assert messages[0]["channel"] == "linkedin_note"
        assert messages[0]["char_count"] == len("Hi Sarah!")
    finally:
        conn.close()


def test_inserted_outreach_message_row_has_no_message_column(tmp_path):
    """The full drafted text now lives only as a file on disk (see
    `jobs.cli._outreach_message_path`) - the DB row is metadata-only."""
    conn = _job_db(tmp_path)
    try:
        job_id = insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
        insert_outreach_message(
            conn, job_id, contact_id=None, contact_name="Sarah Cole", channel="linkedin_note", message="Hi Sarah!"
        )

        messages = list_outreach_messages(conn, job_id)
        assert "message" not in messages[0].keys()
    finally:
        conn.close()


def test_inserted_outreach_message_row_has_no_write_failure_by_default(tmp_path):
    conn = _job_db(tmp_path)
    try:
        job_id = insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
        insert_outreach_message(
            conn, job_id, contact_id=None, contact_name="Sarah Cole", channel="linkedin_note", message="Hi Sarah!"
        )

        assert list_outreach_messages(conn, job_id)[0]["write_failed_at"] is None
    finally:
        conn.close()


def test_mark_outreach_write_failed_sets_the_marker(tmp_path):
    conn = _job_db(tmp_path)
    try:
        job_id = insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
        message_id = insert_outreach_message(
            conn, job_id, contact_id=None, contact_name="Sarah Cole", channel="linkedin_note", message="Hi Sarah!"
        )

        mark_outreach_write_failed(conn, message_id)

        row = list_outreach_messages(conn, job_id)[0]
        assert row["write_failed_at"] is not None
    finally:
        conn.close()


def test_ensure_schema_adds_write_failed_at_column_to_a_pre_existing_db(tmp_path):
    # Simulate a jobs.db created before this fix: outreach_messages exists
    # without the column, since CREATE TABLE IF NOT EXISTS never adds it to
    # an already-existing table.
    db_path = tmp_path / "jobs.db"
    conn = connect(db_path)
    ensure_schema(conn)
    conn.execute("ALTER TABLE outreach_messages DROP COLUMN write_failed_at")
    existing_before = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_messages)")}
    assert "write_failed_at" not in existing_before
    conn.close()

    conn = connect(db_path)
    ensure_schema(conn)  # must migrate the pre-existing table, not just skip it
    try:
        existing_after = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_messages)")}
        assert "write_failed_at" in existing_after

        ensure_schema(conn)  # a third call, now that the column already exists, must be a safe no-op
        existing_after_third_call = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_messages)")}
        assert "write_failed_at" in existing_after_third_call
    finally:
        conn.close()


def test_list_legacy_outreach_message_rows_returns_empty_against_a_fresh_schema(tmp_path):
    """A fresh DB (created after this change) never gets the `message`
    column at all - it's no longer part of SCHEMA. Querying it unguarded
    would be a hard sqlite3 error, not an empty result."""
    conn = _job_db(tmp_path)
    try:
        insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
        assert list_legacy_outreach_message_rows(conn) == []
    finally:
        conn.close()


def _add_legacy_message_column_with_text(conn: sqlite3.Connection, job_id: int, contact_name: str, channel: str, message: str) -> int:
    """Simulate a jobs.db created before this refactor: the `message`
    column still exists as a real column with real data, since dropping a
    column is a one-time migration action, never something schema
    application does automatically."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_messages)")}
    if "message" not in existing:
        conn.execute("ALTER TABLE outreach_messages ADD COLUMN message TEXT")
    cursor = conn.execute(
        """
        INSERT INTO outreach_messages (job_id, contact_id, contact_name, channel, message, char_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, None, contact_name, channel, message, len(message), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return cursor.lastrowid


def test_list_legacy_outreach_message_rows_returns_legacy_rows_with_company_name(tmp_path):
    conn = _job_db(tmp_path)
    try:
        job_id = insert_job(
            conn, "raw text", JobExtraction(job_title="AI Engineer", company_name="Bending Spoons", is_agency_posting=False)
        )
        message_id = _add_legacy_message_column_with_text(conn, job_id, "Sarah Cole", "linkedin_note", "Hi Sarah!")

        rows = list_legacy_outreach_message_rows(conn)
        assert len(rows) == 1
        assert rows[0]["id"] == message_id
        assert rows[0]["job_id"] == job_id
        assert rows[0]["channel"] == "linkedin_note"
        assert rows[0]["message"] == "Hi Sarah!"
        assert rows[0]["company_name"] == "Bending Spoons"
    finally:
        conn.close()


def test_drop_legacy_message_column_drops_it_when_present(tmp_path):
    conn = _job_db(tmp_path)
    try:
        job_id = insert_job(conn, "raw text", JobExtraction(job_title="AI Engineer", is_agency_posting=False))
        _add_legacy_message_column_with_text(conn, job_id, "Sarah Cole", "linkedin_note", "Hi Sarah!")

        existing_before = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_messages)")}
        assert "message" in existing_before

        drop_legacy_message_column(conn)

        existing_after = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_messages)")}
        assert "message" not in existing_after
    finally:
        conn.close()


def test_drop_legacy_message_column_is_a_safe_no_op_when_absent(tmp_path):
    conn = _job_db(tmp_path)
    try:
        existing_before = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_messages)")}
        assert "message" not in existing_before

        drop_legacy_message_column(conn)  # must not raise

        existing_after = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_messages)")}
        assert "message" not in existing_after
    finally:
        conn.close()
