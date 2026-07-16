---
id: SPEC-register-busy-timeout-tuning
companions: ["../../project-context.md"]
sources: ["../../implementation-artifacts/deferred-work.md"]
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Sponsor register busy_timeout tuning

## Why

A pain to solve, flagged in the Blind Hunter adversarial review of `spec-admin-destructive-safety.md`. `register/db.py`'s `connect()` sets `PRAGMA busy_timeout = 5000`, copied from `mcp_server/tools.py`'s convention without ever measuring it against the operation it actually protects: `replace_all()`'s full `DELETE`+`INSERT` of the ~142k-row sponsor register inside one transaction. Direct measurement against the real local `data/sponsors.db` (142,235 rows, 3 trials) shows `replace_all()` takes 553.7–635.3ms — a healthy ~8x margin under 5000ms locally. But `busy_timeout` governs how long a *concurrent* reader/writer waits for `replace_all()`'s write lock to release, and this project has an aspirational Streamlit Cloud deploy target (`data/*.db` is gitignored, so a fresh cloud deploy's Admin "Refresh sponsor register now" button runs this exact 142k-row operation for real on unknown-performance shared infrastructure) — an unmeasured, environment-unaware value is fragile even though the local baseline is comfortable.

## Capabilities

- **CAP-1**
  - **intent:** `register/db.py`'s `busy_timeout` value is backed by a real, documented measurement of `replace_all()` against a realistically large register, not an unmeasured copy of an unrelated call site's convention.
  - **success:** A test seeds a synthetic dataset of at least 100k `SponsorRecord` rows, measures `replace_all()`'s wall-clock duration, and asserts it completes in well under the configured `busy_timeout` (order-of-magnitude margin, not a hair's-breadth pass) — catching a future ingest-performance regression before it erodes the safety margin.

- **CAP-2**
  - **intent:** `register/db.py`'s `busy_timeout` is set to a value with an explicit, comfortable, documented safety margin over the measured baseline, specifically for the large-scale `replace_all()` operation it protects.
  - **success:** `connect()`'s `PRAGMA busy_timeout` value is verifiably higher than the previous `5000`, with an inline comment stating the measured baseline and the reasoning for the chosen margin; the existing `test_connect_sets_busy_timeout_pragma` is updated to assert the new value.

## Constraints

- Target value: `15000` ms (~24x the measured 550–635ms baseline). `busy_timeout` only costs anything during actual lock contention (rare — single-user tool, one writer), so a generous margin has no downside; 24x comfortably covers slower/virtualized cloud disk I/O or future register growth without needing to guess a "perfect" number.
- Only `register/db.py`'s `connect()` changes — `mcp_server/tools.py`'s and `resume/db.py`'s `busy_timeout=5000` stay untouched; they protect different, much smaller single-row operations.
- The new performance test must not depend on network access or the real gov.uk CSV source — generate synthetic `SponsorRecord` rows locally, matching this codebase's existing convention of never hitting real external services in tests.
- The chosen value and its reasoning must be visible in code (an inline comment), not only in this spec.

## Non-goals

- No change to the `DELETE`+`INSERT` transaction shape itself (batching, WAL mode, incremental diffing) — this is only about the `busy_timeout` value being evidence-based, not about making `replace_all()` faster or structurally different.
- No real measurement against actual Streamlit Cloud infrastructure — not available to test from here; the safety margin is a principled buffer over the real local measurement, not a guarantee for every possible environment.
- No change to the `busy_timeout` PRAGMA in `mcp_server/tools.py` or `resume/db.py`.

## Success signal

A future contributor changing `register/db.py`'s `busy_timeout` (or the `replace_all()` transaction) has a real performance test and a documented baseline to check against, instead of an unexplained magic number copied from an unrelated module.
