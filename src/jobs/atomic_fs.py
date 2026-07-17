"""Shared directory-fsync helper for jobs.cli._atomic_write_text and
jobs.docx_tailor._atomic_write_bytes - a standalone leaf module (only
touches os/Path) so both can import it without the circular-import risk
that keeps their own atomic-write functions from importing each other."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _fsync_directory(dir_path: Path) -> None:
    """Best-effort: flush the directory entry itself (not just a file's own
    data) after a rename, on POSIX only (`os.open` on a directory raises
    `PermissionError` on Windows - skipped there, matching prior behavior
    exactly, not a portability gap since Windows never had this guarantee).

    Deliberately swallows its own failure (diagnostic to stderr only, never
    raises) rather than propagating - unlike a failure earlier in an atomic
    write, a directory-fsync failure happens *after* the caller's rename
    already succeeded, so treating it as a write failure would be wrong:
    callers of `_atomic_write_text`/`_atomic_write_bytes` (e.g.
    `_draft_and_store_outreach`) assume any exception from those functions
    means nothing was written, and tell the operator so. This keeps that
    assumption true - a directory-fsync issue degrades to "the rename may
    not survive a crash in the next instant," not "the write failed."
    """
    if os.name != "posix":
        return
    try:
        fd = os.open(str(dir_path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        print(f"Warning: could not fsync directory {dir_path} after a rename: {exc}", file=sys.stderr)
