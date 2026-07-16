---
id: SPEC-tailoring-llm-error-handling
companions: ["../../project-context.md"]
sources: ["../../implementation-artifacts/deferred-work.md", "../../implementation-artifacts/spec-force-regenerate-control.md"]
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Tailoring LLM error handling

## Why

A mandate to meet, surfaced by adversarial review of `spec-force-regenerate-control.md`. Neither `generate_tailored_application` (`src/jobs/tailor.py:73`) nor `generate_paragraph_edits` (`src/jobs/docx_tailor.py:132`) wraps its `genai.Client()` call in a try/except, so a network error, API error, or a malformed-JSON `model_validate_json` failure propagates as a raw, unhandled exception. `views/intake.py` and `views/jobs_list.py` only catch `except SystemExit` at every call site that reaches these functions, so today this crashes as a raw Streamlit traceback instead of the friendly error this codebase's other failure paths already show. `project-context.md` already documents this as a known, unfixed gap. The force-regenerate-control change widened where it's reachable: "Regenerate" used to be a guaranteed cache hit that never called the LLM again; now both "Generate" and "Regenerate" can.

## Capabilities

- **CAP-1**
  - **intent:** A Gemini API/network failure or malformed-JSON response during resume+cover-letter text generation (`generate_tailored_application`) is caught and re-raised as a friendly `SystemExit`-style message instead of propagating as a raw, unhandled exception.
  - **success:** Mocking the call to raise (simulating a network/API error), or to return JSON that fails `TailoredApplication.model_validate_json`, both result in a `SystemExit` reaching the caller (`_cmd_tailor`, `_get_or_generate_tailor_text`) with a message identifying what failed. Existing tests that mock a successful call are unaffected.

- **CAP-2**
  - **intent:** The same failure handling applies to `generate_paragraph_edits` (the docx paragraph-rewrite path).
  - **success:** Mocking the call to raise, or to return JSON that fails `TailoredResumeEdits.model_validate_json`, both result in a `SystemExit` reaching the caller (`_tailor_docx_for_job`) with a message identifying what failed. Existing tests that mock a successful call are unaffected.

## Constraints

- Reuse this codebase's existing `raise SystemExit(str)` convention for user-facing failures — do not introduce a new exception class. Both Streamlit views already catch `except SystemExit` at every call site that reaches these functions (`ui_actions.generate_tailored_docx_for_job`'s own docstring confirms this), so no view-layer change is in scope.
- Preserve the `client: Optional[genai.Client] = None` keyword parameter and each function's current signature/return type — required for Gemini-call mockability in tests, per `project-context.md`'s Mock Usage rule.
- Success-path behavior and return values are unchanged; only the failure path gains handling.

## Non-goals

- Retry/backoff or other resilience engineering for transient network failures — conversion to a friendly error only.
- `src/jobs/extract.py` — `project-context.md`'s Known-gap note names it alongside `tailor.py`, but this deferred-work entry named only `generate_tailored_application` and `generate_paragraph_edits`; `extract.py` is a separate future item.
- A new structured exception class mirroring `OutreachLengthError` — this failure mode has no extra data worth carrying beyond a message, unlike `OutreachLengthError`'s `draft_text`/`char_count`/`limit`.
- Any change to argparse's own top-level exception handling or process exit-code behavior for the CLI entry point — already works via `SystemExit`'s normal propagation.

## Success signal

A Gemini network/API failure or malformed-JSON response during resume/cover-letter tailoring — plain-text CLI path or docx UI path — shows the user (or CLI operator) a clear, catchable error message instead of crashing with a raw traceback.

## Assumptions

- A plain `raise SystemExit(f"...: {exc}")` (or equivalent message naming the failure) is sufficient user-facing text — no request for retry buttons or structured recovery data.

## Open Questions

- What specific exception type(s) does `google-genai`'s `client.interactions.create()` raise for network/API failures (rate limit, auth, timeout, 5xx)? No call site in this codebase catches or documents this today — worth checking the installed `google-genai` version's source/docs before implementing, to catch precisely rather than a bare `except Exception`.
