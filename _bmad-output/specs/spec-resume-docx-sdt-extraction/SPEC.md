---
id: SPEC-resume-docx-sdt-extraction
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# extract_text_from_docx reads w:sdt-wrapped content

## Why

A pain to solve. `extract_text_from_docx` (`src/resume/extract.py`) silently drops any paragraph or table wrapped in a `w:sdt` (structured document tag / content control) element — Word's built-in resume/CV templates commonly wrap sections (job title, dates, skills) in content controls, so a real CV built from one of those templates can produce an incomplete extracted profile with no error or warning. Confirmed by reading python-docx source: even its own public `iter_inner_content()` API — already used by this function for the ordinary paragraph/table case — is built on `CT_Body.inner_content_elements`, whose xpath (`./w:p | ./w:tbl`) only looks at direct children of the document body, skipping anything wrapped in `w:sdt`.

## Capabilities

- **CAP-1**
  - **intent:** `extract_text_from_docx` reads paragraph and table content wrapped in a `w:sdt` (content control), in document order alongside ordinary paragraphs/tables, instead of silently dropping it.
  - **success:** A `.docx` with a resume section wrapped in a single content control (as Word's own resume templates commonly do) has that section's text appear in `extract_text_from_docx`'s output, at its actual document position.

- **CAP-2**
  - **intent:** Nested `w:sdt` (a content control inside another content control) is also read, up to a bounded depth, walked iteratively rather than via Python recursion.
  - **success:** A `.docx` with a paragraph nested two levels deep inside `w:sdt` wrappers has that paragraph's text appear in the output. A pathologically or adversarially deep `w:sdt` chain beyond the bound does not crash or hang extraction (no `RecursionError`, no unbounded work) — content beyond the bound is simply not read.

## Constraints

- The walk must be iterative (explicit stack/queue), not Python recursion, so a deeply or adversarially nested `w:sdt` chain can't raise `RecursionError` or degrade performance unboundedly.
- Depth must be capped at a fixed bound; content nested beyond the bound is silently skipped — matches this codebase's existing "silent content loss for rare structures" precedent (headers/footers/text boxes are already out of scope for the same reason).
- Must preserve the existing document-order interleaving behavior this builds on (from `spec-resume-docx-table-extraction.md`): a `w:sdt`-wrapped paragraph/table appears in the output at its actual position in the document, not appended at the end.
- Must reuse the existing `_row_text` table-row handling (merged-cell dedup, multi-paragraph newline flattening, all-blank-row skip) for any table found inside a `w:sdt`, not a separate or divergent code path.

## Non-goals

- Not headers, footers, or text boxes — already out of scope per `spec-resume-docx-table-extraction.md`, unchanged by this spec.
- Not `w:sdt` elements nested inside other wrapper types (`w:ins`, `w:customXml`, etc.) — only `w:sdt` itself is in scope; other wrapper elements remain a separate, still-open gap (`inner_content_elements`'s own docstring notes `w:ins` is excluded too).

## Success signal

A test builds a `.docx` with a paragraph (and separately, a table) wrapped in `w:sdt`, interleaved with ordinary unwrapped paragraphs, and asserts `extract_text_from_docx`'s output contains the wrapped content in correct document order — where before this fix it would have been silently missing.

## Assumptions

- The depth bound is a fixed constant (e.g. 20) chosen for adversarial-input safety, not measured against real Word documents — real CV content controls are essentially never nested more than 1–2 levels deep, so the bound is a defensive ceiling, not a tuned value.
