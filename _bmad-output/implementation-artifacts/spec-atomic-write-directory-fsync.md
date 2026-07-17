---
title: 'Atomic write directory fsync'
type: 'chore'
created: '2026-07-17'
status: 'done'
route: 'one-shot'
---

# Atomic write directory fsync

## Intent

**Problem:** `_atomic_write_text`/`_atomic_write_bytes` fsync the temp file's data before `os.replace()`, but never fsync the containing directory after — a crash right after the rename could still lose it on POSIX (relevant for this project's Linux-based Streamlit Cloud deploy target, even though local dev is Windows). Previously declined as "too complex to do portably."

**Approach:** The fix doesn't need to be portable, only POSIX-gated (verified empirically: `os.open` on a directory does raise `PermissionError` on Windows). Extracted to a new shared `jobs/atomic_fs.py` module, used by both. Review caught a real semantic bug in the first pass: propagating the directory-fsync failure as `OSError` made it indistinguishable from a pre-rename failure, breaking two real callers' assumption that any exception from these functions means nothing was written — confirmed via a live repro that this would have shown an operator a false "text was not saved" message. Redesigned to be best-effort (catches its own failure, warns to stderr, never propagates), and confirmed via the same repro that the fix now degrades silently instead of misreporting.

## Suggested Review Order

**The fix and the bug it almost introduced**

- The shared helper's best-effort design — this is the load-bearing decision the review forced.
  [`atomic_fs.py:13`](../../src/jobs/atomic_fs.py#L13)

- How it's wired into `_atomic_write_text`: outside the try/except, since it can no longer raise.
  [`cli.py:240`](../../src/jobs/cli.py#L240), [`cli.py:267`](../../src/jobs/cli.py#L267)

**Tests**

- Unit-level coverage of the shared helper itself: POSIX vs. non-POSIX, and the swallow-and-warn behavior.
  [`test_atomic_fs.py:7`](../../tests/test_atomic_fs.py#L7)

- Integration-level: `_atomic_write_text`/`_atomic_write_bytes` call it with the right directory, and only after a successful rename (mutation-tested to confirm ordering is actually enforced).
  [`test_jobs_cli.py`](../../tests/test_jobs_cli.py), [`test_docx_tailor.py`](../../tests/test_docx_tailor.py)
