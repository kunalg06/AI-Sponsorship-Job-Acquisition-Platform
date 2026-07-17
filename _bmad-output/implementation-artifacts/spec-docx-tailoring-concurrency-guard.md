---
title: 'Docx-tailoring concurrency guard'
type: 'feature'
created: '2026-07-17'
status: 'done'
route: 'one-shot'
---

# Docx-tailoring concurrency guard

## Intent

**Problem:** Two browser tabs or sessions both seeing a valid docx cache and both clicking "Regenerate" for the same job both bypassed the cache, both called the LLM, and both overwrote the same docx files and `jobs.db` tailoring columns — last write wins, silently discarding the other session's LLM output and API spend.

**Approach:** A DB-backed advisory lock (`jobs.tailoring_lock_started_at`), claimed atomically before `_tailor_docx_for_job`'s entire body (cache-check included) and released in a `finally`. Review caught a critical bug in the first pass: an unconditional release let a slow original holder's delayed release clobber a legitimate reclaimer's still-live lock once the original went stale — fixed by adding a caller-private ownership token (`jobs.tailoring_lock_token`), so release only clears the lock it still owns. Review also caught `jobs/db.py`'s `connect()` was missing the `PRAGMA busy_timeout` every sibling DB module already sets, despite the SPEC citing that exact precedent — added and verified with a real two-connection lock-contention test.

## Suggested Review Order

**The fix and the bug it almost introduced**

- The ownership-token design — this is the load-bearing correctness fix the review forced.
  [`db.py:287`](../../src/jobs/db.py#L287), [`db.py:335`](../../src/jobs/db.py#L335)

- The `busy_timeout` PRAGMA this diff added to match sibling DB modules.
  [`db.py:85`](../../src/jobs/db.py#L85)

- How the lock wraps the whole cache-check-included call.
  [`cli.py:470`](../../src/jobs/cli.py#L470)

**Tests**

- The reclaim-then-delayed-release test is the one that reproduces the exact bug the review found (mutation-tested to confirm).
  [`test_jobs_db.py`](../../tests/test_jobs_db.py), [`test_jobs_cli.py`](../../tests/test_jobs_cli.py)
