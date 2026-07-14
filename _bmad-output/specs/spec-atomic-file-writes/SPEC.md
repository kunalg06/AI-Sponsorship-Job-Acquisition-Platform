---
id: SPEC-atomic-file-writes
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Atomic File Writes for jobs/cli.py's Output Paths

## Why

None of the `.txt`/`.docx` write paths in `jobs/cli.py` use a temp-file-then-rename (atomic replace) pattern — a pain flagged twice independently (2026-07-12 review of `spec-tailored-content-file-only-storage.md` and `spec-outreach-file-only-storage.md`) as the same root cause with two distinct consequences: a crash mid-write can leave a partial tailoring/backup file that still passes this codebase's "does it exist" cache checks, and — more severely — an outreach-message write failure happening *after* its DB row already committed can permanently and silently lose the drafted text while the metadata survives, with nothing distinguishing that specific failure from any other.

## Capabilities

- **CAP-1**
  - **intent:** Tailored resume/cover-letter output writes (both the primary tailoring path and the legacy-migration/regeneration path) can never leave a partial file at their target path if the write is interrupted.
  - **success:** A write interrupted partway through either call site leaves the target path either fully absent, with its complete prior content, or with the complete new content — never truncated or partial.

- **CAP-2**
  - **intent:** The legacy-outreach DB-text-backup write (`_migrate_legacy_outreach_text`, distinct from CAP-1's tailoring-text backup) can never leave a partial backup file if interrupted, while preserving its existing per-row "warn and continue to the next row" behavior on failure.
  - **success:** Same truncation-safety criterion as CAP-1, applied to this write site. A failure on one row still prints a warning and continues to the next row, unchanged from current behavior.

- **CAP-3**
  - **intent:** The outreach-message draft write can never leave a partial file if interrupted, and if it fails after its DB row has already committed, the operator gets an error message that specifically says the drafted text was lost even though its metadata was saved — distinct from a generic write-failure message.
  - **success:** A write interrupted at this site leaves the target path either absent or fully complete, never truncated. A simulated failure at this specific site (post-DB-commit) surfaces an error message naming the text-lost-but-metadata-saved condition, not a generic exception string.

## Constraints

- A single, shared, reusable atomic-write mechanism must be used across all four write sites (CAP-1's two call sites, CAP-2, CAP-3) — no independent per-site implementations.
- The temp file must be written in the same directory/filesystem as the final target so the replace is atomic — a cross-filesystem rename silently degrades to copy+delete. `_bmad/scripts/memlog.py`'s own `write_atomic()` (temp + flush + fsync + `os.replace`, same directory) is a working precedent already in this codebase to mirror.
- No new dependencies — Python's stdlib (`tempfile`/a `Path` sibling + `os.replace`) is sufficient.
- Existing encoding (`utf-8`) and existing directory-creation behavior (`path.parent.mkdir(parents=True, exist_ok=True)`) at each site must be preserved — this fix targets write atomicity only.

## Non-goals

- Atomic-write handling for any file-write path outside these four `jobs/cli.py` sites (e.g. not `resume/db.py`, `register/db.py`, or any other module).
- A compensating DB-row delete/rollback for the outreach-write-failure case (CAP-3) — see Assumptions.
- Retry/backoff logic for transient write failures — a single clean failure-and-report is sufficient.
- Changing what data is written at any site — only how it's written.

## Success signal

Killing the process (or otherwise forcing a failure) partway through any of the four identified write sites never leaves a truncated file at the final path — it's either the old complete content, the new complete content, or absent. For the outreach site specifically, a write failure occurring after `insert_outreach_message`'s commit produces an error distinctly naming the text-lost/metadata-saved mismatch, not a generic exception.

## Assumptions

- No compensating delete of the `outreach_messages` row on a post-commit write failure (CAP-3) — matches this codebase's established insert-only convention for its other tables (`jobs`, `profiles`). The fix prioritizes a clear, specific error message over transactional rollback, since adding a delete path is a larger behavioral change than this spec's scope.

## Open Questions

- None — the one real ambiguity (whether a post-commit write failure should roll back the DB row) is resolved by the logged assumption above.
