---
id: SPEC-docx-and-ui-outreach-atomic-writes
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Docx and UI-Outreach Atomic Writes

## Why

The prior atomic-file-writes hardening (`spec-atomic-file-writes.md`) fixed four write sites in `jobs/cli.py`, but both of its adversarial reviewers (2026-07-14) independently found the exact same root cause left unaddressed in two other paths: `docx_tailor.py`'s `.docx` writes have no atomic-replace protection at all — arguably the higher-traffic path since it serves UI downloads, and a `.docx` zip container is more fragile under a partial write than plain text — and `views/ui_actions.py`'s `draft_and_save_outreach` is the Streamlit UI's own copy of the CLI's outreach-drafting flow, with the identical committed-DB-row-then-file-write sequence that was just hardened in the CLI path but left untouched here, even though the UI is likely the primary way a user actually drafts outreach.

## Capabilities

- **CAP-1**
  - **intent:** `build_tailored_docx` and `write_plain_docx` can never leave a partial/corrupt `.docx` file at their target path if the write is interrupted.
  - **success:** A write interrupted partway through either function leaves the target path either fully absent, with its complete prior content, or with the complete new content — never a truncated/corrupt zip container.

- **CAP-2**
  - **intent:** `draft_and_save_outreach`'s message write can never leave a partial file if interrupted, and if it fails after its DB row has already committed, the operator gets an error whose displayed message includes the drafted text — recoverable via the existing `st.error(str(exc))` pattern the calling views already use — instead of a generic failure with the text unrecoverably gone.
  - **success:** A write interrupted at this site leaves the target path either absent or fully complete, never truncated. A simulated failure at this specific site (post-DB-commit) raises a `SystemExit` whose message names the text-lost/metadata-saved mismatch and contains the full drafted text.

## Constraints

- CAP-1's atomic-write helper must be implemented locally inside `docx_tailor.py` (same temp-file-then-`os.replace` mechanism, pid+uuid-suffixed same-directory tmp naming, cleanup-on-failure — mirroring `jobs.cli._atomic_write_text`'s design exactly), not imported from `jobs.cli` — `jobs/cli.py` already imports `docx_tailor`, so the reverse import would be circular.
- CAP-1 must save via an in-memory `io.BytesIO()` buffer first (`Document.save()` accepts a file-like stream), then atomic-write those bytes to the final path — `document.save()` has no atomic-replace option when writing directly to a path string.
- CAP-2 must reuse `jobs.cli._atomic_write_text` directly, not reimplement it — matches this codebase's established "views import CLI-layer helpers directly" convention (`ui_actions.py` already imports several `_`-prefixed helpers from `jobs.cli`) and keeps the single-shared-mechanism principle from the prior spec.
- No new dependencies — `io.BytesIO` plus the existing temp-naming/replace pattern are stdlib-only.
- Preserve existing directory-creation behavior at each site (`out_path.parent.mkdir(...)` / `path.parent.mkdir(...)`) — this fix targets write atomicity only.

## Non-goals

- `_tailor_docx_for_job`'s `update_tailoring`-after-write ordering/desync risk — a separate, already-logged, lower-severity deferred-work item (writes happen before the DB commit here, unlike CAP-2's post-commit case).
- A way to distinguish a permanently-orphaned outreach row from a file missing for other reasons — already-logged deferred-work item, needs a schema change.
- Further changes to `jobs/cli.py`'s outreach path — already hardened; CAP-2 only extends that fix to the UI's copy.
- Directory-fsync durability — matches the prior spec's same scope decision.

## Success signal

Killing the process partway through either docx write (CAP-1) or the UI outreach write (CAP-2) never leaves a truncated/corrupt file at the target path. For CAP-2, a write failure occurring after `insert_outreach_message`'s commit raises an error whose message names the text-lost/metadata-saved mismatch and contains the drafted text itself, so a user seeing it via `st.error(...)` can still recover it by copy-paste.

## Assumptions

- CAP-2's recovery text goes inside the `SystemExit` message itself, not printed to stdout (unlike the CLI-side fix) — `print()` output only reaches the server console, invisible to a Streamlit user, while the exception message is what actually reaches them via the existing `except SystemExit as exc: st.error(str(exc))` pattern already used in `views/intake.py` and `views/jobs_list.py`. Keeps this spec from having to touch those view files.
- CAP-1 gets atomicity only, no new exception-handling — matches the prior spec's precedent for sites that don't sit downstream of a DB commit (see Non-goals: the docx writes happen *before* `update_tailoring`'s commit, not after).

## Open Questions

- None — both real ambiguities (where the recovery text surfaces for a UI user; whether CAP-1 needs new exception-handling) are resolved by the logged assumptions above.
