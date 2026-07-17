---
id: SPEC-docx-tailoring-concurrency-guard
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Docx-tailoring concurrency guard

## Why

A pain to solve. Two browser tabs or sessions both seeing a valid docx cache and both clicking "Regenerate" for the same job both bypass the cache, both make a real LLM call, and both overwrite the same docx files and `jobs.db` tailoring columns — last write wins, silently discarding the other session's LLM output and API spend. `_tailor_docx_for_job` (`src/jobs/cli.py:468`) is the single shared implementation behind both `jobs.cli tailor-docx` and `ui_actions.generate_tailored_docx_for_job`, so a fix there closes the race for CLI-vs-UI and UI-vs-UI overlap alike. The cache-check itself is also racy (two callers can both observe a miss before either writes), so the guard needs to cover the whole call, not just the write step.

## Capabilities

- **CAP-1**
  - **intent:** A second concurrent call to `_tailor_docx_for_job` for the same job, made while a first call for that job is still running, is rejected with a clear error instead of proceeding to a real LLM call or file write.
  - **success:** Two sequential calls simulating overlap (the first call's lock claimed and not yet released) — the second raises `SystemExit` naming the job and stating tailoring is already in progress; no LLM call or file write happens on the rejected call.

- **CAP-2**
  - **intent:** The lock is always released after a call finishes, whether it succeeds or raises, so one failed generation never permanently blocks future retries for that job.
  - **success:** A call that raises mid-generation still leaves the job's lock cleared afterward, and an immediately-following call can claim it.

- **CAP-3**
  - **intent:** A lock left set by a crashed or killed process (one that never reached the release step) is reclaimable once it goes stale, rather than blocking that job's tailoring forever.
  - **success:** A lock claimed longer ago than the staleness window is treated as claimable by a new call, even though nothing explicitly released it.

## Constraints

- The lock lives in the jobs DB (a new nullable timestamp column on the `jobs` table, via this codebase's existing `_ensure_columns` auto-migration convention) — not in-process or `st.session_state`, since `st.session_state` is per-browser-session and can't see across tabs, while the DB is the one piece of state already shared across every caller of this app's single-SQLite-writer model.
- Claiming is a single atomic `UPDATE ... WHERE` (conditional on the lock column being `NULL` or older than the staleness cutoff) — a separate read-then-write check has the same race this spec exists to close.
- The lock wraps the entire `_tailor_docx_for_job` body, including the cache-check, not just the fresh-generation branch, since the cache hit/miss decision is itself part of the race.

## Non-goals

- Not a real distributed lock or job queue — a simple advisory DB flag, matching this app's existing single-SQLite-writer, best-effort concurrency mitigations (e.g. `register.db`'s `busy_timeout` PRAGMA for the sponsor-register race).
- Not queueing or auto-retrying a rejected call — it surfaces as a `SystemExit`, exactly like every other failure on this path (`views/intake.py`/`views/jobs_list.py` already catch it via `error_display_text`), and the user decides whether to retry.

## Success signal

A test claims the lock for a job, then attempts a second call for the same job before releasing the first — the second call raises `SystemExit` and makes no LLM call, where before this fix both calls would have proceeded and raced.

## Assumptions

- The staleness window is 5 minutes (300s) — long enough to cover a slow LLM call plus docx writes without reclaiming a live lock, short enough to recover reasonably fast from a crashed process. Not measured against real generation times; a defensive default, not a tuned value.
