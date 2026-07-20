"""Shared sqlite3<->Turso connection helper, used by every domain's db.py
(jobs, register, resume, roadmap) - each domain stays independent (its own
schema, its own queries), but they all need the identical answer to one
cross-cutting question: "is this DB backed by local SQLite or a remote
Turso database this time?"

Streamlit Community Cloud gives an app no persistent disk - a container
rebuild (redeploy, sleep/wake, or just a routine recycle) wipes anything
written locally, including a SQLite file. Turso is a hosted, wire-compatible
fork of SQLite: pointing at it doesn't change the data model or queries,
only where the durable copy of the file actually lives. `connect()` below
picks between the two per-database via environment variables (bridged from
`st.secrets` in `app.py`, the same pattern already used for `GEMINI_API_KEY`)
so local development is completely unaffected - no Turso env vars set,
no behavior change, not even a new import touched at runtime.

`libsql` (the Turso-backed branch) needed empirical verification before any
of this was written, not assumption from docs: confirmed live against a
real Turso database that `libsql.Connection` has no `row_factory` concept
at all (`row["column"]` on a raw result raises `TypeError`, unlike
`sqlite3.Row`), rows come back as bare tuples, and `.commit()`/`with conn:`
already push writes straight to the remote (no separate manual push needed
- `.sync()` is for pulling in changes made elsewhere, which is why it's
still called once up front and once after every commit here). The `Row`/
adapter classes below exist solely to keep sqlite3's `row["column"]`-style
access working unchanged for the ~50 call sites across every domain's
db.py and every views/*.py file that already rely on it.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence


class Row:
    """Minimal `sqlite3.Row`-compatible row: integer or column-name
    indexing, `.keys()`, iteration, equality - the subset this project's
    code actually uses. Not a general-purpose reimplementation of every
    `sqlite3.Row` behavior."""

    __slots__ = ("_columns", "_values")

    def __init__(self, columns: tuple[str, ...], values: tuple[Any, ...]):
        self._columns = columns
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._values[self._columns.index(key)]
            except ValueError:
                # Matches sqlite3.Row's own behavior for an unknown column
                # name (verified live: IndexError, not KeyError/ValueError).
                raise IndexError("No item with that key") from None
        return self._values[key]

    def keys(self) -> list[str]:
        return list(self._columns)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Row):
            return self._columns == other._columns and self._values == other._values
        return NotImplemented

    def __repr__(self) -> str:
        return f"<Row {dict(zip(self._columns, self._values))}>"


class _CursorAdapter:
    """Wraps a raw `libsql` cursor so `fetchone`/`fetchall`/`fetchmany`/
    iteration all yield `Row` objects instead of bare tuples."""

    def __init__(self, cursor: Any):
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def _columns(self) -> tuple[str, ...]:
        return tuple(d[0] for d in (self._cursor.description or ()))

    def fetchone(self) -> Optional[Row]:
        row = self._cursor.fetchone()
        return None if row is None else Row(self._columns(), tuple(row))

    def fetchall(self) -> list[Row]:
        columns = self._columns()
        return [Row(columns, tuple(r)) for r in self._cursor.fetchall()]

    def fetchmany(self, size: Optional[int] = None) -> list[Row]:
        columns = self._columns()
        rows = self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()
        return [Row(columns, tuple(r)) for r in rows]

    def __iter__(self) -> Iterator[Row]:
        # libsql's raw cursor (unlike sqlite3's) isn't itself iterable -
        # confirmed live ("'builtins.Cursor' object is not iterable") - so
        # this drains fetchall() instead of delegating iteration directly.
        return iter(self.fetchall())


class _ConnectionAdapter:
    """Wraps a `libsql` embedded-replica `Connection` so `.execute()`
    returns a `Row`-yielding cursor, and every commit syncs the local
    replica against the remote Turso database afterward - writes already
    reach the remote as part of the commit itself (verified live), this
    additional sync is purely so this process's own subsequent reads see
    the latest state, not a durability requirement."""

    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _CursorAdapter:
        return _CursorAdapter(self._conn.execute(sql, params))

    def executemany(self, sql: str, seq_of_params) -> _CursorAdapter:
        return _CursorAdapter(self._conn.executemany(sql, seq_of_params))

    def executescript(self, sql: str) -> None:
        self._conn.executescript(sql)

    def commit(self) -> None:
        self._conn.commit()
        self._conn.sync()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def cursor(self) -> _CursorAdapter:
        return _CursorAdapter(self._conn.cursor())

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        result = self._conn.__exit__(exc_type, exc_val, exc_tb)
        if exc_type is None:
            self._conn.sync()
        return result


_MISSING_REPLICA_METADATA_MARKER = "db file exists but metadata file does not"


def _is_missing_replica_metadata_error(exc: BaseException) -> bool:
    return isinstance(exc, ValueError) and _MISSING_REPLICA_METADATA_MARKER in str(exc)


def connect(db_path: str | Path, *, turso_env_prefix: str) -> Any:
    """Open a connection to `db_path`. If `TURSO_{turso_env_prefix}_URL`
    and `TURSO_{turso_env_prefix}_TOKEN` are both set in the environment,
    opens a `libsql` embedded-replica connection synced against that
    remote Turso database instead - synced once immediately so reads see
    the latest remote state, not whatever the local replica file happened
    to have from before this process started (on Streamlit Cloud, that's
    usually nothing at all, since the container's disk was just rebuilt).

    Falls back to a plain `sqlite3.Connection` (`row_factory` already set
    to `sqlite3.Row`) when those two env vars aren't both set - completely
    unchanged local-dev behavior, and the caller's `Path.mkdir` /
    `PRAGMA`/`executescript` schema setup works identically either way
    since both branches expose the same `execute`/`executescript`/
    `commit`/context-manager surface.

    One case this module's original design didn't anticipate (see the
    module docstring's "no Turso env vars set locally" assumption): a
    `db_path` created by plain `sqlite3` *before* Turso was wired in for
    this database - e.g. local dev that predates this migration, using the
    same `.streamlit/secrets.toml` for both local runs and the Cloud
    deploy. `libsql.connect()` refuses to open that file at all (confirmed
    live: `ValueError: sync error: invalid local state: db file exists but
    metadata file does not`), since it was never one of its own replicas.
    Turso is the durable source of truth once these env vars exist, so
    that legacy file has nothing libsql needs - it's quarantined alongside
    itself (never deleted) and a fresh replica is initialized in its place,
    synced from the remote."""
    url = os.environ.get(f"TURSO_{turso_env_prefix}_URL")
    token = os.environ.get(f"TURSO_{turso_env_prefix}_TOKEN")
    if url and token:
        import libsql

        try:
            conn = libsql.connect(str(db_path), sync_url=url, auth_token=token)
        except ValueError as exc:
            if not _is_missing_replica_metadata_error(exc):
                raise
            quarantine_path = Path(f"{db_path}.pre-turso-backup")
            Path(db_path).replace(quarantine_path)
            conn = libsql.connect(str(db_path), sync_url=url, auth_token=token)
        conn.sync()
        return _ConnectionAdapter(conn)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
