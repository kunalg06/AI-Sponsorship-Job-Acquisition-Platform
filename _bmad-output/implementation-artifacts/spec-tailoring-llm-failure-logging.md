---
title: 'Tailoring LLM failure logging'
type: 'bugfix'
created: '2026-07-16'
status: 'done'
route: 'one-shot'
---

# Tailoring LLM failure logging

## Intent

**Problem:** `generate_tailored_application` (`src/jobs/tailor.py`) and `generate_paragraph_edits` (`src/jobs/docx_tailor.py`) convert every Gemini failure straight to `SystemExit` with no server-side record of the original exception/traceback — once the Streamlit view shows `st.error(error_display_text(exc))`, the full traceback is gone, leaving near-zero diagnosability for a real production failure.

**Approach:** Print the original exception's traceback to stderr (`traceback.print_exc(file=sys.stderr)`, wrapped defensively so the diagnostic itself can never break the `SystemExit` contract) inside each except block, before the existing `raise SystemExit(...) from exc` line — matching this codebase's only existing diagnostic-output precedent (`app.py`'s plain stderr print for the missing-`GEMINI_API_KEY` case), not introducing the `logging` module.

## Suggested Review Order

**The fix**

- Entry point: the defensive stderr print, placed before `raise SystemExit`, with an inline comment on why it's there.
  [`tailor.py:106`](../../src/jobs/tailor.py#L106)

- Identical fix in the docx path.
  [`docx_tailor.py:166`](../../src/jobs/docx_tailor.py#L166)

**Tests**

- Verifies the traceback lands on stderr, is attributable to the real call site (not just a matching exception type/message), the `SystemExit` message is unaffected, and stdout stays clean.
  [`test_tailor.py:168`](../../tests/test_tailor.py#L168)

- Covers the structurally distinct path where the exception originates inside the `try` block (`model_validate_json`), not at the mocked call site.
  [`test_tailor.py:184`](../../tests/test_tailor.py#L184)

- Mirrored pair for the docx path.
  [`test_docx_tailor.py:198`](../../tests/test_docx_tailor.py#L198)
