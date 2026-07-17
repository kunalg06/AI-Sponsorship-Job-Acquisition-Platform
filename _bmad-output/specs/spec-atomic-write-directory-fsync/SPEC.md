---
id: SPEC-atomic-write-directory-fsync
companions: ["../../project-context.md"]
sources: ["../../implementation-artifacts/deferred-work.md"]
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Atomic write directory fsync

## Why

A pain to solve, flagged in the Blind Hunter adversarial review of `spec-atomic-file-writes.md`. `_atomic_write_text` (`src/jobs/cli.py`) and `_atomic_write_bytes` (`src/jobs/docx_tailor.py`) both fsync the temp file's data before `os.replace()`, but never fsync the containing directory after the rename — a crash immediately after the rename but before the OS flushes directory metadata can still lose it on POSIX. The original review declined to fix this, reasoning a portable implementation was too complex since POSIX directory-fd fsync has no direct Windows equivalent — verified empirically (`os.open(dir, os.O_RDONLY)` raises `PermissionError` on this Windows dev machine). But the fix doesn't need to be portable, only POSIX-gated: this project's actual deploy target includes Streamlit Community Cloud, which runs Linux containers, so the gap is real for the code even though it was never POSIX-tested locally.

## Capabilities

- **CAP-1**
  - **intent:** On POSIX, `_atomic_write_text`'s temp-then-rename durability guarantee extends to the directory entry itself, not just the file's data, so a crash immediately after the rename can't lose it.
  - **success:** On a POSIX system, the parent directory is opened and fsync'd after a successful `os.replace()`; on Windows this step is skipped entirely with no behavior change and no error. Both verified via unit tests using `os.name`/`os.open`/`os.fsync` mocking, not a real POSIX machine.

- **CAP-2**
  - **intent:** The identical fix applies to `_atomic_write_bytes` (`docx_tailor.py`), which mirrors `_atomic_write_text`'s design for binary content.
  - **success:** Same as CAP-1, verified against `_atomic_write_bytes`'s own code path.

## Constraints

- Guard with `os.name == "posix"`, not a try/except swallowing the Windows `PermissionError` — an explicit platform check is clearer than relying on a caught exception to distinguish "not supported here" from "a real failure on a POSIX system."
- A directory-fsync failure on POSIX propagates as `OSError`, matching how a failure earlier in the same function already propagates — this helper's whole point is a durability guarantee, so a failure in the new step must not be silently swallowed.
- Both `_atomic_write_text` and `_atomic_write_bytes` get the identical fix, matching their existing mirrored-design relationship (`docx_tailor.py`'s own docstring already says it mirrors `cli.py`'s design).

## Non-goals

- No attempt at a Windows equivalent (e.g. via `ctypes`/Win32 flush APIs) — Windows behavior is unchanged, still file-data fsync only, matching today exactly.
- No change to temp-file naming, cleanup-on-failure, or any other part of the existing atomic-write pattern — purely additive, one new step after a successful rename.

## Success signal

On a Linux deploy (e.g. Streamlit Community Cloud), a crash immediately after an atomic write's rename can no longer lose the rename itself, closing the one remaining durability gap in this project's atomic-write pattern.
