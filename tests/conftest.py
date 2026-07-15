"""Shared pytest fixtures. `streamlit_data_env` backs the `AppTest`-based
tests in test_app.py/test_views_error_display.py - app.py and views/*.py
hardcode relative data/*.db paths as module-level constants, so those
scripts can only be run safely from a chdir'd tmp_path with fresh DBs
already seeded at those exact paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobs.db import connect as connect_jobs
from register.db import connect as connect_register
from resume.db import connect as connect_profile


@pytest.fixture
def streamlit_data_env(tmp_path, monkeypatch):
    """Chdir into `tmp_path` and seed empty-but-valid data/jobs.db,
    data/profile.db, data/sponsors.db - each connect() call runs
    `CREATE TABLE IF NOT EXISTS`, so no separate schema-seeding helper is
    needed. Returns `tmp_path` for tests that want to seed rows afterward."""
    monkeypatch.chdir(tmp_path)
    data_dir = Path("data")
    data_dir.mkdir()

    connect_jobs(data_dir / "jobs.db").close()
    connect_profile(data_dir / "profile.db").close()
    connect_register(data_dir / "sponsors.db").close()

    return tmp_path
