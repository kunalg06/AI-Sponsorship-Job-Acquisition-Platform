import sqlite3
from unittest.mock import MagicMock

import pytest

import dbcompat


def test_connect_falls_back_to_plain_sqlite_when_turso_env_vars_are_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_JOBS_URL", raising=False)
    monkeypatch.delenv("TURSO_JOBS_TOKEN", raising=False)

    conn = dbcompat.connect(tmp_path / "jobs.db", turso_env_prefix="JOBS")

    assert isinstance(conn, sqlite3.Connection)
    assert conn.row_factory is sqlite3.Row


def test_connect_falls_back_when_only_one_of_url_or_token_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("TURSO_JOBS_URL", "libsql://example.turso.io")
    monkeypatch.delenv("TURSO_JOBS_TOKEN", raising=False)

    conn = dbcompat.connect(tmp_path / "jobs.db", turso_env_prefix="JOBS")

    assert isinstance(conn, sqlite3.Connection)


def test_connect_opens_a_libsql_replica_and_syncs_when_both_turso_env_vars_are_set(tmp_path, monkeypatch):
    monkeypatch.setenv("TURSO_JOBS_URL", "libsql://example.turso.io")
    monkeypatch.setenv("TURSO_JOBS_TOKEN", "fake-token")

    import libsql

    fake_conn = MagicMock()
    fake_connect = MagicMock(return_value=fake_conn)
    monkeypatch.setattr(libsql, "connect", fake_connect)

    db_path = tmp_path / "jobs.db"
    conn = dbcompat.connect(db_path, turso_env_prefix="JOBS")

    fake_connect.assert_called_once_with(str(db_path), sync_url="libsql://example.turso.io", auth_token="fake-token")
    fake_conn.sync.assert_called_once()
    assert isinstance(conn, dbcompat._ConnectionAdapter)


def test_connect_quarantines_a_pre_turso_local_file_and_retries_once(tmp_path, monkeypatch):
    # Reproduces the real failure this guards against: a data/jobs.db
    # created by plain sqlite3 before Turso env vars existed for this
    # database - libsql refuses to open it as a replica at all.
    monkeypatch.setenv("TURSO_JOBS_URL", "libsql://example.turso.io")
    monkeypatch.setenv("TURSO_JOBS_TOKEN", "fake-token")

    import libsql

    db_path = tmp_path / "jobs.db"
    legacy_bytes = b"a plain sqlite3 file, not a libsql replica"
    db_path.write_bytes(legacy_bytes)

    fake_conn = MagicMock()
    missing_metadata_error = ValueError("sync error: invalid local state: db file exists but metadata file does not")
    fake_connect = MagicMock(side_effect=[missing_metadata_error, fake_conn])
    monkeypatch.setattr(libsql, "connect", fake_connect)

    conn = dbcompat.connect(db_path, turso_env_prefix="JOBS")

    assert fake_connect.call_count == 2
    assert isinstance(conn, dbcompat._ConnectionAdapter)
    # The legacy file was moved aside, not deleted, and the original path
    # is now free for libsql's own replica to occupy.
    quarantine_path = tmp_path / "jobs.db.pre-turso-backup"
    assert quarantine_path.read_bytes() == legacy_bytes
    assert not db_path.exists()  # nothing wrote a real file here - fake_connect is mocked


def test_connect_does_not_quarantine_on_an_unrelated_value_error(tmp_path, monkeypatch):
    # A ValueError with a different message is a different failure mode
    # (e.g. a bad URL) - must propagate raw, not be misread as the
    # legacy-file case and have a real file moved aside for no reason.
    monkeypatch.setenv("TURSO_JOBS_URL", "libsql://example.turso.io")
    monkeypatch.setenv("TURSO_JOBS_TOKEN", "fake-token")

    import libsql

    db_path = tmp_path / "jobs.db"
    db_path.write_bytes(b"some file")

    fake_connect = MagicMock(side_effect=ValueError("some unrelated failure"))
    monkeypatch.setattr(libsql, "connect", fake_connect)

    with pytest.raises(ValueError, match="some unrelated failure"):
        dbcompat.connect(db_path, turso_env_prefix="JOBS")

    assert fake_connect.call_count == 1
    assert db_path.read_bytes() == b"some file"
    assert not (tmp_path / "jobs.db.pre-turso-backup").exists()


def test_row_supports_column_name_and_integer_indexing():
    row = dbcompat.Row(("id", "note"), (1, "hello"))

    assert row["id"] == 1
    assert row["note"] == "hello"
    assert row[0] == 1
    assert row[1] == "hello"
    assert row.keys() == ["id", "note"]
    assert list(row) == [1, "hello"]
    assert len(row) == 2


def test_row_equality_compares_columns_and_values():
    a = dbcompat.Row(("id", "note"), (1, "hello"))
    b = dbcompat.Row(("id", "note"), (1, "hello"))
    c = dbcompat.Row(("id", "note"), (2, "hello"))

    assert a == b
    assert a != c
    assert a != "not a row"


def test_row_raises_the_same_error_type_as_real_sqlite3_row_on_an_unknown_column_name():
    row = dbcompat.Row(("id", "note"), (1, "hello"))

    import pytest

    with pytest.raises(IndexError):
        row["nonexistent"]


def test_cursor_adapter_wraps_a_real_sqlite_cursor_into_rows(tmp_path):
    # dbcompat.Row/the adapter classes are exercised here against a real
    # sqlite3 cursor rather than a mock - the only thing that's actually
    # libsql-specific is which library opens the connection, not the shape
    # of the cursor/row API being adapted.
    raw_conn = sqlite3.connect(tmp_path / "probe.db")
    raw_conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, note TEXT)")
    raw_conn.execute("INSERT INTO t (note) VALUES ('a'), ('b')")
    raw_conn.commit()

    cursor = dbcompat._CursorAdapter(raw_conn.execute("SELECT * FROM t ORDER BY id"))
    rows = cursor.fetchall()

    assert [r["note"] for r in rows] == ["a", "b"]
    assert [r["id"] for r in rows] == [1, 2]


def test_cursor_adapter_fetchone_returns_none_past_the_last_row(tmp_path):
    raw_conn = sqlite3.connect(tmp_path / "probe.db")
    raw_conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    raw_conn.commit()

    cursor = dbcompat._CursorAdapter(raw_conn.execute("SELECT * FROM t"))

    assert cursor.fetchone() is None


def test_cursor_adapter_exposes_lastrowid_and_rowcount(tmp_path):
    raw_conn = sqlite3.connect(tmp_path / "probe.db")
    raw_conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, note TEXT)")
    raw_conn.commit()

    insert_cursor = dbcompat._CursorAdapter(raw_conn.execute("INSERT INTO t (note) VALUES ('a')"))
    raw_conn.commit()
    assert insert_cursor.lastrowid == 1

    update_cursor = dbcompat._CursorAdapter(raw_conn.execute("UPDATE t SET note = 'b' WHERE note = 'a'"))
    raw_conn.commit()
    assert update_cursor.rowcount == 1


def test_cursor_adapter_iteration_yields_rows(tmp_path):
    raw_conn = sqlite3.connect(tmp_path / "probe.db")
    raw_conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, note TEXT)")
    raw_conn.execute("INSERT INTO t (note) VALUES ('a'), ('b')")
    raw_conn.commit()

    # jobs.db._ensure_columns iterates `conn.execute(...)` directly (not via
    # .fetchall()) and does `row["name"]` on each - this is exactly that
    # pattern, proven against the adapter rather than assumed to work.
    cursor = dbcompat._CursorAdapter(raw_conn.execute("PRAGMA table_info(t)"))
    names = {row["name"] for row in cursor}

    assert names == {"id", "note"}
