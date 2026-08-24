"""Tests for `app.py`'s startup configuration handling (GEMINI_API_KEY,
GENERATED_CV_DIR). app.py executes st.set_page_config/st.navigation/pg.run()
as a side effect of import, so a plain pytest import runs the whole page
router rather than just the startup logic. `AppTest` sidesteps that by
running the real script in a sandboxed Streamlit runtime.

These once covered a bridge from `st.secrets` into `os.environ`, needed
because Streamlit Community Cloud delivers secrets that way. That deploy is
gone (see spec-retire-cloud-deployment) and `.env` is now the only source,
so what remains is that app.py reads the environment and never clobbers it."""

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
    to restore and does nothing at teardown. app.py's startup adds
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


def test_app_leaves_existing_env_gemini_api_key_unchanged(streamlit_data_env, monkeypatch, restore_gemini_api_key_env):
    monkeypatch.setenv("GEMINI_API_KEY", "already-set")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    at = AppTest.from_file(APP_PY)
    at.run()

    assert os.environ["GEMINI_API_KEY"] == "already-set"


def test_app_leaves_gemini_api_key_unset_and_warns_when_the_environment_lacks_it(
    streamlit_data_env, monkeypatch, capsys, restore_gemini_api_key_env
):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    at = AppTest.from_file(APP_PY)
    at.run()

    assert "GEMINI_API_KEY" not in os.environ
    assert "GEMINI_API_KEY not found" in capsys.readouterr().err


def test_app_leaves_existing_env_generated_cv_dir_unchanged(streamlit_data_env, monkeypatch, restore_generated_cv_dir_env):
    monkeypatch.setenv("GENERATED_CV_DIR", "already-set")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    at = AppTest.from_file(APP_PY)
    at.run()

    assert os.environ["GENERATED_CV_DIR"] == "already-set"


def test_app_leaves_generated_cv_dir_unset_with_no_warning_when_the_environment_lacks_it(
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
