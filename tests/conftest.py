"""Shared pytest fixtures. `streamlit_data_env` backs the `AppTest`-based
tests in test_app.py/test_views_error_display.py - app.py and views/*.py
hardcode relative data/*.db paths as module-level constants, so those
scripts can only be run safely from a chdir'd tmp_path with fresh DBs
already seeded at those exact paths."""

from __future__ import annotations

import pytest

from jobs.db import connect as connect_jobs
from register.db import connect as connect_register
from resume.db import connect as connect_profile


@pytest.fixture(autouse=True)
def _no_turso_env(monkeypatch):
    """Guarantees every test hits a plain local sqlite file, never the real
    Turso-backed production database - regardless of what happens to be in
    the developer's own `.env`. `dbcompat.connect()` (see
    `src/dbcompat/__init__.py`) keys entirely off `TURSO_{prefix}_URL`/
    `_TOKEN` env vars, never the local path passed in - so once any test
    imports `jobs.cli` (which calls `load_dotenv()` at module level), those
    vars stay set process-wide for the rest of the pytest run, and even a
    `tmp_path`-isolated `connect()` call silently opens an embedded replica
    of the real shared database instead. Confirmed happening for real: a
    full test-suite run wrote several `test_jobs_cli.py`/`test_ui_actions.py`
    fixture rows ("Acme AI", "Bending Spoons") into production before this
    fixture existed."""
    for prefix in ("JOBS", "SPONSORS", "PROFILE", "ROADMAP"):
        monkeypatch.delenv(f"TURSO_{prefix}_URL", raising=False)
        monkeypatch.delenv(f"TURSO_{prefix}_TOKEN", raising=False)


@pytest.fixture
def streamlit_data_env(tmp_path, monkeypatch):
    """Chdir into `tmp_path` and seed empty-but-valid data/jobs.db,
    data/profile.db, data/sponsors.db - each connect() call runs
    `CREATE TABLE IF NOT EXISTS`, so no separate schema-seeding helper is
    needed. Returns a dict of ready-made `pathlib.Path`s (root/jobs_db/
    profile_db/sponsors_db) for tests that want to seed rows afterward -
    follows the same dict-keyed-by-DB-name convention as test_ui_actions.py's
    own `ui_tailor_env` fixture (not an identical shape - that one has no
    `root`/`sponsors_db` keys and adds two mock-object keys of its own)."""
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    jobs_db = data_dir / "jobs.db"
    profile_db = data_dir / "profile.db"
    sponsors_db = data_dir / "sponsors.db"
    connect_jobs(jobs_db).close()
    connect_profile(profile_db).close()
    connect_register(sponsors_db).close()

    return {"root": tmp_path, "jobs_db": jobs_db, "profile_db": profile_db, "sponsors_db": sponsors_db}
