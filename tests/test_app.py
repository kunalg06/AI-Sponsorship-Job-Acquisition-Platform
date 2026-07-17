"""Tests for `app.py`'s GEMINI_API_KEY and GENERATED_CV_DIR secrets-bridging
- had zero coverage before this file, since app.py executes
st.set_page_config/st.navigation/pg.run() as a side effect of import, so a
plain pytest import runs the whole page router, not just the bridging
logic. `AppTest` sidesteps that by running the real script in a sandboxed
Streamlit runtime."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

# Resolved at import time (before any test's chdir into a tmp sandbox) so
# AppTest.from_file can find the real script regardless of the test's cwd.
APP_PY = str(Path(__file__).resolve().parent.parent / "app.py")


def _make_restore_env_var_fixture(name: str):
    """`monkeypatch.delenv(name, raising=False)` only queues an undo action
    when `name` already existed - if it was absent, monkeypatch has nothing
    to restore and does nothing at teardown. app.py's secrets bridge adds
    the var back to the real `os.environ` *during* these tests (outside
    monkeypatch's tracking entirely, since it's a plain assignment in the
    script under test, not a call through the monkeypatch fixture), so
    without this, a value set during one test leaks into every later test
    in the process - confirmed via a minimal repro while developing the
    GENERATED_CV_DIR tests below. Directly saves/restores the real env var
    around the test instead of relying on monkeypatch for it."""

    @pytest.fixture
    def _fixture():
        original = os.environ.get(name)
        yield
        if original is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = original

    return _fixture


restore_gemini_api_key_env = _make_restore_env_var_fixture("GEMINI_API_KEY")
restore_generated_cv_dir_env = _make_restore_env_var_fixture("GENERATED_CV_DIR")


def test_app_bridges_gemini_api_key_from_secrets_when_env_unset(streamlit_data_env, monkeypatch, restore_gemini_api_key_env):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # python-dotenv's load_dotenv() searches upward from the caller's (app.py's)
    # own file location, not the chdir'd cwd - so without this it would load
    # this machine's real project .env and mask the case under test.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    at = AppTest.from_file(APP_PY)
    at.secrets["GEMINI_API_KEY"] = "secrets-value"
    at.run()

    assert os.environ["GEMINI_API_KEY"] == "secrets-value"


def test_app_leaves_existing_env_gemini_api_key_unchanged(streamlit_data_env, monkeypatch, restore_gemini_api_key_env):
    monkeypatch.setenv("GEMINI_API_KEY", "already-set")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    at = AppTest.from_file(APP_PY)
    at.secrets["GEMINI_API_KEY"] = "a-different-secrets-value"
    at.run()

    assert os.environ["GEMINI_API_KEY"] == "already-set"


def test_app_leaves_gemini_api_key_unset_and_warns_when_neither_env_nor_secrets_has_it(
    streamlit_data_env, monkeypatch, capsys, restore_gemini_api_key_env
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


def test_app_bridges_generated_cv_dir_from_secrets_when_env_unset(streamlit_data_env, monkeypatch, restore_generated_cv_dir_env):
    monkeypatch.delenv("GENERATED_CV_DIR", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    at = AppTest.from_file(APP_PY)
    at.secrets["GENERATED_CV_DIR"] = "/custom/cv/output"
    at.run()

    assert os.environ["GENERATED_CV_DIR"] == "/custom/cv/output"


def test_app_leaves_existing_env_generated_cv_dir_unchanged(streamlit_data_env, monkeypatch, restore_generated_cv_dir_env):
    monkeypatch.setenv("GENERATED_CV_DIR", "already-set")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    at = AppTest.from_file(APP_PY)
    at.secrets["GENERATED_CV_DIR"] = "a-different-secrets-value"
    at.run()

    assert os.environ["GENERATED_CV_DIR"] == "already-set"


def test_app_leaves_generated_cv_dir_unset_with_no_warning_when_neither_env_nor_secrets_has_it(
    streamlit_data_env, monkeypatch, capsys, restore_generated_cv_dir_env
):
    # Unlike GEMINI_API_KEY, this one has a working default (cv/generated_cv)
    # - being unset is the normal, expected case, so no warning is printed.
    monkeypatch.delenv("GENERATED_CV_DIR", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    at = AppTest.from_file(APP_PY)
    at.run()

    assert "GENERATED_CV_DIR" not in os.environ
    assert "GENERATED_CV_DIR" not in capsys.readouterr().err
