---
title: 'Atomic file writes for jobs/cli.py output paths'
type: 'feature'
created: '2026-07-14'
status: 'done'
review_loop_iteration: 0
baseline_commit: '5143b441f8ebf2d0001f9ab11b781a749a9c3393'
context: ['{project-root}/_bmad-output/specs/spec-atomic-file-writes/SPEC.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** No `.txt`/`.docx` write path in `jobs/cli.py` uses a temp-file-then-rename pattern — a crash mid-write can leave a partial file that still passes "does it exist" cache checks, and an outreach-message write failure *after* its DB row already committed can silently lose the drafted text forever.

**Approach:** Add one shared `_atomic_write_text(path, content)` helper (temp file in the same directory, flush+fsync, `os.replace`) and route all four identified write sites through it; wrap the outreach draft write (the only post-DB-commit site) so a failure there raises a distinct `SystemExit` naming the text-lost/metadata-saved mismatch, using the same `SystemExit` convention `jobs/ui_actions.py` already relies on to bridge CLI errors into `st.error(...)`.

## Boundaries & Constraints

**Always:** One shared helper, reused at all four sites — no per-site reimplementation. Temp file must be a same-directory sibling of the target (e.g. `path.with_suffix(path.suffix + ".tmp")`) so `os.replace` stays a same-filesystem atomic rename. Preserve each site's existing `encoding="utf-8"` and directory-creation calls exactly. `_migrate_legacy_outreach_text`'s existing per-row `try/except OSError: warn and continue` wrapper (line 661-666) must keep working unchanged — the helper composes inside it, doesn't replace it.

**Ask First:** None expected — scope is fully bounded by the approved SPEC.md.

**Never:** Add a compensating DB-row delete/rollback for a failed outreach write (matches this codebase's insert-only convention — see SPEC.md Assumptions). Add retry/backoff logic. Touch any write path outside these four `jobs/cli.py` sites.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normal tailoring write | fresh `tailor`/docx-tailor run | `_write_tailoring_files` writes both files via the helper, unchanged output | N/A |
| Interrupted write (simulated) | `os.replace` raises mid-call | Target path keeps its prior content (or stays absent) — temp file may remain, final path never truncated | Exception propagates same as before (uncaught at CAP-1/CAP-2 sites, matching current behavior) |
| Legacy-outreach backup, one row fails | `_atomic_write_text` raises `OSError` for row N | Existing per-row handler prints a warning and continues to row N+1, unchanged from current behavior | Caught by the pre-existing `except OSError` at line 664 |
| Outreach draft write succeeds | normal `outreach`/`follow-up` run | `.txt` file written atomically, same content/path as before | N/A |
| Outreach draft write fails after DB commit | `_atomic_write_text` raises for the draft write (line 794) | `SystemExit` raised naming: message was logged (channel, char count) but its text failed to save and is lost | Caught upstream by CLI (prints and exits) or by `jobs/ui_actions.py`'s existing `except SystemExit as exc: st.error(str(exc))` |

</frozen-after-approval>

## Code Map

- `src/jobs/cli.py` -- new `_atomic_write_text` helper; all four write sites route through it; the outreach site (line 794) additionally gets a `try/except OSError` wrapper for the distinct error
- `tests/test_jobs_cli.py` -- existing home for these call sites' tests (`outreach_env` fixture at line 580 already mocks `draft_outreach_message`; `tmp_path`-based tests already cover the tailoring/migration write sites)

## Tasks & Acceptance

**Execution:**
- [x] `src/jobs/cli.py` -- add `import os`; add `_atomic_write_text(path: Path, content: str) -> None`: write to `path.with_suffix(path.suffix + ".tmp")`, flush + `os.fsync`, then `os.replace(tmp, path)` -- the one shared mechanism every site below routes through
- [x] `src/jobs/cli.py` -- `_write_tailoring_files` (lines 242-243): replace both `resume_path.write_text(...)`/`cover_letter_path.write_text(...)` calls with `_atomic_write_text(...)` -- closes CAP-1's primary tailoring path
- [x] `src/jobs/cli.py` -- `_migrate_legacy_text` (lines 535, 539): replace both `write_text(...)` calls with `_atomic_write_text(...)` -- closes CAP-1's legacy-migration path
- [x] `src/jobs/cli.py` -- `_migrate_legacy_outreach_text` (line 663, inside the existing `try/except OSError` at 661-666): replace `path.write_text(...)` with `_atomic_write_text(path, row["message"])`, leaving the surrounding warn-and-continue structure untouched -- closes CAP-2
- [x] `src/jobs/cli.py` -- outreach draft write (line 794): wrap `_atomic_write_text(path, draft.message)` in `try/except OSError as exc: raise SystemExit(...)` naming the message-id/channel/char-count and stating the text is lost -- closes CAP-3
- [x] `tests/test_jobs_cli.py` -- added `test_atomic_write_text_writes_full_content_and_leaves_no_tmp_file`, `test_atomic_write_text_leaves_prior_content_intact_when_replace_fails`, `test_cmd_outreach_write_failure_after_db_commit_raises_distinct_lost_text_error` (via the real `outreach` CLI command + `outreach_env` fixture, matching this file's stated wiring-not-helpers testing philosophy)
- [ ] `_bmad-output/implementation-artifacts/deferred-work.md` -- mark the 2 corresponding entries `status: done` with resolution evidence (files touched, test result)

**Acceptance Criteria:**
- Given any of the four write sites, when the underlying `os.replace` call fails, then the target path never contains truncated/partial content.
- Given the legacy-outreach backup write fails for one row, when migration continues, then the existing warn-and-continue behavior for subsequent rows is unchanged.
- Given the outreach draft write fails after `insert_outreach_message` has already committed, when the failure is raised, then the error explicitly states the drafted text was lost even though its metadata (channel, char count) was saved.
- Given all four sites succeed normally, when their respective commands run, then output content and file paths are unchanged from current behavior.

## Spec Change Log

- Round-1 review (Blind Hunter + Edge Case Hunter, 2026-07-14) surfaced 5 real issues, auto-fixed as `patch` (no spec/intent change):
  1. The temp filename (`path.with_suffix(path.suffix + ".tmp")`) was static/deterministic per target path — two overlapping writers to the same path would share one tmp file and could interleave/corrupt it before either `os.replace` ran, defeating the atomicity guarantee. Fixed by naming each tmp file `{target.name}.{pid}.{uuid4().hex}.tmp` (also removes the undocumented one-suffix-component assumption `with_suffix` implied).
  2. Any failure before `os.replace` (open/write/flush/fsync) or during `os.replace` itself left an orphaned `.tmp` sibling with nothing to clean it up — over repeated failed runs (e.g. the legacy-outreach migration's per-row loop) these could accumulate silently. Fixed with a `try/except (OSError, ValueError): tmp.unlink(missing_ok=True); raise` wrapper; added tests asserting no `.tmp` remains after both a write-stage and a replace-stage simulated failure.
  3. The outreach draft-write's `except OSError` wouldn't catch a `ValueError` (e.g. `UnicodeEncodeError`, a `ValueError` subclass, from pathological string content) — broadened to `except (OSError, ValueError)` in both the helper and the site-4 call.
  4. `draft.message` is sitting in memory at the exact moment CAP-3's failure is caught, but nothing printed it before exiting — the operator was forced to redraft from scratch (a non-deterministic, LLM-backed call) to recover text that was one `print()` away. Fixed by printing the drafted text before raising `SystemExit`; the exit message now says "printed above for manual recovery" instead of implying the text is unrecoverable.
  5. A new test's docstring referenced a nonexistent `_draft_and_save_outreach` — corrected to the real name, `_draft_and_store_outreach`.
  Also added one test closing a coverage gap the reviewers correctly identified: the original failure test only simulated `os.replace` raising, not the write/fsync step where a real `ENOSPC` more realistically surfaces — added `test_atomic_write_text_leaves_prior_content_intact_and_cleans_up_tmp_when_fsync_fails` to cover that half of the helper's error path, plus a test confirming successive calls get distinct tmp filenames.
  Also added one code comment (no behavior change): a note at `_write_tailoring_files` explaining why sites 1/2 deliberately don't get new exception handling while site 4 does — this was already documented in this spec's Design Notes but a reviewer reasonably wanted it visible in the code itself.
  6 findings judged real but out of this spec's committed scope were logged to `deferred-work.md` instead of patched: no directory-fsync (matches the `memlog.py` precedent this helper mirrors, which also omits it, plus Windows-portability concerns); `_write_tailoring_files` writing its resume/cover-letter pair as two independent atomic writes rather than one atomic pair; no permanent way to distinguish a "known write failure" orphaned DB row from a file missing for any other reason; `docx_tailor.py`'s `document.save(...)` and its own DB-commit-after-write desync, entirely unhardened; and `views/ui_actions.py`'s `draft_and_save_outreach` having the identical unguarded write as the CLI path this spec just fixed.
  2 findings rejected: `_migrate_legacy_text`'s per-row loop could already be aborted by an uncaught `OSError` from `write_text()` before this diff — not a regression this diff introduced. Real-filesystem/Windows-specific OS-level integration testing (vs. mocked failure injection) was judged a methodology preference already consistent with this codebase's existing test conventions (Gemini calls mocked, DB layer uses real SQLite via `tmp_path`), not a defect.

## Suggested Review Order

- Entry point: the one shared atomic-write primitive every site below routes through — unique per-call tmp naming (fixes a concurrent-writer collision a review round caught) and cleanup-on-any-failure.
  [`cli.py:239`](../../src/jobs/cli.py#L239)

- First call site: straightforward swap from `write_text` to the atomic helper, plus a comment explaining why this site deliberately doesn't get new exception handling (only the outreach site does — see below).
  [`cli.py:263`](../../src/jobs/cli.py#L263)

- The one site with new exception-handling behavior, not just atomicity: this write runs *after* its DB row already committed, so a failure here gets a distinct message instead of a generic one — and the drafted text is printed before exiting so a failure doesn't force a costly LLM re-draft to recover it.
  [`cli.py:828`](../../src/jobs/cli.py#L828)

- Legacy-outreach backup write, inside its pre-existing per-row `try/except OSError: warn and continue` loop — the atomic helper composes with that structure unchanged.
  [`cli.py:567`](../../src/jobs/cli.py#L567)

**Tests**

- New coverage for the helper's two distinct failure surfaces (write/fsync vs. replace) and the tmp-naming uniqueness a review round asked for.
  [`test_jobs_cli.py:835`](../../tests/test_jobs_cli.py#L835)

- The outreach failure-path test, now also asserting the recovered text was printed to stdout.
  [`test_jobs_cli.py:896`](../../tests/test_jobs_cli.py#L896)

## Design Notes

`_atomic_write_text` mirrors `_bmad/scripts/memlog.py`'s own `write_atomic()` (temp + flush + fsync + `os.replace`, same directory) — an existing, working precedent in this project, not a novel pattern. The outreach site is the only one that gets new *exception handling*, not just atomicity: today `path.write_text(...)` at line 794 is unguarded, so any failure already propagates (crashes the CLI / bubbles to the UI's existing `SystemExit` handler) rather than vanishing silently — the real gap is that the resulting message is generic, not that nothing surfaces at all. The fix's job is to make that message specific enough that the operator understands the DB row now refers to lost text, not to invent error visibility that didn't exist before.

## Verification

**Commands:**
- `python -m pytest tests/test_jobs_cli.py -v` -- expect all existing tests plus the new atomic-write/failure-path tests to pass
- `python -m pytest -v` (via `--ignore=tests/test_mcp_server.py`, same fallback-environment caveat as the previous session's work) -- expect no regressions

**Manual checks (if no CLI):**
- None needed -- this is pure CLI/library logic with full unit-test coverage, unlike the Admin-page UI work; no Streamlit involved.
