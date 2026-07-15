---
title: 'Docx and UI-outreach atomic writes'
type: 'feature'
created: '2026-07-14'
status: 'done'
review_loop_iteration: 0
baseline_commit: '9c06934c45dfe710453194b3a1af7e269b61544c'
context: ['{project-root}/_bmad-output/specs/spec-docx-and-ui-outreach-atomic-writes/SPEC.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `docx_tailor.py`'s `.docx` writes have no atomic-replace protection, and `views/ui_actions.py`'s `draft_and_save_outreach` — the UI's primary outreach-drafting path — has the same committed-DB-row-then-unguarded-write risk that `jobs/cli.py`'s CLI path already got fixed for.

**Approach:** Add a local `_atomic_write_bytes` helper inside `docx_tailor.py` (writes via an in-memory `io.BytesIO()` buffer, same temp-then-`os.replace` mechanism as `jobs.cli._atomic_write_text`, kept local to avoid a circular import); route both docx writes through it. In `ui_actions.py`, reuse `jobs.cli._atomic_write_text` directly and wrap the outreach write in `try/except` that raises `SystemExit` embedding the drafted text in the message itself (not printed — a Streamlit user never sees server stdout).

## Boundaries & Constraints

**Always:** `_atomic_write_bytes` lives in `docx_tailor.py`, not imported from `jobs.cli` (circular-import risk: `cli.py` already imports `docx_tailor`). `ui_actions.py`'s fix reuses `jobs.cli._atomic_write_text` verbatim, matching this codebase's "views import CLI-layer helpers directly" convention already used for `DEFAULT_GENERATED_CV_DIR`/`_outreach_message_path`/etc. in the same file. CAP-2's recovery text goes inside the `SystemExit` message (reaches the user via the existing `except SystemExit as exc: st.error(str(exc))` in `views/intake.py`/`views/jobs_list.py`), never `print()`.

**Ask First:** None expected — scope is fully bounded by the approved SPEC.md.

**Never:** Touch `_tailor_docx_for_job`'s `update_tailoring`-after-write ordering, add orphaned-row tracking, touch `jobs/cli.py`'s outreach path further, or add directory-fsync — all explicit non-goals in SPEC.md.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normal docx build | `build_tailored_docx`/`write_plain_docx` run normally | Same output file/content as before, written via the atomic helper | N/A |
| Interrupted docx write (simulated) | `os.replace` raises mid-call | Target path keeps its prior content (or stays absent), never a truncated/corrupt `.docx`; no orphaned `.tmp` remains | Exception propagates uncaught (matches `jobs/cli.py`'s CAP-1/CAP-2 precedent — atomicity only, no new handling here) |
| Normal UI outreach draft | `draft_and_save_outreach` succeeds | `.txt` file written atomically, same content/path as before | N/A |
| UI outreach write fails after DB commit | `_atomic_write_text` raises for the write at `ui_actions.py:99` | `SystemExit` raised: message names the id/channel/char-count, states the text wasn't saved, and includes the full drafted text | Caught by the existing `except SystemExit as exc: st.error(str(exc))` in `views/intake.py`/`views/jobs_list.py` — no code change needed there |

</frozen-after-approval>

## Code Map

- `src/jobs/docx_tailor.py` -- new `_atomic_write_bytes` helper; `build_tailored_docx`/`write_plain_docx` route through it
- `src/jobs/ui_actions.py` -- import `_atomic_write_text` from `jobs.cli`; wrap the outreach write in `try/except`
- `tests/test_docx_tailor.py` -- existing home for docx_tailor tests (imports `build_tailored_docx`, `write_plain_docx` already)
- `tests/test_ui_actions.py` -- **new file** (this module has zero existing test coverage); mirrors `test_jobs_cli.py`'s `outreach_env`-style setup (`RESUME_TEXT`, `_add_profile_version`/`_add_narrative_and_profile`-equivalent helpers, `insert_job`/`JobExtraction`) but calls `draft_and_save_outreach` directly rather than through CLI arg parsing
- `_bmad-output/implementation-artifacts/deferred-work.md` -- mark the 2 corresponding entries `status: done`

## Tasks & Acceptance

**Execution:**
- [x] `src/jobs/docx_tailor.py` -- add `import io`, `import os`, `import uuid`; add `_atomic_write_bytes(path: Path, data: bytes) -> None` mirroring `jobs.cli._atomic_write_text`'s design (pid+uuid tmp naming, fsync, `os.replace`, cleanup-on-failure via `except OSError: tmp.unlink(missing_ok=True); raise`) -- the one shared mechanism both docx sites route through
- [x] `src/jobs/docx_tailor.py` -- `build_tailored_docx` (line 159): replace `document.save(str(out_path))` with save-to-`io.BytesIO()` then `_atomic_write_bytes(out_path, buffer.getvalue())` -- closes CAP-1's first site
- [x] `src/jobs/docx_tailor.py` -- `write_plain_docx` (line 203): same replacement -- closes CAP-1's second site
- [x] `src/jobs/ui_actions.py` -- add `_atomic_write_text` to the existing `from jobs.cli import (...)` block; wrap `path.write_text(draft.message, encoding="utf-8")` (line 99) in `try/except (OSError, ValueError) as exc: raise SystemExit(...)` naming the message id/channel/char-count and embedding `draft.message` in the exception text -- closes CAP-2
- [x] `tests/test_docx_tailor.py` -- added `test_atomic_write_bytes_writes_full_content_and_leaves_no_tmp_file`, `test_atomic_write_bytes_leaves_prior_content_intact_and_cleans_up_tmp_when_replace_fails`, `test_build_tailored_docx_leaves_no_partial_file_when_replace_fails`
- [x] `tests/test_ui_actions.py` -- new file (this module had zero prior test coverage): `ui_outreach_env` fixture (job + profile + narrative, `draft_outreach_message` monkeypatched), a happy-path test, and a failure-path test asserting the `SystemExit` message contains the drafted text
- [x] `_bmad-output/implementation-artifacts/deferred-work.md` -- mark the 2 corresponding entries `status: done` with resolution evidence

**Acceptance Criteria:**
- Given either docx write site, when the underlying `os.replace` call fails, then the target path never contains truncated/corrupt content and no `.tmp` file remains.
- Given both docx sites succeed normally, when their respective callers run, then output content and file paths are unchanged from current behavior.
- Given the UI outreach write fails after `insert_outreach_message` has already committed, when the failure is raised, then the resulting `SystemExit`'s message contains the full drafted text.
- Given the UI outreach write succeeds normally, when `draft_and_save_outreach` runs, then behavior and output are unchanged from current behavior.

## Spec Change Log

<!-- Empty until the first bad_spec loopback. -->

## Design Notes

`_atomic_write_bytes` is a near-duplicate of `jobs.cli._atomic_write_text` (same tmp-naming, same fsync/replace/cleanup shape) but for `bytes` instead of `str` — the duplication is deliberate per the SPEC's Constraints (avoiding a circular import), not an oversight. `document.save()` accepts either a path string or a file-like object; routing through `io.BytesIO()` first is what makes the atomic-replace possible at all, since `Document.save()` itself has no temp-file option.

CAP-2's embedded-recovery-text choice differs from the CLI's `print()`-based fix in the prior spec specifically because Streamlit's `st.error(str(exc))` is the only channel that reaches a browser user — server-side `print()` output is invisible to them.

## Verification

**Commands:**
- `python -m pytest tests/test_docx_tailor.py tests/test_ui_actions.py -v` -- expect all existing tests plus the new ones to pass
- `python -m pytest -v` (via `--ignore=tests/test_mcp_server.py`, same fallback-environment caveat as prior sessions) -- expect no regressions

**Manual checks (if no CLI):**
- None needed -- pure library logic with full unit-test coverage.
