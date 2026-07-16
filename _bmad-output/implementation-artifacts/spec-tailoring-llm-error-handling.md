---
title: 'Friendly error handling for tailoring Gemini calls'
type: 'bugfix'
created: '2026-07-16'
status: 'done'
review_loop_iteration: 0
context: ['{project-root}/_bmad-output/specs/spec-tailoring-llm-error-handling/SPEC.md']
baseline_commit: '76153c30d5cddf0ba81432f54817a79a14a0fe06'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `generate_tailored_application` (`src/jobs/tailor.py`) and `generate_paragraph_edits` (`src/jobs/docx_tailor.py`) call the Gemini API with no error handling. A network/API failure or a malformed-JSON response (pydantic `ValidationError`) propagates as a raw, unhandled exception — both Streamlit views only catch `except SystemExit`, so this currently crashes as a raw traceback instead of this codebase's usual friendly error.

**Approach:** Wrap each function's Gemini call in a try/except that catches the SDK's real failure types — confirmed by inspecting the installed `google-genai` package: `google.genai.errors.APIError` (HTTP-level API errors: auth, rate-limit, 4xx/5xx) and `httpx.HTTPError` (network-level: timeout, connection failure — the SDK's default retry config is "never retry, reraise", per `_api_client.py`'s `retry_args`, so these surface directly) — plus `pydantic.ValidationError` for a malformed response, and re-raise each as `SystemExit(<message naming what failed>)`, matching this codebase's existing `_require_raw_resume_text`-style convention.

## Boundaries & Constraints

**Always:** Preserve each function's `client: Optional[genai.Client] = None` keyword and return type. Success-path behavior is byte-for-byte unchanged. Only `SystemExit` is raised on failure — no new exception class.

**Ask First:** Nothing — the one open design question (exact exception types) is resolved above from the installed SDK source, not a human call.

**Never:** No retry/backoff logic. No changes to `src/jobs/extract.py` or `src/jobs/outreach.py` (separate, out of scope). No changes to `views/intake.py` or `views/jobs_list.py` (they already catch `except SystemExit` at every call site reaching these functions).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | `client.interactions.create` returns valid JSON matching the response schema | Parsed model returned unchanged (current behavior) | N/A |
| API error | `client.interactions.create` raises `genai.errors.APIError` (e.g. 429/500) | No raw traceback | `SystemExit` naming the API error's message |
| Network error | `client.interactions.create` raises `httpx.TimeoutException` or `httpx.ConnectError` | No raw traceback | `SystemExit` naming the network failure |
| Malformed response | `interaction.output_text` is JSON that fails `model_validate_json` | No raw traceback | `SystemExit` naming the validation failure |

</frozen-after-approval>

## Code Map

- `src/jobs/tailor.py` -- `generate_tailored_application` (line 73) needs the try/except; add `genai_errors`/`httpx`/`ValidationError` imports
- `src/jobs/docx_tailor.py` -- `generate_paragraph_edits` (line 132) needs the identical try/except; add same imports
- `tests/test_tailor.py` -- add failure-path tests (API error, network error, malformed JSON) mirroring the existing `MagicMock`-based happy-path tests
- `tests/test_docx_tailor.py` -- same, for `generate_paragraph_edits`

## Tasks & Acceptance

**Execution:**
- [x] `src/jobs/tailor.py` -- add `from google.genai import errors as genai_errors`, `import httpx`, `from pydantic import ValidationError`; wrap the `client.interactions.create(...)` call and `model_validate_json` call in `generate_tailored_application` in `try: ... except (genai_errors.APIError, genai_errors.UnknownApiResponseError, httpx.HTTPError, ValidationError, RuntimeError) as exc: raise SystemExit(f"Tailoring generation failed: {detail}") from exc` (`detail` falls back to the exception's type name when `str(exc)` is empty) -- closes CAP-1. Review widened the tuple past the original two SDK types after Edge Case Hunter found, via SDK source, that a missing/invalid API key raises bare `RuntimeError` and a non-JSON 200 response raises `genai_errors.UnknownApiResponseError` (a `ValueError` subclass, not `APIError`) -- both inside the wrapped call, both previously uncaught.
- [x] `src/jobs/docx_tailor.py` -- identical wrap in `generate_paragraph_edits`, message `f"Resume paragraph tailoring failed: {detail}"` -- closes CAP-2
- [x] `tests/test_tailor.py` -- add `test_generate_tailored_application_raises_system_exit_on_api_error`, `test_generate_tailored_application_raises_system_exit_on_network_error`, `test_generate_tailored_application_raises_system_exit_on_malformed_response`
- [x] `tests/test_docx_tailor.py` -- add the mirrored three tests for `generate_paragraph_edits`

**Acceptance Criteria:**
- Given a mocked `client.interactions.create` that raises `genai_errors.APIError`, when `generate_tailored_application` or `generate_paragraph_edits` is called, then a `SystemExit` is raised (not the raw `APIError`) with a message containing the underlying error text.
- Given a mocked `client.interactions.create` that raises `httpx.ConnectError`, when either function is called, then a `SystemExit` is raised with a message naming the network failure.
- Given a mocked `client.interactions.create` returning JSON that fails schema validation, when either function is called, then a `SystemExit` is raised (not the raw `pydantic.ValidationError`).
- Given a mocked successful call (existing tests), when either function is called, then behavior and return values are unchanged.

## Spec Change Log

## Design Notes

`httpx.HTTPError` is the base class for both `httpx.TimeoutException` and `httpx.ConnectError` (confirmed via `_api_client.py`'s retry predicate, which checks exactly these two alongside `errors.APIError`), so catching it covers the network-failure family without over-broadening to bare `Exception`. `genai.errors.APIError` is itself the base of `ClientError`/`ServerError`, so one `except` clause covers the whole SDK error hierarchy.

## Verification

**Commands:**
- `uv run pytest tests/test_tailor.py tests/test_docx_tailor.py -v` -- expected: all pass, including the new failure-path tests
- `uv run pytest` -- expected: full suite green, no regressions

## Suggested Review Order

**Error-handling shape**

- Entry point: the try/except that converts every Gemini failure mode into a friendly `SystemExit`, with an empty-message fallback to the exception's type name.
  [`tailor.py:96`](../../src/jobs/tailor.py#L96)

- Same wrap in the docx path; note it's now structurally symmetric with `tailor.py` (return moved inside `try`) after review flagged the original asymmetry.
  [`docx_tailor.py:156`](../../src/jobs/docx_tailor.py#L156)

**Exception-set completeness (the review-driven widening)**

- The final except tuple: two SDK types confirmed from installed source (`genai_errors.UnknownApiResponseError`, a `ValueError` subclass not `APIError`) plus bare `RuntimeError` for missing/invalid credentials — both missed in the first pass, added after Edge Case Hunter traced the SDK source.
  [`tailor.py:96-102`](../../src/jobs/tailor.py#L96)

- Regression test proving the except clause is precisely scoped, not a bare `except Exception` — an unrelated exception must still propagate raw.
  [`test_tailor.py:158`](../../tests/test_tailor.py#L158)

- Tests locking in the two review-found gaps: missing-credentials `RuntimeError` and the non-`APIError` `UnknownApiResponseError`.
  [`test_tailor.py:103`](../../tests/test_tailor.py#L103)

**Message quality**

- Every failure-path test asserts the underlying exception text actually lands in the `SystemExit` message, not just the static prefix — the literal AC the first draft's tests missed.
  [`test_tailor.py:81`](../../tests/test_tailor.py#L81)

**Peripherals**

- Mirrored failure-path tests for the docx paragraph-edit path.
  [`test_docx_tailor.py:111`](../../tests/test_docx_tailor.py#L111)
