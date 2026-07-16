---
title: 'Resume .docx table extraction'
type: 'feature'
created: '2026-07-16'
status: 'done'
route: 'one-shot'
---

# Resume .docx table extraction

## Intent

**Problem:** `extract_text_from_docx` (`src/resume/extract.py`) only read top-level paragraph text — tables were silently dropped, so a table-based CV layout (skills/dates commonly laid out in a table) produced an incomplete extracted-text string with no error or warning, feeding straight into the Admin page's CV-upload → profile-registration pipeline.

**Approach:** Walk `document.iter_inner_content()` (python-docx's own public API for order-preserving `w:p`/`w:tbl` traversal) so table content lands in the same relative position it appears in the source document, joining each row's cells with `" | "`. Review surfaced three real edge-case bugs during implementation — an all-blank table row producing a non-empty `" | "` that would defeat the caller's "no text found" guard, horizontally-merged cells duplicating their text, and multi-paragraph cells injecting stray newlines — all fixed before merge, plus a fragile-parent-object issue resolved by switching to the official API. Headers, footers, text boxes, and `w:sdt` content-control-wrapped sections remain unread (out of scope; `w:sdt` logged as a new deferred item).

## Suggested Review Order

**The fix**

- Entry point: order-preserving traversal via python-docx's own public API, plus the docstring noting what's still excluded.
  [`extract.py:77`](../../src/resume/extract.py#L77)

- The row-text helper: dedupe merged cells, flatten embedded newlines, and skip all-blank rows — three review-driven fixes in one place.
  [`extract.py:57`](../../src/resume/extract.py#L57)

**Tests**

- Baseline order-preservation case (paragraph → table → paragraph).
  [`test_resume_extract.py:51`](../../tests/test_resume_extract.py#L51)

- The three review-found edge cases: blank-row skip, merged-cell dedup, and embedded-newline flattening.
  [`test_resume_extract.py:75`](../../tests/test_resume_extract.py#L75)
