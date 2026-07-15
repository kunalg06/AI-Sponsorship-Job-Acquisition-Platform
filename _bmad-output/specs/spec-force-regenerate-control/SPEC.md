---
id: SPEC-force-regenerate-control
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Force-regenerate control

## Why

A pain to solve. `views/intake.py` and `views/jobs_list.py`'s tailor button labels itself "Regenerate tailored resume & cover letter" once a docx pair already exists, but always calls `generate_tailored_docx_for_job` with the default `force=False` — clicking it when the cache is valid is silently a no-op cache hit, not a regeneration. The button's own label overpromises. Flagged in a round-2 adversarial review (2026-07-12) and originally deferred as "a UI-design decision" — investigation found that framing overestimated the fix: both views already compute the exact boolean (`already_generated`) that picks the button's label, and reusing it as the force argument closes the gap with no new UI element.

## Capabilities

- **CAP-1**
  - **intent:** Clicking the tailor button when it reads "Regenerate tailored resume & cover letter" triggers an actual fresh regeneration, not a cache hit.
  - **success:** Calling `generate_tailored_docx_for_job` with `force=True` against a job whose docx cache is already valid runs the LLM-calling path again instead of being short-circuited by the cache check.

- **CAP-2**
  - **intent:** Clicking the button when it reads "Generate tailored resume & cover letter" (no cache yet) behaves exactly as today.
  - **success:** Existing tests covering the first-generation path pass unmodified.

## Constraints

- `force=True` bypasses the job_id-keyed cache-hash-and-file-existence check, triggering a real Gemini API call and overwriting the existing resume/cover-letter docx files — a real cost, not a free no-op.
- No confirmation dialog before this regeneration — matches this codebase's existing convention that small-blast-radius single-click mutations don't need one (only bigger-blast-radius admin actions got confirmation dialogs in a prior spec); the button's own label already signals intent unambiguously.

## Non-goals

- Adding any new UI element (checkbox, second button, confirmation dialog) — the fix reuses the `already_generated` boolean both views already compute, as the `force` argument.
- Changing the plain-text `tailor` CLI command, which is already deliberately uncached and unrelated to this docx-path cache-check.

## Success signal

- A user who clicks a button labeled "Regenerate tailored resume & cover letter" gets a genuinely fresh tailored docx pair, matching the label's promise.
