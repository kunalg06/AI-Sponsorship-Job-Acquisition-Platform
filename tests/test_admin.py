"""Tests for views/admin.py behavior not covered by test_views_error_display.py's
error-display regression checks."""

from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path
from unittest.mock import MagicMock

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

    st.session_state["pending_cv_profile"] = {"raw_text": "resume text", "profile": None, "content_hash": "abc"}
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
        "content_hash": "deadbeef",
    }
    at.session_state["cv_registration_in_progress"] = True
    at.run()

    cancel_button = next(b for b in at.button if b.label == "Cancel")
    cancel_button.click().run()

    assert not at.error
    assert "pending_cv_profile" not in at.session_state
    assert at.session_state["cv_registration_in_progress"] is False


def test_reselecting_the_same_cv_file_via_a_fresh_upload_is_recognized_as_already_registered(streamlit_data_env):
    # Fast, hand-seeded check of the read/comparison side only (does
    # already_registered correctly compare against a pre-set hash). Does not
    # prove the write side (_register_pending_profile actually storing a
    # matching hash) or that a fresh upload really does mint a new file_id -
    # see the end-to-end test below for both of those.
    content = b"Jane Doe\nSenior ML Engineer\nSkills: Python, PyTorch"

    at = AppTest.from_file(str(_ADMIN_PY))
    at.session_state["last_registered_cv_hash"] = hashlib.sha256(content).hexdigest()
    at.run()
    at.file_uploader[0].set_value(("resume.txt", content, "text/plain"))
    at.run()

    assert not at.error
    assert any("already been registered" in info.value for info in at.info)
    register_button = next(b for b in at.button if b.label == "Extract & Register Profile")
    assert register_button.proto.disabled is True


def test_registering_then_reuploading_the_same_bytes_end_to_end_is_recognized_as_already_registered(
    streamlit_data_env, monkeypatch
):
    # Drives the real registration path (not a hand-seeded hash) end to end,
    # covering both halves of the SPEC's success signal: the still-held
    # upload staying recognized across reruns, and a fresh re-upload of the
    # same bytes (a genuinely new file_id, verified below, not just assumed)
    # also being recognized once the guard has something registered to
    # compare against.
    content = b"Jane Doe\nSenior ML Engineer\nSkills: Python, PyTorch"
    mock_extract = MagicMock(
        return_value=ResumeProfile(seniority="senior", core_skills=[], domains=[], past_roles=[], summary="s")
    )
    monkeypatch.setattr("resume.extract.extract_profile", mock_extract)

    at = AppTest.from_file(str(_ADMIN_PY))
    at.run()
    at.file_uploader[0].set_value(("resume.txt", content, "text/plain"))
    at.run()
    first_file_id = at.file_uploader[0].value.file_id

    register_button = next(b for b in at.button if b.label == "Extract & Register Profile")
    register_button.click().run()

    assert not at.error
    assert at.session_state["last_registered_cv_hash"] == hashlib.sha256(content).hexdigest()

    # Still-held upload, no re-selection: stays recognized across a rerun
    # triggered by something else entirely (e.g. clicking another button).
    at.run()
    assert any("already been registered" in info.value for info in at.info)

    # Fresh re-selection of the identical bytes: a genuinely new file_id
    # (verified, not assumed), still recognized via content, not identity.
    at.file_uploader[0].set_value(("resume.txt", content, "text/plain"))
    at.run()
    second_file_id = at.file_uploader[0].value.file_id
    assert second_file_id != first_file_id
    assert any("already been registered" in info.value for info in at.info)
