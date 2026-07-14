---
title: 'Admin page destructive-action safety guards'
type: 'feature'
created: '2026-07-14'
status: 'done'
review_loop_iteration: 0
baseline_commit: '6e010bfe36afeb842128d325cb0dc0415edbcca9'
context: ['{project-root}/_bmad-output/specs/spec-admin-destructive-safety/SPEC.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Admin page's two mutating actions — sponsor-register refresh (whole-table wipe+reload) and CV-upload profile registration (insert-only) — have no confirmation, no concurrency guard, and no duplicate/no-op detection, unlike the rest of this codebase's single-row mutations and the MCP layer's connection handling.

**Approach:** Add a `PRAGMA busy_timeout` to the register DB connection, a no-op message when a refresh re-fetches the same snapshot, an `st.dialog` confirmation before the destructive refresh, an in-flight/duplicate-file guard on CV registration, and an `st.dialog` confirmation before a new CV supersedes the existing latest profile.

## Boundaries & Constraints

**Always:** Reuse the exact `PRAGMA busy_timeout = 5000` value/style already used in `mcp_server/tools.py`. Use `st.dialog` (Streamlit 1.58.0 is pinned, `st.dialog` available since 1.31) for both confirmations — no custom modal. Keep all new UI state in `st.session_state`, never `st.cache_data`/`st.cache_resource` (project convention). CV extraction (the Gemini call) still runs once per legitimate submission; confirmation gates the `insert_profile` call, not the extraction.

**Ask First:** None expected — scope is fully bounded by the approved SPEC.md.

**Never:** Touch `st.error(str(exc))` call sites, add atomic-write handling, change `register.cli.DEFAULT_SOURCE`, add auth, or add profile delete/rollback — all explicit non-goals in SPEC.md.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First-ever ingest | `sponsors` table empty | `get_current_source_updated` returns `None`; post-ingest message is the normal success message | N/A |
| Re-ingest, same source | table has rows with `source_updated=X`; new ingest also resolves to `X` | Admin page shows an "already up to date" info message instead of success | N/A |
| Re-ingest, newer source | table has `source_updated=X`; new ingest resolves to `Y != X` | Normal success message | N/A |
| Concurrent register writer | a second connection holds a write lock during `replace_all` | `busy_timeout` makes the second connect wait up to 5s instead of erroring immediately | `sqlite3.OperationalError` still raised (existing `try/except` in admin.py) if the lock outlives the timeout |
| Double-submit same CV file | "Extract & Register Profile" clicked again for the same `uploaded_file.file_id` after a prior success | No second profile row, no second Gemini call; button short-circuits with an info message | N/A |
| CV upload, profile exists | `get_latest_profile` returns an existing row | Confirmation dialog shows current vs. candidate profile before `insert_profile` runs | N/A |
| CV upload, no profile yet | `get_latest_profile` returns `None` | Profile inserted directly, no dialog (nothing to supersede) | N/A |

</frozen-after-approval>

## Code Map

- `src/register/db.py` -- `connect()` needs `PRAGMA busy_timeout = 5000`; add `get_current_source_updated()` helper
- `views/admin.py` -- both button flows live here; needs the two `st.dialog` confirmations and the CV in-flight/duplicate guard
- `tests/test_ingest.py` -- existing home for `register.db`/`register.ingest` tests; add coverage for the two new `db.py` behaviors
- `_bmad-output/implementation-artifacts/deferred-work.md` -- mark the 5 source entries done once shipped

## Tasks & Acceptance

**Execution:**
- [x] `src/register/db.py` -- add `conn.execute("PRAGMA busy_timeout = 5000")` in `connect()` right after opening the connection, and add `get_current_source_updated(conn) -> str | None` (`SELECT source_updated FROM sponsors LIMIT 1`, `None` if empty) -- gives every register-DB caller lock-wait behavior and lets the UI detect a no-op refresh
- [x] `views/admin.py` -- wrap "Refresh sponsor register now" behind an `st.dialog`-decorated confirm function; capture `previous_source_updated` *inside* that dialog's confirm handler, immediately before calling `ingest()` (not at page-load time -- see Spec Change Log); after a successful ingest, show `st.info("already up to date …")` when `summary["source_updated"] == previous_source_updated` (both non-empty), else the existing `st.success(...)` -- closes CAP-1, CAP-3
- [x] `views/admin.py` -- add `st.session_state["cv_registration_in_progress"]` and `st.session_state["last_registered_cv_file_id"]`; disable the "Extract & Register Profile" button (and short-circuit with an info message) when the current `uploaded_file.file_id` matches the last-registered one -- closes CAP-4
- [x] `views/admin.py` -- after `extract_profile` succeeds, if `latest_profile` (already fetched at page load) is not `None`, gate `insert_profile` behind an `st.dialog` showing the current profile's name/seniority vs. the candidate's, only inserting on explicit confirm; if `latest_profile` is `None`, insert directly -- closes CAP-5
- [x] `tests/test_ingest.py` -- add `test_connect_sets_busy_timeout_pragma`, `test_get_current_source_updated_returns_none_for_empty_table`, `test_get_current_source_updated_returns_value_after_ingest`
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- mark the 5 corresponding entries `status: done` with resolution evidence (files touched, test result)

**Acceptance Criteria:**
- Given the Admin page with an existing register, when "Refresh sponsor register now" is clicked, then a confirmation dialog appears before any DB mutation occurs.
- Given the operator confirms and the fetched `source_updated` matches what was already loaded, when ingest completes, then the page shows the "already up to date" message rather than generic success.
- Given a profile was already registered from an uploaded file, when the same file is submitted again without re-uploading, then no second profile row is inserted and no second Gemini call is made.
- Given at least one profile exists, when a new CV is extracted, then a confirmation dialog shows the current latest profile before the new one is inserted.
- Given no profile exists yet, when a CV is uploaded and extracted, then the profile is inserted without a confirmation dialog.

## Spec Change Log

- Implementation-time refinement (not a scope/intent change): the task list originally said to capture `previous_source_updated` alongside the page-load-time `sponsor_count` read. Implemented differently -- captured inside the confirm dialog's click handler, immediately before `ingest()` runs. Reason: after a successful refresh, `st.rerun()` re-executes the whole script top-to-bottom, so a page-load-time capture would already reflect the *new* post-ingest state by the time the no-op comparison ran, making every refresh look like a no-op. Capturing at click-time, pre-mutation, avoids that bug. CAP-1's observable behavior is unchanged.
- Round-1 review (Blind Hunter + Edge Case Hunter, 2026-07-14) surfaced 4 real bugs, auto-fixed as `patch` (no spec/intent change, all within CAP-1..5 as already scoped):
  1. The CV-upload idempotency guard (CAP-4) only fed `already_registered`/`cv_registration_in_progress` into the button's `disabled=` kwarg, which is a rendering hint for the *next* frame -- it doesn't retroactively invalidate a click event already in flight (a fast double-click racing the disabled state back to the browser). Fixed by re-checking both flags explicitly inside `if register_clicked:` itself.
  2. `_register_pending_profile()`'s `insert_profile()` call had no `try/except` (unlike the original pre-diff code) -- a DB failure (locked, disk full) would crash the script AND leave `cv_registration_in_progress=True` stuck forever, permanently disabling the button. Fixed by wrapping it and resetting the flag on failure.
  3. `was_noop`'s comparison (`previous_source_updated and summary["source_updated"] and previous_source_updated == summary["source_updated"]`) mixed `None` (from a fresh `ingest()` call on an unparseable source) with `""` (from a DB round-trip of the same case, since `register.ingest.build_records` writes `source_updated or ""`) -- `None != ""` meant an identical unparseable-date refresh would never register as a no-op. Fixed by extracting the comparison into `register.db.is_noop_refresh()`, which normalizes both sides before comparing, and added 4 unit tests. This also addressed a second finding (untestable inline logic) by giving it a home with its own tests.
  4. The `st.spinner("Extracting profile from your CV...")` wrapper present in the original pre-diff code was accidentally dropped during the rewrite -- restored around the `extract_profile()` call.
  Also applied one cosmetic fix: `_confirm_supersede_dialog`'s `current` parameter was typed `object`, tightened to `ResumeProfile` (the actual type passed).
  4 findings judged real but not one-line-fixable without a design tradeoff were logged to `deferred-work.md` instead of patched: `busy_timeout` value not measured against the actual 142k-row reload duration; no Streamlit version floor pinned despite the new `st.dialog`/`file_id` dependency (matches this project's pre-existing unbounded-deps convention); the CV-supersede dialog can't be dismissed via native X (only its in-dialog Cancel button works -- `st.dialog` has no dismiss callback); and the CV idempotency guard's `file_id` key can be bypassed by re-selecting the identical file via the OS picker rather than re-clicking the button on the file already held in the widget.
  2 findings rejected as false positives: the no-op check running after the network fetch/DB write (this is by design -- CAP-1 was scoped as "detect and surface," not "skip the work," per the spec's own Constraints/Non-goals) and the register-refresh dialog's error path staying open without an auto-rerun while Cancel explicitly reruns (intentional -- lets the user see the error and retry/cancel from the same dialog, rather than the success path's rerun which needs to refresh the page's displayed state).

## Suggested Review Order

**Register-refresh safety (CAP-1, CAP-2, CAP-3)**

- Entry point: destructive refresh now gated behind a confirm dialog, with the pre-mutation snapshot captured inside the click handler (not at page-load, which would already reflect post-ingest state).
  [`admin.py:54`](../../views/admin.py#L54)

- No-op detection extracted to a small, independently testable function instead of an inline closure comparison.
  [`register/db.py:147`](../../src/register/db.py#L147)

- Display branches on `is_noop_refresh(...)` instead of a stashed boolean, so the comparison logic lives in one tested place.
  [`admin.py:90`](../../views/admin.py#L90)

- Concurrency guard: every register-DB connection now waits on a lock instead of failing immediately, matching the existing `mcp_server/tools.py` convention.
  [`register/db.py:70`](../../src/register/db.py#L70)

**CV-upload safety (CAP-4, CAP-5)**

- The guard flags are re-checked here, not just fed into the button's `disabled=` kwarg -- closes the double-click race a review round caught (disabled is a rendering hint, not a gate on an already-in-flight click).
  [`admin.py:180`](../../views/admin.py#L180)

- Extraction (the billed Gemini call) happens once per legitimate submission; its result is stashed, not the DB write itself.
  [`admin.py:192`](../../views/admin.py#L192)

- Confirmation gate: only opens when an existing profile would actually be superseded; skipped entirely on a first-ever upload.
  [`admin.py:207`](../../views/admin.py#L207)

- `insert_profile` is now wrapped in `try/except` -- a DB failure here used to crash the script and leave the button permanently disabled.
  [`admin.py:121`](../../views/admin.py#L121)

- Same concurrency guard extended to the profile DB for consistency with the register-DB path above.
  [`resume/db.py:44`](../../src/resume/db.py#L44)

**Tests**

- New DB-layer coverage: busy_timeout, no-op detection (including the None-vs-empty-string edge case a review round caught), source-updated tracking.
  [`test_ingest.py:130`](../../tests/test_ingest.py#L130)

## Design Notes

`st.dialog` functions render as a modal when called; the calling code triggers them from inside a button's `if` block. Extraction (the Gemini call) happens *before* opening the CV-supersede dialog and its result is stashed in `st.session_state`, so the dialog's own reruns (while open) never re-extract — only the final confirm click performs `insert_profile`. This keeps the Gemini call count at exactly one per legitimate submission while still gating the actual data mutation behind confirmation.

## Verification

**Commands:**
- `python -m pytest tests/test_ingest.py -v` -- ran, 12/12 passed (9 pre-existing + 3 new: `test_connect_sets_busy_timeout_pragma`, `test_get_current_source_updated_returns_none_for_empty_table`, `test_get_current_source_updated_returns_value_after_ingest`)
- `python -m pytest -v` (via `--ignore=tests/test_mcp_server.py`) -- 166/166 passed, no regressions. The ignored module fails to import (`ModuleNotFoundError: No module named 'mcp'`) only because this session's fallback interpreter (plain system `python`, not the project's `uv`-managed `.venv`) lacks that optional dependency -- pre-existing environment gap, unrelated to this change, doesn't touch anything this spec modified.

**Manual checks -- done live via browser (Streamlit app run with `PYTHONPATH=src python -m streamlit run app.py`):**
- CAP-3 confirmed working end-to-end: clicking "Refresh sponsor register now" opens the confirm dialog with no DB mutation yet; "Cancel" closes it cleanly with the sponsor count unchanged (142235); "Yes, refresh now" runs the real ingest path.
- CAP-1/CAP-2 (no-op detection, busy_timeout): the live gov.uk fetch itself failed in this session with `SSL: CERTIFICATE_VERIFY_FAILED` -- a CA-trust gap specific to the fallback system Python interpreter used in this session (not the project's normal `uv`-managed environment, which has this configured correctly), unrelated to this diff. The failure exercised the dialog's `except`/`st.error` path correctly (error shown inline inside the still-open dialog, no partial mutation, sponsor count unchanged) but did not reach the no-op-message branch. That branch's logic is covered by `test_get_current_source_updated_returns_value_after_ingest` plus code review; recommend the user re-verify live once running via the project's normal `uv run streamlit run app.py`.
- CAP-4/CAP-5 (CV-upload guards): **not** exercised live in this session -- doing so would insert a real row into the user's actual `data/profile.db` (currently holding a real registered profile, "Kunal Gaikwad — senior") and burn a real Gemini API call against the user's own key. Verified via code review instead: `_confirm_supersede_dialog` reuses the exact same `st.dialog` confirm/cancel mechanism already proven live for CAP-3. Recommend the user click through this path themselves (or greenlight a throwaway `.txt` CV) to confirm.
