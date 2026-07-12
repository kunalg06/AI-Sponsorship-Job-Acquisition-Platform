---
title: 'Stop persisting outreach-message text in jobs.db'
type: 'refactor'
created: '2026-07-12'
status: 'done'
review_loop_iteration: 0
context: ['{project-root}/_bmad-output/project-context.md']
baseline_commit: 'f95ea34568c4a25502e65a8895de64d7bcc061be'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `outreach_messages.message` stores full drafted outreach text in `jobs.db`, the same anti-pattern already fixed for tailored resumes/cover-letters. Unlike that fix, `outreach_messages` is an insert-only *history* table (multiple drafts per job/channel, e.g. to different contacts) whose full text is actively re-displayed in the UI's "Message history" expander (`views/jobs_list.py`, `views/intake.py`) — so files must be keyed per message row, not per job+channel, or history browsing breaks. `message` is also `NOT NULL` on the existing table (unlike the nullable legacy tailoring columns), so a schema migration is required, not just an additive change.

**Approach:** Write each drafted message to `<out_dir>/<company_slug>/{job_id}_outreach_{channel}_{message_id}.txt` (new `_outreach_message_path` helper in `jobs/cli.py`, reusing the existing `_company_slug`) instead of storing it in the DB. Drop the `message` column from `outreach_messages` (metadata-only: id, job_id, contact_id, contact_name, channel, char_count, created_at). Add a `migrate-legacy-outreach` CLI command (mirroring `migrate-legacy-tailoring`) to back up any pre-existing DB-resident message text to files, then drop the column — required before new inserts can succeed against an existing table.

## Boundaries & Constraints

**Always:**
- File path: `<out_dir>/<company_slug>/{job_id}_outreach_{channel}_{message_id}.txt`, via new `_outreach_message_path(company_name, job_id, channel, message_id, out_dir) -> Path` in `jobs/cli.py`, next to `_tailored_docx_paths`, reusing `_company_slug`.
- `outreach_messages` SCHEMA drops `message` entirely; `char_count` stays computed as `len(message)` before the text is written to file (unchanged value, just no longer backed by a stored column).
- Both existing persistence call sites — `jobs/cli.py::_draft_and_store_outreach` and `jobs/ui_actions.py::draft_and_save_outreach` — write the file themselves right after `insert_outreach_message` returns the new row id (needed for the filename). Add an `out_dir` param to `_draft_and_store_outreach` (CLI: new `--out-dir` arg on `outreach`/`follow-up`, default `DEFAULT_GENERATED_CV_DIR`); `ui_actions.py` uses `DEFAULT_GENERATED_CV_DIR` directly, matching its existing tailoring call.
- New `migrate-legacy-outreach` CLI command: for every pre-existing `outreach_messages` row with a non-null `message` (detected via `PRAGMA table_info` guard, mirroring `list_legacy_tailored_rows`), write it to the same path convention (idempotent — skip a file that already exists), then `ALTER TABLE outreach_messages DROP COLUMN message` if the column is still present. A fresh DB (created after this change) never has the column, so this command is a safe no-op there.
- `views/jobs_list.py`/`views/intake.py`'s "Message history" expander reads the file instead of `msg["message"]`; if the file is missing, show a caption ("message file not found") instead of crashing.

**Ask First:** none identified — the file-per-message-row vs. file-per-job+channel question was already resolved with the human before drafting this spec (per-message-row, to preserve full history browsing).

**Never:**
- Do not touch tailored-resume/cover-letter storage (`jobs/db.py`'s `tailor_*` columns, `docx_tailor.py`) — that migration is already complete and unrelated.
- Do not change `jobs/outreach.py`'s Gemini-calling logic (`draft_outreach_message`, `OutreachDraft`, `OutreachLengthError`) — this is purely a downstream persistence change.
- Do not deduplicate `_draft_and_store_outreach` (CLI) vs. `draft_and_save_outreach` (UI)'s pre-existing parallel implementations — out of scope; add the same file-write step to each without restructuring either.
- Do not add authentication or a UI to browse/manage the raw files directly — out of scope.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Successful draft (CLI or UI) | Any channel, any contact | Metadata row inserted (no `message` column); `.txt` file written with the exact drafted text; `char_count` matches file length | No error expected |
| Message-history display, file present | Past message, file exists on disk | Full text shown via file read, same as today | No error expected |
| Message-history display, file missing | File deleted/moved externally | Caption "message file not found" shown; page doesn't crash | Handled inline, no exception |
| Legacy DB with pre-existing `message` column + real rows | `migrate-legacy-outreach` run | Every non-null `message` backed up to its file (skipping ones already backed up); column dropped; subsequent inserts succeed | N/A |
| Fresh DB (no `message` column ever existed) | `migrate-legacy-outreach` run | No-op, prints "nothing to do" | Guarded via `PRAGMA table_info` |

</frozen-after-approval>

## Code Map

- `src/jobs/outreach_db.py` -- drop `message` from `SCHEMA`/`insert_outreach_message`; add `list_legacy_outreach_message_rows` (JOIN `jobs` for `company_name`) and `drop_legacy_message_column`
- `src/jobs/cli.py` -- add `_outreach_message_path`; wire file-write into `_draft_and_store_outreach`; add `--out-dir` to `outreach`/`follow-up`; new `migrate-legacy-outreach` command
- `src/jobs/ui_actions.py` -- `draft_and_save_outreach` writes the file after insert
- `views/jobs_list.py`, `views/intake.py` -- "Message history" expander reads from file instead of `msg["message"]`
- `tests/test_outreach_db.py`, `tests/test_jobs_cli.py` -- schema/legacy-migration/file-write coverage

## Tasks & Acceptance

**Execution:**
- [x] `src/jobs/outreach_db.py` -- drop `message` from schema/insert; add `list_legacy_outreach_message_rows(conn)` and `drop_legacy_message_column(conn)`, both guarded via `PRAGMA table_info`
- [x] `src/jobs/cli.py` -- add `_outreach_message_path(...)`; update `_draft_and_store_outreach` to accept `out_dir` and write the file; add `--out-dir` args; add `migrate-legacy-outreach` subcommand (backup-then-drop-column, idempotent)
- [x] `src/jobs/ui_actions.py` -- `draft_and_save_outreach` writes the file via `_outreach_message_path` after insert
- [x] `views/jobs_list.py`, `views/intake.py` -- read message text from file in the history expander; graceful missing-file caption
- [x] `tests/test_outreach_db.py` -- assert no `message` column on inserted rows; `list_legacy_outreach_message_rows`/`drop_legacy_message_column` against both a fresh schema and a manually-built legacy-shape table
- [x] `tests/test_jobs_cli.py` -- `migrate-legacy-outreach` idempotency test (mirroring the `migrate-legacy-tailoring` test style); `_draft_and_store_outreach` writes the expected `.txt` file

**Acceptance Criteria:**
- Given a fresh job and a successful draft, when `insert_outreach_message` completes, then a `.txt` file with the exact drafted text exists at the expected job/channel/message-id path.
- Given a pre-existing `outreach_messages` table with the old `message NOT NULL` column and real rows, when `migrate-legacy-outreach` runs, then every non-null message is backed up to disk, the column is dropped, and a subsequent draft insert succeeds without error.
- Given the Message-history expander and a message whose file has been deleted, when the page renders, then it shows a "file not found" caption instead of raising.

## Verification

**Commands:**
- `uv run pytest tests/test_outreach_db.py tests/test_jobs_cli.py -v` -- expected: existing tests pass, new ones green
- `uv run pytest` -- expected: full suite green, no regressions

**Manual checks (if no CLI):**
- Run `uv run python -m jobs.cli migrate-legacy-outreach` against the real local `data/jobs.db` (which currently has a pre-existing empty-but-old-shaped `outreach_messages` table) and confirm it completes cleanly and a subsequent `uv run streamlit run app.py` outreach draft succeeds.

## Suggested Review Order

**Persistence layer**

- Schema change and the `message`-discarding insert - the core of the fix.
  [`outreach_db.py:72`](../../src/jobs/outreach_db.py#L72)

- Legacy-row lookup, fixed post-review to use `LEFT JOIN` so an orphaned row (no matching job) still gets backed up instead of being silently destroyed by the column drop.
  [`outreach_db.py:104`](../../src/jobs/outreach_db.py#L104)

- Column drop, guarded so a fresh DB that never had `message` is a safe no-op.
  [`outreach_db.py:123`](../../src/jobs/outreach_db.py#L123)

**File-path convention and migration**

- New path helper: message-id-keyed (not job+channel-keyed), so history across multiple drafts is preserved.
  [`cli.py:387`](../../src/jobs/cli.py#L387)

- New shared read helper, extracted post-review to remove near-duplicate logic across both views.
  [`cli.py:398`](../../src/jobs/cli.py#L398)

- Migration: backs up legacy DB-resident text to disk, now with per-row `OSError` isolation (post-review) so one bad row can't abort the rest.
  [`cli.py:646`](../../src/jobs/cli.py#L646)

**Write-path wiring and the un-migrated-DB error path**

- CLI draft-and-store: writes the file after insert; now raises a friendly, actionable error (post-review) instead of a raw `sqlite3.IntegrityError` if `migrate-legacy-outreach` hasn't been run yet.
  [`cli.py:753`](../../src/jobs/cli.py#L753)

- UI draft-and-save: same file-write and friendly-error wiring, mirrored for the Streamlit path.
  [`ui_actions.py:59`](../../src/jobs/ui_actions.py#L59)

**Message-history display**

- Both views now call the shared read helper instead of duplicating path-building/exists-check logic.
  [`jobs_list.py:395`](../../views/jobs_list.py#L395)
  [`intake.py:476`](../../views/intake.py#L476)

**Peripherals**

- Ledger: item marked done; 2 new findings logged for later attention.
  [`deferred-work.md`](deferred-work.md)
