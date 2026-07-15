"""Tests for `app.py`'s GEMINI_API_KEY secrets-bridging - had zero coverage
before this file, since app.py executes st.set_page_config/st.navigation/
pg.run() as a side effect of import, so a plain pytest import runs the
whole page router, not just the bridging logic. `AppTest` sidesteps that
by running the real script in a sandboxed Streamlit runtime."""

from __future__ import annotations

import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

# Resolved at import time (before any test's chdir into a tmp sandbox) so
# AppTest.from_file can find the real script regardless of the test's cwd.
APP_PY = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_bridges_gemini_api_key_from_secrets_when_env_unset(streamlit_data_env, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # python-dotenv's load_dotenv() searches upward from the caller's (app.py's)
    # own file location, not the chdir'd cwd - so without this it would load
    # this machine's real project .env and mask the case under test.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    at = AppTest.from_file(APP_PY)
    at.secrets["GEMINI_API_KEY"] = "secrets-value"
    at.run()

    assert os.environ["GEMINI_API_KEY"] == "secrets-value"


def test_app_leaves_existing_env_gemini_api_key_unchanged(streamlit_data_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "already-set")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    at = AppTest.from_file(APP_PY)
    at.secrets["GEMINI_API_KEY"] = "a-different-secrets-value"
    at.run()

    assert os.environ["GEMINI_API_KEY"] == "already-set"


def test_app_leaves_gemini_api_key_unset_and_warns_when_neither_env_nor_secrets_has_it(
    streamlit_data_env, monkeypatch, capsys
):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    at = AppTest.from_file(APP_PY)
    # at.secrets left empty - AppTest only overrides st.secrets when it's
    # non-empty, so this exercises the real "no secrets.toml anywhere"
    # path app.py's own except Exception: pass is written for.
    at.run()

    assert "GEMINI_API_KEY" not in os.environ
    assert "GEMINI_API_KEY not found" in capsys.readouterr().err
