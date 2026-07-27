---
title: 'Widen `_str_or_empty`'s exception catch to `BaseException`'
type: 'bugfix'
created: '2026-07-27'
status: 'in-review'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
baseline_revision: '6ca389ed44d7603c94b52db816252e3e4674decd'
---

<intent-contract>

## Intent

**Problem:** `_str_or_empty` (`src/jobs/ui_actions.py:34-38`) is the safety-net helper `error_display_text` calls for the top-level exception and every chain link it walks, but it only catches `Exception`. A chain link whose `__str__` raises a non-`Exception` `BaseException` (e.g. `KeyboardInterrupt`, or a `SystemExit` raised from inside a broken `__str__`) propagates straight out of `error_display_text`, crashing the very error-display path that exists to safely render errors to the user (open deferred-work item, `_bmad-output/implementation-artifacts/deferred-work.md`, sourced from `spec-error-display-chained-cause/SPEC.md`'s review).

**Approach:** Widen `_str_or_empty`'s `except Exception:` to `except BaseException:`, matching `error_display_text`'s own already-`BaseException`-typed signature and rationale (most callers pass a caught `SystemExit`, not an `Exception`).

## Boundaries & Constraints

**Always:** Preserve `_str_or_empty`'s existing return contract (a stripped `str`, `""` on any failure) and every currently-passing behavior in `tests/test_ui_actions.py` (empty-str, whitespace-only-str, and Exception-raising-`__str__` cases must keep passing unchanged).

**Block If:** Nothing here requires a human decision — this is a single-clause widen with no ambiguity.

**Never:** Do not change `_next_chain_link`, `error_display_text`'s public signature/behavior, or add logging — out of scope for this narrow hardening fix.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Non-`Exception` `__str__` failure | Exception chain link whose `__str__()` raises `KeyboardInterrupt` | `_str_or_empty` returns `""` instead of propagating | Caught by widened `except BaseException` |
| Existing `Exception`-raising `__str__` | Exception whose `__str__()` raises `ValueError` (pre-existing covered case) | `_str_or_empty` returns `""`, unchanged | Still caught (subset of `BaseException`) |
| Normal exception | `str(exc)` succeeds, e.g. `"disk full"` | `_str_or_empty` returns `"disk full"` | No error expected |

</intent-contract>

## Code Map

- `src/jobs/ui_actions.py` -- `_str_or_empty` (line 34) is the sole target of the fix; `error_display_text` (line 56) and `_next_chain_link` (line 41) are unchanged callers/neighbors for context.
- `tests/test_ui_actions.py` -- existing `error_display_text` test suite (lines 164-348); add one new test alongside `test_error_display_text_survives_a_str_that_itself_raises` (line 195) for the non-`Exception` case.

## Tasks & Acceptance

**Execution:**
- [x] `src/jobs/ui_actions.py` -- change `_str_or_empty`'s `except Exception:` to `except BaseException:` -- closes the gap where a non-`Exception` `BaseException` from a broken `__str__` crashes `error_display_text` instead of degrading to the fallback message.
- [x] `tests/test_ui_actions.py` -- add a test asserting `error_display_text` survives an exception whose `__str__` raises a non-`Exception` `BaseException` (e.g. `KeyboardInterrupt`), returning the `"{type}: (no error message)"` fallback instead of propagating -- proves the fix; mirrors the existing `test_error_display_text_survives_a_str_that_itself_raises` pattern but with a `BaseException`-only exception type that the old `except Exception` clause would have missed.

**Acceptance Criteria:**
- Given an exception whose `__str__()` raises `KeyboardInterrupt`, when `error_display_text(exc)` is called, then it returns `f"{type(exc).__name__}: (no error message)"` instead of letting `KeyboardInterrupt` propagate.
- Given the existing `Exception`-raising-`__str__` test case, when re-run after this change, then behavior is unchanged (still returns the same fallback text).

## Spec Change Log

(none — no bad_spec loopback occurred in this run)

## Review Triage Log

### 2026-07-27 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 5 (medium 2, low 3)
- defer: 1 (low 1)
- reject: 6
- addressed_findings:
  - `[low]` `[patch]` No in-code rationale for the broad `except BaseException:` catch — added a comment on `_str_or_empty` explaining it's deliberate (a chain link's `__str__` can raise anything, and this is the safety net `error_display_text` relies on to never crash while rendering an error).
  - `[medium]` `[patch]` New test only exercised a synthetic `KeyboardInterrupt`-raising `__str__`, not `SystemExit` (this codebase's own real-world `BaseException` convention) — a regression narrowing the catch to `except (Exception, KeyboardInterrupt):` would still pass. Added `test_error_display_text_survives_a_str_that_raises_system_exit`.
  - `[low]` `[patch]` New test duplicated `test_error_display_text_survives_a_str_that_itself_raises` with no cross-reference explaining why both are needed — added a short comment distinguishing the two (Exception-raising `__str__` vs. BaseException-only-raising `__str__`).

Rejected (deliberate, spec-mandated consequences of the frozen `<intent-contract>` Approach, or non-issues; not actionable without reopening the frozen approach): swallowing a genuine `KeyboardInterrupt`/`SystemExit` raised mid-`str(exc)` instead of propagating (already logged as extremely-low-likelihood when this deferred-work item was originally opened); "bare `except BaseException`" being a style anti-pattern (the whole point of the fix); no logging added on swallow (pre-existing codebase convention, not newly introduced); the new test's exact-string-equality assertion vs. a sibling test's looser `in` check (stricter is not a defect); this diff not also touching other still-open deferred-work items (out of this story's scope by design).

Deferred to ledger: `mark_outreach_write_failed`'s sibling `except Exception as mark_exc:` (`ui_actions.py:174`) has the same narrow-catch shape but lives in a different, untouched function — logged to `deferred-work.md` for separate consideration.

## Verification

**Commands:**
- `uv run pytest tests/test_ui_actions.py -q` -- expected: all tests pass, including the new one.
- `uv run pytest -q` -- expected: full suite passes, no regressions elsewhere.
