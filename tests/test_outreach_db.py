from jobs.db import connect, insert_job
from jobs.extract import JobExtraction
from jobs.outreach_db import (
    ensure_schema,
    get_contact,
    insert_contact,
    insert_outreach_message,
    list_contacts,
    list_outreach_messages,
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
