"""Tests for views/admin.py behavior not covered by test_views_error_display.py's
error-display regression checks."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from resume.db import connect as connect_profile
from resume.db import insert_profile
from resume.extract import ResumeProfile

_ADMIN_PY = Path(__file__).resolve().parent.parent / "views" / "admin.py"


def _load_admin_module():
    # Loaded by file path with importlib, not AppTest - views/ has no
    # __init__.py so it can't be imported normally, and this gets a direct
    # reference to _clear_pending_cv_profile that a full AppTest page-render
    # (test_views_error_display.py's approach) can't hand back. A materially
    # weaker mechanism than AppTest though: no real ScriptRunContext, and
    # st.session_state only works here because it degrades to an undocumented
    # bare-mode global fallback - see the Cancel-click test below for
    # coverage through the fully-supported path instead.
    spec = importlib.util.spec_from_file_location("admin", _ADMIN_PY)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load a module spec for {_ADMIN_PY}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clear_pending_cv_profile_clears_both_session_state_keys(streamlit_data_env):
    # streamlit_data_env seeds data/sponsors.db (needed for admin.py's
    # module-level sponsor-count check) and chdirs there before this loads.
    admin = _load_admin_module()
    import streamlit as st

    st.session_state["pending_cv_profile"] = {"raw_text": "resume text", "profile": None, "file_id": "abc"}
    st.session_state["cv_registration_in_progress"] = True
    try:
        admin._clear_pending_cv_profile()
        assert "pending_cv_profile" not in st.session_state
        assert st.session_state["cv_registration_in_progress"] is False
    finally:
        # st.session_state is a process-global singleton outside a real
        # AppTest/script-run context - clean up so this can't leak into an
        # unrelated test running later in the same pytest process.
        st.session_state.pop("pending_cv_profile", None)
        st.session_state.pop("cv_registration_in_progress", None)


def test_confirm_supersede_dialog_wires_on_dismiss_to_the_shared_helper():
    # Streamlit's dialog decorator doesn't expose its on_dismiss callable for
    # runtime introspection after decoration, so this checks the wiring at
    # the source level (whitespace-tolerant, survives reformatting) - the
    # real behavioral proof is the Cancel-click test below, which exercises
    # the same shared helper through a supported path. This check's known
    # gap: it can't tell a correctly-wired call from a same-named shadowing
    # function defined elsewhere - AppTest has no way to simulate an actual
    # X/backdrop/ESC dismiss event to close that gap for real.
    source = _ADMIN_PY.read_text(encoding="utf-8")
    assert re.search(r"on_dismiss\s*=\s*_clear_pending_cv_profile", source)


def test_cancel_button_clears_pending_cv_profile_through_the_real_dialog(streamlit_data_env):
    # Exercises the actual decorated dialog function via AppTest, not just
    # the extracted helper in isolation - proves Cancel still calls the
    # shared helper rather than reintroducing separate/diverged cleanup logic
    # (a mutation test confirmed the two tests above alone miss exactly this
    # regression).
    conn = connect_profile(streamlit_data_env["profile_db"])
    try:
        insert_profile(
            conn,
            "current resume text",
            ResumeProfile(seniority="senior", core_skills=[], domains=[], past_roles=[], summary="current"),
        )
    finally:
        conn.close()

    at = AppTest.from_file(str(_ADMIN_PY))
    at.session_state["pending_cv_profile"] = {
        "raw_text": "new resume text",
        "profile": ResumeProfile(seniority="mid", core_skills=[], domains=[], past_roles=[], summary="new"),
        "file_id": "file-abc",
    }
    at.session_state["cv_registration_in_progress"] = True
    at.run()

    cancel_button = next(b for b in at.button if b.label == "Cancel")
    cancel_button.click().run()

    assert not at.error
    assert "pending_cv_profile" not in at.session_state
    assert at.session_state["cv_registration_in_progress"] is False
