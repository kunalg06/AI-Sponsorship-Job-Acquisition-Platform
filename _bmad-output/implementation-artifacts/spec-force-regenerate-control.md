---
title: 'Force-regenerate control'
type: 'bugfix'
created: '2026-07-15'
status: 'done'
review_loop_iteration: 0
baseline_commit: '5818f2adee6d0eed2884b7612e57ed7fa0784d81'
context: ['{project-root}/_bmad-output/specs/spec-force-regenerate-control/SPEC.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The tailor button in `views/intake.py`/`views/jobs_list.py` labels itself "Regenerate tailored resume & cover letter" once a docx pair already exists, but always calls `generate_tailored_docx_for_job` with the default `force=False` — clicking it is silently a no-op cache hit, not a regeneration.

**Approach:** Add a `force: bool = False` parameter to `generate_tailored_docx_for_job` (`src/jobs/ui_actions.py`), threaded through to `_tailor_docx_for_job`'s own `force` param. Both view call sites pass `force=already_generated` — the same boolean each already computes to pick the button's label.

## Boundaries & Constraints

**Always:** `force=already_generated` at both call sites — no new session-state, checkbox, or dialog. Default `force=False` on `generate_tailored_docx_for_job` preserves every other caller's behavior unchanged.

**Ask First:** None expected — scope is fully bounded by the approved SPEC.md kernel.

**Never:** Add a confirmation dialog or any new UI element. Touch `jobs/cli.py`'s plain-text `tailor` command (already always-fresh, unrelated cache path).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cache valid, "Regenerate" clicked | `already_generated=True` | `force=True` passed through; cache check bypassed; fresh LLM call + docx rewrite | N/A |
| No cache yet, "Generate" clicked | `already_generated=False` | `force=False` passed through; unchanged from current behavior | N/A |
| Cache valid, but `_require_raw_resume_text`/job lookup fails | Any `force` value | Same `SystemExit` behavior as today — force only affects the cache-check step, not upstream validation | Existing `except SystemExit as exc: st.error(error_display_text(exc))` unchanged |

</frozen-after-approval>

## Code Map

- `src/jobs/ui_actions.py` -- `generate_tailored_docx_for_job` (line 49): add `force: bool = False` parameter, thread through to `_tailor_docx_for_job`
- `views/intake.py` -- line 367 call site: pass `force=already_generated`
- `views/jobs_list.py` -- line 286 call site: pass `force=already_generated`
- `tests/test_ui_actions.py` -- add coverage for `force=True` bypassing the cache, plus 2 `AppTest`-based view-wiring tests added during review
- `tests/test_views_error_display.py` -- strengthened during review to also assert `force=False` on the existing no-cache-seeded tests

## Tasks & Acceptance

**Execution:**
- [x] `src/jobs/ui_actions.py` -- `generate_tailored_docx_for_job(job_id, jobs_db, profile_db, force: bool = False)`, replace the hardcoded `force=False` at line 69 with the new parameter
- [x] `views/intake.py` -- line 367: `generate_tailored_docx_for_job(saved_job_id, JOBS_DB, PROFILE_DB, force=already_generated)`
- [x] `views/jobs_list.py` -- line 286: `generate_tailored_docx_for_job(job["id"], JOBS_DB, PROFILE_DB, force=already_generated)`
- [x] `tests/test_ui_actions.py` -- add `test_generate_tailored_docx_for_job_with_force_true_bypasses_cache_and_calls_llm_again`: seed a job with an existing valid docx cache (matching hash + files present), call with `force=True`, assert the LLM-calling path actually runs (not short-circuited) and the docx content actually changes
- [x] `tests/test_ui_actions.py` -- add `test_generate_tailored_docx_for_job_with_force_false_default_still_uses_cache`: same seeded state, call with default `force`, assert the cache hit path is taken (no LLM call, docx content unchanged) — pins today's existing default behavior
- [x] `tests/test_ui_actions.py` -- **added during review**: `test_jobs_list_regenerate_button_passes_force_true_when_docx_cache_already_exists` and `test_intake_regenerate_button_passes_force_true_when_docx_cache_already_exists` -- drive the real views via `AppTest` with a pre-seeded docx cache, click the actual "Regenerate" button, assert `force=True` reaches the mock (the direct-call tests above couldn't catch a regression at the view call sites themselves)
- [x] `tests/test_views_error_display.py` -- **strengthened during review**: both existing intake/jobs_list tests now also assert `force=False` was passed, symmetric coverage for the no-cache path

**Acceptance Criteria:**
- Given a job with a valid docx cache, when `generate_tailored_docx_for_job` is called with `force=True`, then the LLM-calling/docx-rewrite path executes again rather than returning the cached result.
- Given a job with a valid docx cache, when `generate_tailored_docx_for_job` is called with no `force` argument (or `force=False`), then behavior is unchanged from before this diff (cache hit, no LLM call).
- Given the "Generate" (first-time) path in either view, when the button is clicked, then behavior is unchanged from before this diff.

## Spec Change Log

<!-- Empty until the first bad_spec loopback. -->

## Verification

**Commands:**
- `python -m pytest tests/test_ui_actions.py -v` -- expect all existing tests plus the 2 new ones to pass
- `python -m pytest --ignore=tests/test_mcp_server.py` -- expect no regressions

**Manual checks (if no CLI):**
- None needed -- pure parameter-threading change with full unit-test coverage on both the `force=True` and default-`force` paths.

## Suggested Review Order

**The fix itself**

- Entry point: `force: bool = False` threaded through to `_tailor_docx_for_job`, replacing the hardcoded `force=False`.
  [`ui_actions.py:49`](../../src/jobs/ui_actions.py#L49)

- Both view call sites pass the exact boolean already driving the button's own label.
  [`jobs_list.py:283`](../../views/jobs_list.py#L283)
  [`intake.py:363`](../../views/intake.py#L363)

**Direct-call tests (the original coverage)**

- Force=True bypasses the cache and the docx content actually changes.
  [`test_ui_actions.py:261`](../../tests/test_ui_actions.py#L261)

- Force=False (default) still hits the cache — pins pre-existing behavior.
  [`test_ui_actions.py:286`](../../tests/test_ui_actions.py#L286)

**View-wiring tests (added during review)**

- The real gap review caught: neither test above could catch a regression at the actual view call sites. These drive the real pages via `AppTest` with a pre-seeded docx cache and assert `force=True` reaches the mock.
  [`test_ui_actions.py:329`](../../tests/test_ui_actions.py#L329)
  [`test_ui_actions.py:348`](../../tests/test_ui_actions.py#L348)

- Symmetric `force=False` assertions added to the pre-existing error-display tests (no-cache path).
  [`test_views_error_display.py:65`](../../tests/test_views_error_display.py#L65)
  [`test_views_error_display.py:90`](../../tests/test_views_error_display.py#L90)
