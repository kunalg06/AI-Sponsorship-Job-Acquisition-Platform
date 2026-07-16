---
title: 'Sponsor register busy_timeout tuning'
type: 'chore'
created: '2026-07-16'
status: 'done'
route: 'one-shot'
---

# Sponsor register busy_timeout tuning

## Intent

**Problem:** `register/db.py`'s `PRAGMA busy_timeout = 5000` was copied from `mcp_server/tools.py`'s convention without ever being measured against `replace_all()` — the ~142k-row full register wipe+reload it protects.

**Approach:** Measured `replace_all()` directly against the real local `data/sponsors.db` (3 trials: 553.7/614.9/635.3ms), bumped `register/db.py`'s value to a named `BUSY_TIMEOUT_MS = 15000` constant (~24x the worst trial), and added tests covering both throughput and — the part a duration-only test never proves — actual lock-contention behavior. Review caught a critical bug: `mcp_server/tools.py`'s `check_sponsor()` opened its connection via this same `register.db.connect()` and then silently re-downgraded the timeout back to 5000 on that connection, defeating the fix for exactly the concurrent-reader path most likely to race an admin-triggered refresh.

## Suggested Review Order

**The fix**

- The reasoned, measured value and its honest tradeoff (contention now waits up to 3x longer, in exchange for margin on unmeasured deploy infrastructure).
  [`db.py:60`](../../src/register/db.py#L60)

- The critical catch: a redundant `PRAGMA` re-execution was silently undoing this fix for the MCP concurrent-reader path.
  [`tools.py:99`](../../src/mcp_server/tools.py#L99)

**Tests**

- The real test of what `busy_timeout` is for — a second connection waits out a held lock instead of erroring.
  [`test_ingest.py:154`](../../tests/test_ingest.py#L154)

- Throughput baseline against realistic (nullable-field, varied-length) synthetic data, tied to the named constant rather than a decoupled literal.
  [`test_ingest.py:203`](../../tests/test_ingest.py#L203)
