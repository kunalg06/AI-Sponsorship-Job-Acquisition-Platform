---
title: 'extract_text_from_docx reads w:sdt-wrapped content'
type: 'feature'
created: '2026-07-17'
status: 'done'
route: 'one-shot'
---

# extract_text_from_docx reads w:sdt-wrapped content

## Intent

**Problem:** `extract_text_from_docx` silently dropped any paragraph or table wrapped in a `w:sdt` (structured document tag / content control) element — Word's built-in resume/CV templates commonly wrap sections in content controls, and even python-docx's own public `iter_inner_content()` API skips `w:sdt` entirely (confirmed by reading its source: `CT_Body.inner_content_elements`'s xpath is `./w:p | ./w:tbl`, direct children only).

**Approach:** New `_iter_body_content_including_sdt` walks the document body with an explicit stack (not Python recursion), looking inside `w:sdt`/`w:sdtContent` up to a fixed depth cap (`_MAX_SDT_DEPTH = 20`). Review found the initial docstring overclaimed scope: a `w:sdt` wrapping a single table row or an in-cell paragraph (not a whole body-level section) is still dropped, since table/cell iteration still goes through python-docx's own unmodified APIs — corrected the docstrings to state this precisely and logged the row/cell-level gap as a separate deferred item rather than expanding scope. Review also caught the docstring conflating two different protections (iterative-not-recursive is what prevents `RecursionError`; the depth cap only bounds how much gets read) and several test-coverage gaps (missing-`sdtContent` guard, empty `sdtContent`, exact depth-cap boundary, multi-item wrappers, multiple interleaved wraps) — all patched and mutation-tested.

## Suggested Review Order

**The walk and its documented scope**

- The iterative, depth-capped body walk — this is the core of the fix.
  [`extract.py:81`](../../src/resume/extract.py#L81)

- How `extract_text_from_docx` wires it in, and the corrected docstring on what is/isn't covered.
  [`extract.py:123`](../../src/resume/extract.py#L123)

**Tests**

- The depth-cap boundary and guard tests are the ones mutation-tested to confirm they actually catch a regression.
  [`test_resume_extract.py`](../../tests/test_resume_extract.py)
