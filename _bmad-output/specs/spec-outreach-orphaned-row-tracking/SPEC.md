---
id: SPEC-outreach-orphaned-row-tracking
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Outreach orphaned-row tracking

## Why

A pain to solve. A CAP-3-style outreach write failure (message metadata committed to `outreach_messages`, but the `.txt` file write then fails) leaves that row permanently orphaned — retrying inserts a *second* row rather than fixing the first. `_read_outreach_message_text` returns `None` for this row identically to a row whose file was simply deleted later, so the "Message history" expander in `views/jobs_list.py`/`views/intake.py` shows the same generic "(message file not found)" caption either way, giving the user no way to tell a known, already-explained failure from an unexplained one.

## Capabilities

- **CAP-1**
  - **intent:** The moment a write failure happens (message logged to the DB, then the file write fails), the `outreach_messages` row is marked as a known write-failure, distinct from a row whose file is missing for any other reason.
  - **success:** After a simulated write failure, the row's write-failure marker is set; a row that never failed has it unset.

- **CAP-2**
  - **intent:** The Message-history expander shows a distinguishing caption for a known write-failure row instead of the generic "(message file not found)" caption used for every other missing-file case.
  - **success:** A row with the write-failure marker set renders the distinguishing caption; a row with a missing file but no marker still renders the existing generic caption unchanged.

## Constraints

- The write-failure marker must work on a pre-existing DB too, not just a freshly created one. `outreach_db.py`'s `ensure_schema()` has no auto-migration for pre-existing DBs (unlike `jobs.db`'s `jobs` table). This needs its own targeted migration (a `PRAGMA table_info` check + `ALTER TABLE ADD COLUMN`, matching this file's existing `drop_legacy_message_column` precedent) — not a naive reuse of `jobs.db._ensure_columns`, whose paren-parsing assumes one `CREATE TABLE` per schema string, while `outreach_db.py`'s `SCHEMA` has two (`contacts` + `outreach_messages`).
- Must be applied identically at both write-failure sites (`jobs/cli.py`'s `_draft_and_store_outreach` and `jobs/ui_actions.py`'s `draft_and_save_outreach`) — a fix at only one leaves the other's failures just as unmarked as before.
- Must be applied identically at both display sites (`views/jobs_list.py` and `views/intake.py`) — same reasoning.

## Non-goals

- Not a compensating DB-row delete or automatic cleanup of orphaned rows — matches this codebase's existing insert-only convention for `outreach_messages` (already a deliberate assumption logged in `spec-atomic-file-writes.md`).
- Not a retry/resume mechanism that re-attempts the failed file write for the same row — the drafted text is already gone once `SystemExit` fires (never persisted anywhere but the error message shown to the operator at the time), so there's nothing left to retry against; this only makes the historical row's state honest, not recoverable.

## Success signal

A test simulates a write failure via the CLI or UI path, then reads the row back and confirms the write-failure marker is set; a second test drives the real Message-history expander (via `AppTest`) for such a row and asserts the distinguishing caption renders instead of "(message file not found)".
