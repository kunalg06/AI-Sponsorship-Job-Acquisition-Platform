---
id: SPEC-tailoring-llm-failure-logging
companions: ["../../project-context.md"]
sources: ["../../implementation-artifacts/deferred-work.md", "../../implementation-artifacts/spec-tailoring-llm-error-handling.md"]
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Tailoring LLM failure logging

## Why

A pain to solve, surfaced by adversarial review of `spec-tailoring-llm-error-handling.md`. The except blocks in `generate_tailored_application` (`src/jobs/tailor.py`) and `generate_paragraph_edits` (`src/jobs/docx_tailor.py`) convert every Gemini failure straight to `SystemExit` with no server-side record of the original exception or traceback. Once `views/intake.py`/`views/jobs_list.py` catch it and show `st.error(error_display_text(exc))`, the full traceback is gone — leaving near-zero diagnosability for a real production failure (API error, network failure, missing credentials, malformed response).

## Capabilities

- **CAP-1**
  - **intent:** When `generate_tailored_application` catches a Gemini failure, the original exception's full traceback is written to stderr before conversion to `SystemExit`, so a server operator can diagnose a real failure even though the Streamlit user only sees the friendly `SystemExit` message.
  - **success:** Mocking the Gemini call to raise any of the already-caught types (`APIError`, `UnknownApiResponseError`, `httpx.HTTPError`, `ValidationError`, `RuntimeError`) results in the original exception's traceback text appearing on stderr, in addition to the existing `SystemExit` behavior being unchanged.

- **CAP-2**
  - **intent:** The same stderr-traceback behavior applies to `generate_paragraph_edits`.
  - **success:** Same as CAP-1, verified against `generate_paragraph_edits`'s own except block and its own caught exception types.

## Constraints

- Use `traceback.print_exc(file=sys.stderr)` (stdlib `traceback` module) — do not introduce the `logging` module. This codebase has zero existing `logging` usage; its only diagnostic-output precedent is `app.py`'s plain `print(..., file=sys.stderr)` for the missing-`GEMINI_API_KEY` case.
- `SystemExit`'s message, the except tuple's exception types, and every other existing behavior of both functions are unchanged — this is additive-only (a new side effect on the failure path), not a refactor.
- The stderr write must happen inside the except block, while the original traceback context is still live (`sys.exc_info()`), before the `raise SystemExit(...) from exc` line.

## Non-goals

- No introduction of the `logging` module, log levels, log rotation, or any structured-logging framework — plain stderr is the deliberate, minimal fix matching this project's existing convention and its no-CI/no-observability-infra-by-design posture.
- No change to `src/jobs/extract.py` or `src/jobs/outreach.py` — out of scope, same exclusion as the parent spec that deferred this item.
- No change to what the Streamlit user sees — `st.error(error_display_text(exc))` output is unaffected; this is purely a server-side diagnostic addition.
- No log aggregation, remote log shipping, or persistence beyond the process's own stderr stream.

## Success signal

A real Gemini call failure in either tailoring path leaves its full original traceback on the server's stderr stream (visible in the terminal running `uv run streamlit run app.py`, or a hosting platform's log viewer), even though the Streamlit user only ever sees the friendly `SystemExit` message.
