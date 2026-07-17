---
id: SPEC-tailoring-pair-write-honesty
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Tailoring pair write honesty

## Why

A pain to solve. `_write_tailoring_files` (`src/jobs/cli.py:297`) writes the resume and cover-letter `.txt` files as two independent atomic writes, not one atomic pair. If the resume write succeeds and the cover-letter write then fails, a mismatched pair is left on disk — a new resume alongside a stale cover letter from a previous run (or nothing, on a first run) — with nothing distinguishing it from a genuinely successful run.

A first-pass design (delete the just-written resume file on cover-letter failure) was implemented and then rejected after adversarial review: on a re-run (the job already tailored before, both files pre-existing), deleting the resume left "no resume + stale old cover letter" — strictly worse than the original bug, since the fresh resume text was gone and nothing could restore the cover letter's own prior content. That design's premise ("no old content worth restoring") only held for a first-ever tailor of a job_id, not a re-run.

## Capabilities

- **CAP-3** (supersedes an earlier, rejected CAP-1/CAP-2 pair — see `.memlog.md`)
  - **intent:** When the cover-letter write fails after the resume write already succeeded, `_write_tailoring_files` leaves both files exactly as they land (resume fresh, cover letter untouched), prints both pieces of generated text for manual recovery, and raises `SystemExit` naming which file is fresh and which is stale/absent — it never deletes anything.
  - **success:** Simulating a cover-letter failure on both a first run (cover letter absent before and after) and a re-run (cover letter's old content unchanged) — in both cases the resume holds this call's fresh text, the cover letter is provably untouched, and the printed output contains both generated texts.

## Constraints

- Must not attempt to restore or fabricate the cover letter's prior content — only report the true, current state of both files honestly.
- Must not change this function's existing behavior for the resume write itself: if it fails, both paths are already left exactly as they were before the call (per `_atomic_write_text`'s own contract), and the exception propagates as a bare `OSError`/`ValueError`, unchanged.
- The `SystemExit` raised on cover-letter failure is a deliberate, new asymmetry from the resume-write branch (which still raises a bare `OSError`/`ValueError`) — `_cmd_tailor`, the only current caller, doesn't catch either type, so this is currently harmless, but it's a real contract a future caller must respect.

## Non-goals

- Not a two-phase-rename or manifest system that restores the old cover-letter content on failure — not needed given `_cmd_tailor` is always uncached and a retry regenerates both files fresh from a new LLM call.
- Not touching the docx path (`_tailor_docx_for_job`/`build_tailored_docx`/`write_plain_docx`) — a separate write pair with its own cache-check semantics, out of scope for this specific deferred-work entry, which named `_write_tailoring_files` (the plain-text `tailor` command's path) specifically.

## Success signal

A test simulates the cover-letter write failing after the resume write succeeds, on both a first run and a re-run, and asserts in both cases: the resume holds the fresh content, the cover letter is unchanged from before the call, both generated texts were printed, and a retry after the failure (with the underlying write working again) produces a clean, fully-matched pair.
