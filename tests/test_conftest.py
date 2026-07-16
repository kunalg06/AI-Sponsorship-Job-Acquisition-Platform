"""Tests for shared fixtures in conftest.py itself - covers the parts of
their contract no consumer test happens to exercise indirectly."""

from __future__ import annotations

from pathlib import Path


def test_streamlit_data_env_returns_paths_to_existing_dbs_for_every_key(streamlit_data_env):
    assert set(streamlit_data_env) == {"root", "jobs_db", "profile_db", "sponsors_db"}
    for key, path in streamlit_data_env.items():
        assert isinstance(path, Path), f"{key} is not a Path: {type(path)!r}"

    assert streamlit_data_env["root"].is_dir()
    assert streamlit_data_env["jobs_db"].is_file()
    assert streamlit_data_env["profile_db"].is_file()
    assert streamlit_data_env["sponsors_db"].is_file()
