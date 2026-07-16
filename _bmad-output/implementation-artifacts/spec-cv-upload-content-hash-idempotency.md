---
title: 'CV upload content-hash idempotency'
type: 'bugfix'
created: '2026-07-17'
status: 'done'
route: 'one-shot'
---

# CV upload content-hash idempotency

## Intent

**Problem:** `views/admin.py`'s CV-upload idempotency guard keyed off `uploaded_file.file_id` — a Streamlit upload-widget identity stable only for the file currently held by that widget instance. Re-selecting the identical file via the OS file picker produced a new `file_id` and bypassed the guard, risking a duplicate profile row and a second Gemini charge. The original review called the real fix (hashing text) a tradeoff, since it requires eagerly extracting text just to compute the comparison key.

**Approach:** That premise didn't hold for a content hash computed over the raw bytes: `UploadedFile.getvalue()` returns the full buffer as a pure in-memory operation with no parsing and no possible failure mode, so it introduces no error-timing change at all. Replaced the `file_id`-keyed session state with a `sha256`-keyed one. Review caught that the initial tests only hand-seeded the hash and never proved the write side or the "fresh selection mints a new `file_id`" claim (asserted only in prose) — added an end-to-end test through the real registration path, mutation-tested to confirm it catches a write-path regression. Also softened an overclaiming code comment and documented one accepted residual limitation (raw-byte hashing doesn't catch two files with identical visible content but different bytes).

## Suggested Review Order

**The fix**

- The content-hash computation and the comparison, including the accepted residual-limitation note.
  [`admin.py:182`](../../views/admin.py#L182), [`admin.py:184`](../../views/admin.py#L184)

**Tests**

- The real proof: drives registration through the actual page, verifies the write side stores a matching hash, and verifies (not just asserts in a comment) that a fresh re-selection mints a new `file_id` for identical bytes — mutation-tested to confirm it catches a write-path regression.
  [`test_admin.py:124`](../../tests/test_admin.py#L124)

- Fast supplementary check of the read/comparison side in isolation.
  [`test_admin.py:104`](../../tests/test_admin.py#L104)
