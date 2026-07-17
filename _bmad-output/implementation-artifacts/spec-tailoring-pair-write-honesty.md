---
title: 'Tailoring pair write honesty'
type: 'bugfix'
created: '2026-07-17'
status: 'done'
route: 'one-shot'
---

# Tailoring pair write honesty

## Intent

**Problem:** `_write_tailoring_files` writes the resume and cover-letter `.txt` files as two independent atomic writes. If the resume write succeeds and the cover-letter write then fails, a mismatched pair was left on disk with no distinguishing message.

**Approach:** Two design passes. First pass (rejected before merge): delete the just-written resume file on cover-letter failure, to restore "neither file exists." Review caught this was itself buggy on a re-run — deleting the fresh resume left "no resume + stale old cover letter," worse than the original bug. Redesigned: no deletion at all — leave both files exactly as they land, print both pieces of generated text for manual recovery, and raise `SystemExit` naming which file is fresh and which is stale/absent. A second review round on the corrected design found no repeat of the original bug class, but caught missing `ValueError` coverage, a weaker CLI-integration test than the direct-call tests, and no proof the "just re-run" advice actually works — all closed with new tests, including a fail-then-retry round-trip.

## Suggested Review Order

**The fix and the design reversal it went through**

- The corrected `_write_tailoring_files` and its comment explaining why the first design was rejected.
  [`cli.py:297`](../../src/jobs/cli.py#L297)

**Tests**

- The first-run vs. re-run distinction, and the retry round-trip, are the ones that prove the corrected design actually holds.
  [`test_jobs_cli.py`](../../tests/test_jobs_cli.py)
