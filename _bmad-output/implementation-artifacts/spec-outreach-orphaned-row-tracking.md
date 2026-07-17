---
title: 'Outreach orphaned-row tracking'
type: 'feature'
created: '2026-07-17'
status: 'done'
route: 'one-shot'
---

# Outreach orphaned-row tracking

## Intent

**Problem:** A CAP-3-style outreach write failure (message metadata committed, then the `.txt` file write fails) leaves that `outreach_messages` row permanently orphaned. `_read_outreach_message_text` returned `None` for it identically to a row whose file was simply deleted later, so the Message-history UI showed the same generic "(message file not found)" caption either way.

**Approach:** A new nullable `write_failed_at` column, set by `mark_outreach_write_failed` at both write-failure sites (CLI and UI). Both Message-history expanders show a distinguishing caption when it's set. Review caught a real bug: the marker call was unwrapped inside the failure handler, so if it itself raised, that exception would replace the intended, more informative `SystemExit` — wrapped in a best-effort `try/except` at both sites, mutation-tested to confirm the masking bug is real and the fix closes it. Review also caught a missing test for `intake.py`'s generic-caption fallback and no idempotency proof past a second migration call — both added.

## Suggested Review Order

**The fix and the bug it almost introduced**

- The best-effort wrap around `mark_outreach_write_failed` — this is the load-bearing correctness fix the review forced.
  [`cli.py`](../../src/jobs/cli.py), [`ui_actions.py`](../../src/jobs/ui_actions.py)

- The marker function and the pre-existing-DB migration it needed its own path for.
  [`outreach_db.py:39`](../../src/jobs/outreach_db.py#L39), [`outreach_db.py:113`](../../src/jobs/outreach_db.py#L113)

- The two display sites showing the distinguishing caption.
  [`jobs_list.py`](../../views/jobs_list.py), [`intake.py`](../../views/intake.py)

**Tests**

- The marker-failure-survives test is the one that reproduces the exact masking bug the review found (mutation-tested to confirm).
  [`test_jobs_cli.py`](../../tests/test_jobs_cli.py), [`test_outreach_message_history_display.py`](../../tests/test_outreach_message_history_display.py)
