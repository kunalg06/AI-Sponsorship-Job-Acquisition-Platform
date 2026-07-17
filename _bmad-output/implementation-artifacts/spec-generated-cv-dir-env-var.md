---
title: 'GENERATED_CV_DIR environment variable'
type: 'feature'
created: '2026-07-17'
status: 'done'
route: 'one-shot'
---

# GENERATED_CV_DIR environment variable

## Intent

**Problem:** The CLI's `--out-dir` flags defaulted to `DEFAULT_GENERATED_CV_DIR`, but the Streamlit UI always hardcoded the same constant unmodified — a user with no way to relocate where generated files live without the CLI and UI silently disagreeing the moment they did.

**Approach:** `DEFAULT_GENERATED_CV_DIR` now reads a `GENERATED_CV_DIR` env var (falling back to the historical default), bridged from `st.secrets` on Streamlit Cloud too, mirroring `app.py`'s existing `GEMINI_API_KEY` pattern — a claim the first version of this fix made without actually implementing, caught before merge. Review also caught two real test-infrastructure bugs during implementation: `importlib.reload(jobs.cli)`-based tests corrupted other test files' already-bound references to the same shared module, and `monkeypatch.delenv` on an absent key left a pre-existing leak in this file's own `GEMINI_API_KEY` tests once external code (the secrets bridge) added the key back mid-test. Both fixed — the former by extracting a small, directly-testable `_resolve_generated_cv_dir()` function instead of reloading anything; the latter with a save/restore fixture applied to both env vars' tests.

## Suggested Review Order

**The fix and the bugs it almost introduced**

- The resolver function and why it's not just inlined into the constant.
  [`cli.py:79`](../../src/jobs/cli.py#L79)

- The Streamlit Cloud secrets bridge — added after review caught the original claim of `GEMINI_API_KEY` parity was false.
  [`app.py:38`](../../app.py#L38)

**Tests**

- The reload-avoidance and env-var-leak fixes are the load-bearing parts — both were proven necessary via live reproduction, not just asserted.
  [`test_jobs_cli.py`](../../tests/test_jobs_cli.py), [`test_app.py`](../../tests/test_app.py)
