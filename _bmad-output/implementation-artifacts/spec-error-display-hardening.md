---
title: 'Error-display hardening'
type: 'bugfix'
created: '2026-07-15'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'fc6eb1ab8cde3c8a1c906d4174abfd1892d93b76'
context: ['{project-root}/_bmad-output/specs/spec-error-display-hardening/SPEC.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `st.error(str(exc))` is used identically at 10 call sites across `views/admin.py`, `views/intake.py`, `views/jobs_list.py`. Any exception whose `str()` is empty (some `OSError`/`HTTPError` subclasses) renders a blank error box with no information for the user.

**Approach:** Add a pure helper function to `src/jobs/ui_actions.py` that takes an exception and returns display text — `str(exc)` when non-empty, otherwise a fallback naming the exception's type. Replace `st.error(str(exc))` with `st.error(<helper>(exc))` at all 10 sites.

## Boundaries & Constraints

**Always:** The helper is a plain function returning `str`, not one that calls `st.error` itself — `ui_actions.py` currently has zero Streamlit import/dependency (it's shared, testable orchestration logic that `views/*.py` wraps in `st.error`/`st.success`), and this fix must not break that layering. A non-empty `str(exc)` must pass through byte-identical to today's output.

**Ask First:** None expected — scope is fully bounded by the approved SPEC.md kernel.

**Never:** Change which exception types are caught at any of the 10 sites, add logging/telemetry, or alter error-handling control flow — this is display-only.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normal exception | `exc` with non-empty `str(exc)` | Helper returns `str(exc)` unchanged | N/A |
| Empty-message exception | `exc` where `str(exc) == ""` (e.g. `OSError()` with no args) | Helper returns a non-empty fallback containing `type(exc).__name__` | N/A |
| Existing call sites | Any of the 10 `st.error(str(exc))` sites fires | Renders via the helper instead; behavior for non-empty messages is unchanged from today | N/A |

</frozen-after-approval>

## Code Map

- `src/jobs/ui_actions.py` -- add the new helper function (near the top, module-level, no Streamlit import needed)
- `views/admin.py` -- 4 call sites (lines 50, 76, 128, 195) -- route through the helper
- `views/intake.py` -- 2 call sites (lines 369, 455) -- route through the helper
- `views/jobs_list.py` -- 4 call sites (lines 105, 124, 288, 374) -- route through the helper
- `tests/test_ui_actions.py` -- existing home for `ui_actions` tests -- add coverage for the new helper

## Tasks & Acceptance

**Execution:**
- [x] `src/jobs/ui_actions.py` -- add `error_display_text(exc: Exception) -> str` returning `str(exc)` when non-empty, else `f"{type(exc).__name__}: (no error message)"` -- the one shared mechanism all 10 sites route through
- [x] `views/admin.py` -- import `error_display_text` from `jobs.ui_actions`; replace `st.error(str(exc))` at lines 50, 76, 128, 195 with `st.error(error_display_text(exc))`
- [x] `views/intake.py` -- same import; replace at lines 369, 455
- [x] `views/jobs_list.py` -- same import; replace at lines 105, 124, 288, 374
- [x] `tests/test_ui_actions.py` -- add `test_error_display_text_returns_str_exc_unchanged_when_non_empty` and `test_error_display_text_falls_back_to_type_name_when_str_exc_is_empty`

**Acceptance Criteria:**
- Given an exception with a non-empty `str(exc)`, when `error_display_text` is called, then it returns `str(exc)` unchanged.
- Given an exception with an empty `str(exc)` (e.g. `OSError()`), when `error_display_text` is called, then it returns a non-empty string containing the exception's class name.
- Given the codebase after this change, when grepping `views/` for `st.error(str(exc))`, then zero matches remain.

## Spec Change Log

<!-- Empty until the first bad_spec loopback. -->

## Verification

**Commands:**
- `python -m pytest tests/test_ui_actions.py -v` -- expect all existing tests plus the 2 new ones to pass
- `python -m pytest --ignore=tests/test_mcp_server.py` -- expect no regressions
- `grep -rn "st.error(str(exc))" views/` -- expect no output

**Manual checks (if no CLI):**
- None needed -- pure string-transform logic with full unit-test coverage; the 10 call sites are mechanical replacements with no behavior change for the non-empty case.

## Suggested Review Order

**The helper**

- Entry point: returns `str(exc)` stripped when non-empty, else a type-name fallback; also swallows a `__str__` that itself raises.
  [`ui_actions.py:33`](../../src/jobs/ui_actions.py#L33)

- Typed `BaseException`, not `Exception` — most real callers pass a caught `SystemExit`, which isn't an `Exception` subclass.
  [`ui_actions.py:33`](../../src/jobs/ui_actions.py#L33)

**Call-site wiring (10 sites, 3 files)**

- Admin page has the highest real risk: 4 sites catching bare `Exception` from network/DB/Gemini calls.
  [`admin.py:51`](../../views/admin.py#L51)

- Same pattern repeated 3 more times in this file.
  [`admin.py:77`](../../views/admin.py#L77) · [`admin.py:129`](../../views/admin.py#L129) · [`admin.py:196`](../../views/admin.py#L196)

- Intake page: both sites catch `SystemExit` from tailoring/outreach helpers, already rich messages.
  [`intake.py:369`](../../views/intake.py#L369) · [`intake.py:455`](../../views/intake.py#L455)

- Jobs-list page: same `SystemExit` pattern, 4 sites.
  [`jobs_list.py:105`](../../views/jobs_list.py#L105) · [`jobs_list.py:124`](../../views/jobs_list.py#L124) · [`jobs_list.py:288`](../../views/jobs_list.py#L288) · [`jobs_list.py:374`](../../views/jobs_list.py#L374)

**Tests**

- Covers the two capability-required cases plus three edge cases surfaced by review: whitespace-only, `SystemExit`, and a broken `__str__`.
  [`test_ui_actions.py:147`](../../tests/test_ui_actions.py#L147)
