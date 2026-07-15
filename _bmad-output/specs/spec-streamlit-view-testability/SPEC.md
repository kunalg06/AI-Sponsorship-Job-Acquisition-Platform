---
id: SPEC-streamlit-view-testability
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Streamlit view testability

## Why

A pain to solve. Two separate deferred-work entries share one root cause: `app.py` and `views/*.py` execute top-level code as a side effect of import (DB connections, `st.navigation`, `st.set_page_config`), so a plain `pytest` import can't isolate logic under test. This has left `app.py`'s `GEMINI_API_KEY` secrets-bridging (flagged 2026-07-12) and the `error_display_text` call-site wiring across `views/admin.py`/`views/intake.py`/`views/jobs_list.py` (flagged 2026-07-15) both untested — a future typo or partial revert at any of these sites would regress silently past the full test suite.

## Capabilities

- **CAP-1**
  - **intent:** `app.py`'s `GEMINI_API_KEY` secrets-bridging is verified by an automated test, covering both the `st.secrets`-present and `st.secrets`-absent cases.
  - **success:** A test asserts `os.environ["GEMINI_API_KEY"]` is set after running `app.py` with `st.secrets` mocked to contain the key; a second test asserts an already-set env/`.env` value is left untouched (env always wins per `app.py`'s existing logic).

- **CAP-2**
  - **intent:** At least one automated regression test per view file (`admin.py`, `intake.py`, `jobs_list.py`) proves a caught exception's displayed text comes from `error_display_text`, not bare `str(exc)`.
  - **success:** For each of the 3 files, a test forces an exception with an empty `str()` at one call site and asserts the rendered error message is non-empty and names the exception type.

## Constraints

- Use `streamlit.testing.v1.AppTest` (confirmed available, `streamlit==1.58.0` installed) to run `app.py`/`views/*.py` as real scripts, instead of extracting logic into separately-testable helper modules — no production code changes required.
- `views/admin.py:38`, `views/intake.py:41,43`, `views/jobs_list.py:24-25`, and `register/cli.py:15` hardcode relative DB paths (`data/jobs.db`, `data/profile.db`, `data/sponsors.db`) as module-level constants, not parameterized. Every `AppTest`-based test must run with the working directory changed to a pytest `tmp_path` (`monkeypatch.chdir`) containing freshly-seeded DB files at those exact relative paths — never touch the real project `data/` directory. Seeding is one `connect()` call per DB module; `jobs.db`/`resume.db`/`register.db`'s `connect()` all run `CREATE TABLE IF NOT EXISTS`, so no new seeding helper is needed.

## Non-goals

- Extracting business logic out of `app.py`/`views/*.py` into separately-testable helper modules.
- Full coverage of all 10 `error_display_text` call sites, or general end-to-end coverage of every view's user flow — this closes the specific regression-detection gap the two source deferred-work entries named.

## Success signal

- Both source deferred-work entries can be marked `done`: a passing test suite fails if `app.py`'s secrets-bridging breaks, or if any of the 3 view files' error-display wiring reverts to bare `str(exc)`.
