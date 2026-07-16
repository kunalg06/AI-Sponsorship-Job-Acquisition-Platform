---
id: SPEC-cv-upload-content-hash-idempotency
companions: ["../../project-context.md"]
sources: ["../../implementation-artifacts/deferred-work.md"]
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# CV upload content-hash idempotency

## Why

A pain to solve, flagged by both Blind Hunter and Edge Case Hunter reviews of `spec-admin-destructive-safety.md`. `views/admin.py`'s CV-upload idempotency guard keys off `uploaded_file.file_id` — a Streamlit upload-widget identity stable only for the file currently held by that widget instance. Re-selecting the identical file via the OS file picker produces a new `file_id` and bypasses the guard, allowing a genuine duplicate profile row and a second Gemini charge. The original review called the real fix (hashing `raw_text`) a design tradeoff, since it requires eagerly extracting text on every render just to compute the comparison key — changing when a corrupt file fails (immediately on upload instead of after clicking the button). That tradeoff doesn't apply when hashing the raw uploaded bytes instead: `UploadedFile.getvalue()` returns the full byte buffer without consuming the read cursor or parsing anything, so it can't fail the way text extraction can.

## Capabilities

- **CAP-1**
  - **intent:** The CV-upload idempotency guard recognizes a re-selected file as already-registered by its actual content, not the upload-widget's transient identity, so re-picking the identical file via the OS file picker no longer bypasses the guard.
  - **success:** Uploading a file, registering it, then re-selecting the byte-identical file via a fresh `file_uploader` interaction (a new `file_id`, same bytes) shows the same already-registered state (button disabled, info message) that re-clicking the still-held original upload already shows today.

## Constraints

- Hash the raw uploaded bytes via `uploaded_file.getvalue()`, not the extracted text — must not introduce any new failure mode or change when in the flow a failure can occur (matches today's exact error-timing).
- Session-state key renamed from `last_registered_cv_file_id` to a hash-based name (e.g. `last_registered_cv_hash`) and used consistently at both the `already_registered` check and the mark-as-registered step — no site keeps comparing against `file_id`.
- The existing double-click guard (`cv_registration_in_progress` gating, the `disabled=` re-check) is unchanged — this only changes what identity the guard compares, not the guard mechanism itself.

## Non-goals

- No change to the supersede-profile confirmation dialog or its own dismiss/idempotency handling (`spec-cv-supersede-dialog-dismiss-fix`'s scope) — orthogonal, this only changes how a duplicate upload is detected before that dialog is ever reached.
- No persistence of the hash beyond the current `session_state` (e.g. no DB column recording every registered file's hash) — matches today's scope (`last_registered_cv_file_id` is also session-only).

## Success signal

Re-selecting the same CV file — whether by re-clicking the still-held upload or picking it again fresh from disk — is always recognized as already registered, closing the gap that let a duplicate profile row and a second Gemini charge slip through.
