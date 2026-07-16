---
id: SPEC-cv-supersede-dialog-dismiss-fix
companions: ["../../project-context.md"]
sources: ["../../implementation-artifacts/deferred-work.md"]
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# CV supersede-profile dialog dismiss fix

## Why

A pain to solve, flagged by both reviewers of `spec-admin-destructive-safety.md`. `views/admin.py`'s `_confirm_supersede_dialog` can't be dismissed via the modal's native X/backdrop/ESC — only its in-dialog "Cancel" button clears `st.session_state["pending_cv_profile"]`/`"cv_registration_in_progress"`. Dismissing via X visually closes the modal, but since the calling script re-invokes the dialog on the next rerun whenever `pending_cv_profile` is still set, the modal reopens. The original review called this unfixable without a state-machine redesign, since `st.dialog` had no documented dismissal callback at the time. That's no longer true: the actually-installed `streamlit==1.58.0` has an `on_dismiss` parameter accepting a callable, run as a callback (with `session_state` access) specifically when the user dismisses via X/backdrop/ESC.

## Capabilities

- **CAP-1**
  - **intent:** Dismissing the CV-upload supersede-profile dialog via X/backdrop/ESC clears the same pending state the in-dialog Cancel button already clears, so the dialog does not reopen on the next rerun.
  - **success:** A shared cleanup helper is extracted and both (a) the Cancel button and (b) the dialog's `on_dismiss` parameter call it — verified by a direct unit test on the helper (seed `session_state` with `pending_cv_profile` set and `cv_registration_in_progress=True`, call the helper, assert both are cleared) plus a check that `on_dismiss` is wired to that exact helper, not a separate/diverged implementation.

## Constraints

- Extract the Cancel button's existing cleanup (pop `pending_cv_profile`, set `cv_registration_in_progress=False`) into one shared helper function — both Cancel and `on_dismiss` call it, no duplicated logic.
- Only `_confirm_supersede_dialog` changes. `_confirm_refresh_dialog` (sponsor-register refresh) is untouched — it's invoked directly from a button click, not gated on persisted state, so it has no equivalent bug.
- Cancel's existing `st.rerun()` call stays Cancel-specific — `on_dismiss` already triggers its own rerun per Streamlit's own dismiss-handling, so only the state-clearing logic is shared, not the rerun call.

## Non-goals

- No end-to-end/browser-level test of the actual X/backdrop/ESC click — `AppTest`'s public API has no hook for simulating a dialog dismissal event (verified: no `dismiss()`/close method exists). Coverage is at the shared-helper unit level plus confirming the wiring, not a full interaction simulation.
- No broader state-machine redesign of the CV-upload flow — this is a narrow fix using the now-available `on_dismiss` parameter, not the bigger rework the original spec assumed was necessary.

## Success signal

A user who dismisses the "replace current profile" dialog via X, clicking outside it, or pressing ESC sees it stay closed on the next rerun — the same outcome clicking "Cancel" already produces.
