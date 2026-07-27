---
title: 'Widen `mark_outreach_write_failed`'s recovery catch to `BaseException`'
type: 'bugfix'
created: '2026-07-27'
status: 'in-review'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
baseline_revision: 'aa5dd293512676ad169b7e80bc0647173f3e790d'
---

<intent-contract>

## Intent

**Problem:** `draft_and_save_outreach`'s best-effort recovery block (`src/jobs/ui_actions.py:177-179`) calls `mark_outreach_write_failed(jobs_conn, message_id)` inside `try: ... except Exception as mark_exc:`. If marking the write-failure itself raises a non-`Exception` `BaseException` (e.g. `SystemExit`, `KeyboardInterrupt`), that exception propagates and replaces the more informative `SystemExit` the surrounding code is about to raise — the exact "second failure must not replace the more informative error" bug the existing comment already says this catch exists to prevent, just with a narrower net than the failure mode requires (open deferred-work item, `_bmad-output/implementation-artifacts/deferred-work.md`, sourced from `spec-error-display-str-or-empty-baseexception.md`'s review).

**Approach:** Widen `except Exception as mark_exc:` to `except BaseException as mark_exc:`, mirroring the identical fix `_str_or_empty` just received in the same module for the same reason.

## Boundaries & Constraints

**Always:** Preserve the existing best-effort semantics exactly — the stderr warning still prints, and the original `SystemExit` below it still always raises. Keep every currently-passing test in `tests/test_ui_actions.py` passing unchanged.

**Block If:** Nothing here requires a human decision — this is a single-clause widen with no ambiguity, directly mirroring an already-reviewed and merged precedent in the same file.

**Never:** Do not change `mark_outreach_write_failed` itself (in `jobs/outreach_db.py`), the surrounding `SystemExit` message, or any other except clause in this file — out of scope for this narrow hardening fix.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| `mark_outreach_write_failed` raises non-`Exception` `BaseException` | e.g. `SystemExit` raised from inside the marker call | Warning prints to stderr; the original write-failure `SystemExit` still raises and reaches the caller | Caught by widened `except BaseException` |
| `mark_outreach_write_failed` raises ordinary `Exception` (pre-existing covered case) | e.g. `sqlite3.OperationalError` | Warning prints to stderr; original `SystemExit` still raises, unchanged | Still caught (subset of `BaseException`) |
| `mark_outreach_write_failed` succeeds | Normal DB update | No warning printed; original `SystemExit` still raises as before | No error expected |

</intent-contract>

## Code Map

- `src/jobs/ui_actions.py` -- `draft_and_save_outreach`'s recovery block (lines 177-186) is the sole target; the `except Exception as mark_exc:` clause at line 179 is what changes.
- `tests/test_ui_actions.py` -- existing `draft_and_save_outreach` write-failure tests cover the `_atomic_write_text` failure path; add one new test for a `BaseException`-raising `mark_outreach_write_failed`.

## Tasks & Acceptance

**Execution:**
- [x] `src/jobs/ui_actions.py` -- change `draft_and_save_outreach`'s `except Exception as mark_exc:` to `except BaseException as mark_exc:` -- closes the gap where a non-`Exception` `BaseException` from the write-failure marker replaces the more informative `SystemExit` it's meant to protect.
- [x] `tests/test_ui_actions.py` -- add a test that makes `mark_outreach_write_failed` raise a non-`Exception` `BaseException` (e.g. `SystemExit`) when the outreach-text write already failed, asserting the original write-failure `SystemExit` (naming the message id/channel/recoverable text) is still what propagates, not the marker's exception -- proves the fix.

**Acceptance Criteria:**
- Given `_atomic_write_text` raises `OSError` and `mark_outreach_write_failed` then raises `SystemExit`, when `draft_and_save_outreach` is called, then the exception that propagates to the caller is the original write-failure `SystemExit` (containing the recoverable message text), not the marker's `SystemExit`.
- Given the existing `test_draft_and_save_outreach_write_failure_after_db_commit_raises_error_containing_the_drafted_text` test (where the real, unmocked `mark_outreach_write_failed` succeeds), when re-run after this change, then behavior is unchanged.

## Verification

**Commands:**
- `uv run pytest tests/test_ui_actions.py -q` -- expected: all tests pass, including the new one.
- `uv run pytest -q` -- expected: full suite passes, no regressions elsewhere.

## Spec Change Log

(none — no bad_spec loopback occurred in this run)

## Review Triage Log

### 2026-07-27 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 4 (medium 1, low 3)
- defer: 1 (medium 1)
- reject: 6
- addressed_findings:
  - `[medium]` `[patch]` The warning `print` still interpolated `{mark_exc}` directly — if `str(mark_exc)` itself raised, the except block would crash and the informative `SystemExit` below would never fire, defeating the whole point of this fix. Switched to `_str_or_empty(mark_exc) or type(mark_exc).__name__`.
  - `[low]` `[patch]` The new test never verified the stderr warning was actually printed. Added a `capsys` assertion.
  - `[low]` `[patch]` The test only covered one `BaseException` subtype (`SystemExit`) — a regression narrowing the catch to `except (Exception, SystemExit):` would still pass it. Added a second test using `KeyboardInterrupt` (which also has an empty `str()`, exercising the new type-name fallback too).
  - `[low]` `[patch]` The comment above the except clause didn't disclose the widened blast radius or explain the `_str_or_empty` usage. Expanded it.

Rejected: catching Streamlit's own `StopException`/`RerunException` — verified inapplicable, since `mark_outreach_write_failed` (`src/jobs/outreach_db.py`) imports only `sqlite3`/`datetime`/`typing`, no Streamlit dependency anywhere in its call chain, so it cannot raise those types. Swallowing a genuine `KeyboardInterrupt`/`GeneratorExit` instead of propagating — same deliberate, spec-mandated, already-accepted-as-low-likelihood tradeoff as the sibling `_str_or_empty` fix. A falsy-message `SystemExit` (e.g. `SystemExit()`) making the diagnostic print less informative — out of scope for a best-effort log line, not a crash. Editing `mark_outreach_write_failed`'s own docstring in `outreach_db.py` — explicitly out of scope per this spec's frozen `Never` clause. `draft_and_save_outreach`'s docstring not documenting this behavior — marginal, sufficiently covered by the now-expanded inline comment. The new tests' call-signature duplication with the adjacent pre-existing test — pre-existing style in this file, not this narrow diff's to refactor.

Deferred to ledger: `jobs/cli.py`'s `_draft_and_store_outreach` has the identical unfixed `except Exception as mark_exc:` pattern around the same `mark_outreach_write_failed` call — a different file, out of this story's scope.
