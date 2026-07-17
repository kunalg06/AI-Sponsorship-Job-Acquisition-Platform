---
title: 'Row/cell-level w:sdt extraction'
type: 'feature'
created: '2026-07-17'
status: 'done'
route: 'one-shot'
---

# Row/cell-level w:sdt extraction

## Intent

**Problem:** `extract_text_from_docx` silently dropped content from a `w:sdt` wrapping a single table row, cell, or in-cell paragraph — one level deeper than the body-level `w:sdt` fix already shipped.

**Approach:** Three implementation passes, each corrected by a live-reproduced adversarial review, not just reasoning. Pass 1's per-cell vertical-merge guard let a wrapped content-holding cell make `_tc_above` silently resolve to a *sibling's* content. Pass 2's per-row guard still let a wrapped `<w:tr>` element raise an uncaught `ValueError` that aborted the *entire document's* extraction. Pass 3 (shipped) replaces both with a single whole-table check (`_table_has_any_sdt_wrapping`) — vertical-merge resolution is only attempted for a table with zero `w:sdt` usage anywhere in it, a deliberately coarser but provably safe boundary. A third review round found no further correctness bugs, only documentation/coverage gaps, all patched.

## Suggested Review Order

**The three-pass history and why the final design is the safe one**

- The whole-table detector and its docstring explaining the two correctness failures it was built to close.
  [`extract.py:111`](../../src/resume/extract.py#L111)

- How it gates vertical-merge resolution.
  [`extract.py:146`](../../src/resume/extract.py#L146)

- The top-level entry point, computing the flag once per table.
  [`extract.py:224`](../../src/resume/extract.py#L224)

**Tests**

- The two crash-regression tests reproduce the exact bugs pass 2's review found; the whole-table-tradeoff test proves the residual is real, not just claimed.
  [`test_resume_extract.py`](../../tests/test_resume_extract.py)
