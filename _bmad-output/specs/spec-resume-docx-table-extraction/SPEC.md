---
id: SPEC-resume-docx-table-extraction
companions: ["../../project-context.md"]
sources: ["../../implementation-artifacts/deferred-work.md", "../../implementation-artifacts/spec-admin-cv-upload-resume-registration.md"]
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Resume .docx table extraction

## Why

A pain to solve, surfaced by both reviewers of `spec-admin-cv-upload-resume-registration.md`. `extract_text_from_docx` (`src/resume/extract.py`) only reads top-level paragraph text — tables are silently dropped. Real CVs commonly lay out skills, dates, or project details in tables, so a table-based CV produces an incomplete extracted-text string with no error or warning, feeding directly into the Admin page's CV-upload → `extract_profile` → `insert_profile` pipeline. This was a deliberate frozen-spec scope choice at authoring time ("pure paragraph-join"), not an oversight — extending it now is purely additive and behavior-tightening (extracts more real text, never less), so it doesn't require destructive renegotiation of that original decision.

## Capabilities

- **CAP-1**
  - **intent:** `extract_text_from_docx` includes table content (every row's cell text) in its returned text, in the same relative position tables appear in the source document, so a table-based CV layout no longer silently loses content laid out in a table.
  - **success:** A `.docx` with a paragraph, then a table, then another paragraph produces extracted text containing all three pieces of content in that order, with every table row's cells present and no cell content missing.

## Constraints

- The existing test (`test_extract_text_from_docx_joins_paragraph_text_with_newlines`, a table-free `.docx`) must keep passing unchanged — its exact current output for a paragraph-only document is unaffected.
- Table rows join their cells with a separator (`" | "`) distinct from the newline used between paragraphs/rows, so downstream text consumers can still tell where one row ends and the next begins.
- `extract_text_from_docx`'s signature and return type (`str`) are unchanged — no new parameters, no new exceptions beyond what `python-docx` itself can already raise for a malformed `.docx`.

## Non-goals

- Headers, footers, and text boxes remain out of scope — split off as a separate, still-open deferred item (different APIs, rarer in CVs than tables).
- Nested tables (a table inside a table cell) are not specially handled — `python-docx`'s `cell.text` does not recurse into a nested table, so nested-table content stays dropped. Rare enough in real CVs not to warrant added complexity here.
- No change to `resume.extract.extract_profile`, `resume.db.insert_profile`, or the Admin page UI — this is a pure input-completeness fix to the text-extraction step only.
- No warning/error surfaced when a document has zero tables or zero paragraphs — matches the function's existing silent, best-effort extraction behavior.

## Success signal

Uploading a table-based CV on the Admin page produces a candidate profile that reflects the CV's table content (e.g. a skills/dates grid), not one silently missing everything that was laid out in a table.
