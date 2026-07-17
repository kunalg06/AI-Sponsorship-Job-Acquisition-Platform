---
id: SPEC-resume-docx-sdt-table-extraction
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Row/cell-level w:sdt extraction

## Why

A pain to solve. `extract_text_from_docx` still silently drops content from a `w:sdt` (content control) that wraps a single table row, a single cell, or a single paragraph inside a cell — one level deeper than the body-level `w:sdt` gap already fixed. `_Rows`/`_Row.cells` only see direct `w:tr`/`w:tc` children, so a Word template that wraps a table row or cell in a content control still loses that content with no warning.

Three implementation passes were needed. Pass 1's per-cell vMerge guard let a wrapped content-holding cell make `CT_Tc._tc_above` silently resolve to a *sibling's* content instead of raising or degrading — confirmed via live repro. Pass 2 tightened the guard to check both rows involved, but a wrapped `<w:tr>` row element itself (not just a cell) still made `_tr_above`'s xpath raise an uncaught `ValueError`, aborting extraction of the *entire document* — confirmed via a second live repro. Pass 3 (shipped) replaces both narrower guards with a single whole-table check.

## Capabilities

- **CAP-1**
  - **intent:** A `w:sdt` wrapping a whole table row is read — its cells' text appears in the table's output in correct document order, same as an unwrapped row.
  - **success:** A table with one sdt-wrapped row interleaved with unwrapped rows extracts all rows, in order.

- **CAP-2**
  - **intent:** A `w:sdt` wrapping a single cell within an otherwise-normal row is read, in its correct position among the row's other cells.
  - **success:** A row with one sdt-wrapped cell and unwrapped siblings extracts all cells' text in the correct left-to-right order.

- **CAP-3**
  - **intent:** A `w:sdt` wrapping a single paragraph inside a table cell (alongside other unwrapped paragraphs in the same cell) is read as part of that cell's text.
  - **success:** A multi-paragraph cell with one paragraph sdt-wrapped includes that paragraph's text in the cell's newline-then-space-flattened output.

- **CAP-4**
  - **intent:** All existing table-extraction behavior is preserved exactly — horizontal-merge collapsing, vertical-merge content repetition across rows for a table with no `w:sdt` usage anywhere, the all-blank-row skip, multi-paragraph-cell newline flattening, and the depth-capped iterative walk.
  - **success:** The full existing `test_resume_extract.py` suite (as it stood before this change) still passes unmodified.

## Constraints

- A generic, shared sdt-unwrapping traversal helper backs all levels (body, row, cell, paragraph-within-cell) — not four near-duplicate stack-walk implementations. The existing body-level `_iter_body_content_including_sdt` is refactored to build on this same generic core.
- Vertical-merge (`vMerge="continue"`) resolution is attempted only for a table where **no row or cell anywhere is `w:sdt`-wrapped** (`_table_has_any_sdt_wrapping`, computed once per table). `CT_Tc.grid_offset`/`_tc_above`/`_tr_above` all rely on `preceding-sibling`/`ancestor` xpaths that assume every `w:tr` is a direct `w:tbl` child and every `w:tc` is a direct `w:tr` child. Two live repros during implementation proved that assumption breaks — sometimes silently, sometimes by raising and aborting the whole document — the moment *any* row or cell in the table is `w:sdt`-wrapped, not just the one being resolved. A per-row or per-cell guard was tried twice and found unsafe both times; the whole-table check is deliberately the coarsest boundary that is provably safe.

## Non-goals

- Not resolving vMerge continuation anywhere in a table that uses `w:sdt` anywhere in it — a documented, table-wide residual (see the constraint above; every affected cell shows its own, often-empty literal content instead, indistinguishable in the output from a genuinely blank source cell). Real Word templates wrap actual content in controls, not merge-continuation placeholder cells, but the residual is intentionally wider than "just the specific merge" given the two correctness failures found in narrower designs.
- Not detecting non-`w:sdt` wrapper elements (`w:ins`, `w:customXml`, etc.) that could trigger the identical underlying python-docx trap — out of scope, matching this module's existing `w:sdt`-only focus.
- Not nested tables inside a cell, headers, footers, or text boxes — already out of scope per the body-level fix and the original table-extraction spec, unchanged here.

## Success signal

A test builds a `.docx` with a table containing an sdt-wrapped row, an sdt-wrapped cell, and an sdt-wrapped in-cell paragraph, interleaved with ordinary unwrapped content, and asserts `extract_text_from_docx`'s output contains all of it in correct document order and correct cell layout. A separate test proves the whole-table tradeoff directly: wrapping a cell in one vertical merge also disables repetition for a second, unrelated vertical merge elsewhere in the same table. Two regression tests reproduce the exact crash scenarios found during implementation (wrapping the continuation row; wrapping the row holding the real content) and assert extraction completes without raising.
