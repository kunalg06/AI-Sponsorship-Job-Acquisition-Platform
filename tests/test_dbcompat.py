import sqlite3

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
