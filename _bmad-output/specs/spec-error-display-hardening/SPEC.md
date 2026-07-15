---
id: SPEC-error-display-hardening
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Error-display hardening

## Why

A pain to solve. `st.error(str(exc))` is used identically at 10 call sites across `views/admin.py`, `views/intake.py`, and `views/jobs_list.py`. Any exception whose `str()` happens to be empty — some `OSError`/`HTTPError` subclasses, for instance — renders a completely blank error box, leaving the user with no information that something went wrong or what to do next. Flagged by the edge-case reviewer of the Admin-page spec (2026-07-12) as a systemic, pre-existing pattern, not specific to any one diff.

## Capabilities

- **CAP-1**
  - **intent:** A caught exception with a non-empty `str()` displays exactly as it does today.
  - **success:** A test asserts the shared helper returns `str(exc)` unchanged when non-empty — no behavior change for the common case.

- **CAP-2**
  - **intent:** A caught exception with an empty `str()` displays an informative fallback identifying the exception type, instead of a blank error box.
  - **success:** A test constructs an exception whose `str()` is empty and asserts the helper's output is non-empty and contains the exception's class name.

- **CAP-3**
  - **intent:** Every existing `st.error(str(exc))` call site is routed through the shared helper.
  - **success:** `grep -r "st.error(str(exc))" views/` returns zero matches; the full pytest suite still passes. Sites: `admin.py:50,76,128,195`; `intake.py:369,455`; `jobs_list.py:105,124,288,374`.

## Constraints

- The helper lives in `src/jobs/ui_actions.py`, not a new `views/` module — all 3 view files already import CLI-layer helpers from there (`project-context.md`'s "views import CLI-layer helpers directly" convention); no new import surface.
- The fallback only changes rendering for the empty-`str()` case. A non-empty `str(exc)` must pass through unmodified — this is a defensive fallback, not a redesign of error presentation.

## Non-goals

- Changing which exception types are caught, or narrowing any `except Exception`/`except SystemExit` clause — this spec only changes what's displayed once an exception is already caught.
- Adding logging or telemetry for caught exceptions.

## Success signal

- No view in this app can show an empty `st.error()` box for any exception, verified by CAP-2's test plus a manual pass confirming all 10 call sites route through the helper.

## Assumptions

- 6 of the 10 sites catch `SystemExit` raised by this codebase's own CLI-layer helpers, which already embed rich messages (e.g. the atomic-write failure text) — lower real-world risk than the 4 `except Exception` sites in `admin.py` (network/DB/Gemini calls that can raise a bare `OSError`/`HTTPError`). All 10 are hardened uniformly anyway: it's one mechanical fix, and consistency matters more than scoping to the higher-risk subset.
