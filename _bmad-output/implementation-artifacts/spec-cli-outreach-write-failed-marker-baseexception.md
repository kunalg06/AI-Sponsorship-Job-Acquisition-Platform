---
title: "Widen the CLI's outreach write-failure marker catch to BaseException"
type: 'bugfix'
created: '2026-07-27'
status: 'in-review'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
baseline_revision: '02ee0ca62a21ea4d5dca1c6bc8e0e96d3e039e61'
---

<intent-contract>

## Intent

**Problem:** `jobs/cli.py`'s `_draft_and_store_outreach` (lines 938-944) has the identical narrow-catch bug the Streamlit twin (`jobs/ui_actions.py`'s `draft_and_save_outreach`) was just fixed for: `except Exception as mark_exc:` around the best-effort `mark_outreach_write_failed(conn, message_id)` call. A non-`Exception` `BaseException` raised while marking a write-failure would propagate and replace the more informative `SystemExit` this code is about to raise (open deferred-work item, `_bmad-output/implementation-artifacts/deferred-work.md`, sourced from `spec-outreach-write-failed-marker-baseexception.md`'s review). The same review also found that a raw `{mark_exc}` f-string interpolation in the print message is itself unsafe if `mark_exc`'s own `__str__` raises — the CLI version has this identical latent gap (line 944).

**Approach:** Widen `except Exception as mark_exc:` to `except BaseException as mark_exc:`, and make the print message resilient to a `mark_exc` whose `str()` itself raises, via a small local, module-private helper in `cli.py` (mirroring `docx_tailor.py`'s existing precedent of a local, non-shared helper to avoid a circular import — `jobs/ui_actions.py` imports from `jobs/cli.py`, not the reverse, so `cli.py` cannot import `ui_actions.py`'s `_str_or_empty`).

## Boundaries & Constraints

**Always:** Preserve the existing best-effort semantics exactly — the operator-facing print still fires, and the original `SystemExit` (with the drafted-text recovery instructions) still always raises. Keep every currently-passing test in `tests/test_cli.py` (or wherever `_draft_and_store_outreach` is tested) passing unchanged.

**Block If:** Nothing here requires a human decision — this is a direct, already-reviewed-and-merged mirror of the fix just applied to the Streamlit twin.

**Never:** Do not import from `jobs/ui_actions.py` into `jobs/cli.py` (backwards relative to this codebase's established CLI→UI layering direction). Do not change `mark_outreach_write_failed` itself, the surrounding `SystemExit` message, or any other except clause in this file.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| `mark_outreach_write_failed` raises non-`Exception` `BaseException` | e.g. `SystemExit` raised from inside the marker call | Print still fires; the original write-failure `SystemExit` still raises and reaches the caller | Caught by widened `except BaseException` |
| Marker exception's `__str__` itself raises or is empty | e.g. bare `KeyboardInterrupt()` | Print names the exception type instead of crashing or printing a bare trailing colon | Local safe-string helper, mirrors `ui_actions._str_or_empty` |
| `mark_outreach_write_failed` raises ordinary `Exception` (pre-existing covered case) | e.g. `sqlite3.OperationalError` | Print fires; original `SystemExit` still raises, unchanged | Still caught (subset of `BaseException`) |

</intent-contract>

## Code Map

- `src/jobs/cli.py` -- `_draft_and_store_outreach` (lines 889-949); the `except Exception as mark_exc:` clause at line 940 and the `print(f"  (also failed ... {mark_exc})")` at line 944 both change. A new small module-private helper (e.g. `_str_or_empty`) is added near the top-level helpers in this file.
- `src/jobs/ui_actions.py` -- reference implementation of the identical fix (`_str_or_empty`, and `draft_and_save_outreach`'s equivalent except clause) already merged; mirror its shape, don't import it.
- `tests/test_jobs_cli.py` -- `test_cmd_outreach_write_failure_survives_the_write_failure_marker_itself_failing` (line 1215) already covers the ordinary-`Exception`-marker case (`sqlite3.OperationalError`) via the real `outreach` CLI command through `_run([...])`; add a sibling test for the non-`Exception` `BaseException` case using the same pattern.

## Tasks & Acceptance

**Execution:**
- [x] `src/jobs/cli.py` -- add a small module-private `_str_or_empty(exc: BaseException) -> str` helper (mirrors `jobs.ui_actions._str_or_empty`'s implementation exactly: `try: return str(exc).strip() except BaseException: return ""`).
- [x] `src/jobs/cli.py` -- change `_draft_and_store_outreach`'s `except Exception as mark_exc:` to `except BaseException as mark_exc:`, and change the print to use `_str_or_empty(mark_exc) or type(mark_exc).__name__` instead of raw `{mark_exc}` interpolation.
- [x] `tests/test_jobs_cli.py` -- add a test sibling to `test_cmd_outreach_write_failure_survives_the_write_failure_marker_itself_failing` (line 1215) where `mark_outreach_write_failed` raises a non-`Exception` `BaseException` (e.g. `KeyboardInterrupt`) instead of `sqlite3.OperationalError`, asserting the original write-failure `SystemExit` (containing the recoverable drafted text) still propagates and is not replaced.

**Acceptance Criteria:**
- Given `_atomic_write_text` raises `OSError` and `mark_outreach_write_failed` then raises a non-`Exception` `BaseException`, when `_draft_and_store_outreach` is called, then the exception that propagates is the original write-failure `SystemExit` (naming the message id/channel and containing the drafted text), not the marker's exception.
- Given `mark_outreach_write_failed` raises an exception whose `str()` is empty (e.g. bare `KeyboardInterrupt()`), when the failure is printed, then the printed text names the exception's type instead of ending in a bare, uninformative trailing colon.
- Given the existing write-failure test(s) for this function, when re-run after this change, then behavior is unchanged.

## Verification

**Commands:**
- `uv run pytest tests/test_jobs_cli.py -q` -- expected: all tests pass, including the new one.
- `uv run pytest -q` -- expected: full suite passes, no regressions elsewhere.

## Spec Change Log

(none — no bad_spec loopback occurred in this run)

## Review Triage Log

### 2026-07-27 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 3 (medium 1, low 2)
- defer: 2 (medium 2)
- reject: 5
- addressed_findings:
  - `[medium]` `[patch]` The new test only used `KeyboardInterrupt`, whose `str()` returns `""` without raising — `_str_or_empty`'s own inner `except BaseException: return ""` guard (for a `str()` that itself raises) was never exercised. Added `test_cmd_outreach_write_failure_survives_a_marker_exception_whose_str_itself_raises`.
  - `[low]` `[patch]` No test asserted on the actual printed diagnostic text, only that the right `SystemExit` fired. Added `capsys` assertions to both the `KeyboardInterrupt` test and the new str()-raises test.
  - `[low]` `[patch]` The comment above the except clause didn't explain why the catch widened to `BaseException`. Expanded it, mirroring the equivalent comment already merged in `jobs/ui_actions.py`.

Rejected: swallowing a genuine `KeyboardInterrupt`/`SystemExit`/`GeneratorExit` instead of propagating — same deliberate, spec-mandated, already-accepted-as-low-likelihood tradeoff as both prior iterations in this series. `_str_or_empty`'s own inner `except BaseException` being uncommented — intentional design, exact mirror of the already-reviewed-and-merged `ui_actions.py` helper. Bare `type(mark_exc).__name__` being unqualified — matches this codebase's existing `error_display_text` fallback convention elsewhere. Synthetic `KeyboardInterrupt` test scenario — deliberately testing the general `BaseException` contract, same precedent as the prior two iterations. Narrow-vs-broad except-clause "inconsistency" between the primary and marker branches — intentional: the primary catch targets `_atomic_write_text`'s specific known failure modes, the marker catch is a must-never-fail safety net.

Deferred to ledger: the primary `except (OSError, ValueError) as exc:` branch's `SystemExit` message still interpolates `{exc}` raw — the identical unprotected-`__str__` risk this fix just closed for `mark_exc`, but touching that except clause is out of scope per this spec's frozen `Never` boundary, and the same asymmetry already exists unmodified in the just-merged `ui_actions.py` twin. The `print(...)` call itself is unguarded against something like a `UnicodeEncodeError` on a narrow console codepage — a pre-existing pattern across every `print()` in this function, not introduced by this diff.
