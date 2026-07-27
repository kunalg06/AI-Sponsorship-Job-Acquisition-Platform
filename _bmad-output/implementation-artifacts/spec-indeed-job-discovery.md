---
title: 'Automated Indeed job discovery queue'
type: 'feature'
created: '2026-07-27'
status: 'done'
review_loop_iteration: 0
context: ['{project-root}/_bmad-output/specs/spec-indeed-job-discovery/SPEC.md', '{project-root}/_bmad-output/specs/spec-indeed-job-discovery/job-source-evaluation.md']
baseline_commit: '365c46d4fe5ee6c727fff7b346519bd6e89551f3'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The user is racing a 136-day UK sponsorship deadline while also studying for interviews, so manually searching Indeed for sponsor-eligible roles competes with that study time. Job #18 (85/100 match) already sat forgotten in the manual pipeline for weeks until caught by chance.

**Approach:** Discovered Indeed postings are inserted directly into the existing `jobs` table (via the same sponsor-check/salary-check/match-score pipeline `jobs intake` already runs) with new source-tracking columns, so nothing is duplicated or forked. A new "Automate" page lists unreviewed Indeed-sourced rows as a review queue; marking one reviewed just clears a flag - it then behaves exactly like a manually-pasted job everywhere else in the app.

## Boundaries & Constraints

**Always:**
- Reuse the existing `_run_sponsor_check`/`_run_salary_check`/`_run_match_score` pipeline unmodified - no forked scoring logic for Indeed-sourced rows.
- Every Indeed-sourced row carries a `source_job_id`, uniquely enforced (partial unique index, NULLs excluded) so the same posting can never be staged twice across repeated searches.
- Applying stays a manual click on the real Indeed apply link; no code path in this feature submits an application.

**Ask First:** None - the open questions from the source SPEC (default search terms, 85% hard-filter vs. show-all, staging retention, where the schedule lives) are resolved below in Design Notes per the user's explicit direction to resolve them during build.

**Never:**
- No automated application submission.
- No visasponsor.jobs, LinkedIn, or Glassdoor integration - see `job-source-evaluation.md` (Terms-of-Service and account-ban risk, respectively).
- No change to the existing manual paste-in `jobs intake` flow.
- Not building the actual `/schedule` cron routine as code in this repo - creating it is a manual, one-time operational step done after this ships (same category as this project's existing Turso-account-creation precedent).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | New `source_job_id`, title/company/location/posted-date/apply-url, full description text | New `jobs` row inserted with `source='indeed'`, sponsor/salary/match verdicts populated, `discovery_reviewed_at` NULL | N/A |
| Duplicate posting | Same `source_job_id` staged twice (repeat daily search) | Second attempt is a no-op | Catches the unique-index `IntegrityError`, prints a friendly "already staged" message, no crash |
| No resume on file | `stage-indeed` run before any profile exists | Row still inserted with sponsor/salary populated | Match score skipped, matching `_run_match_score`'s existing no-profile behavior |
| Mark reviewed | User clicks "Mark Reviewed" in the Automate view | Row disappears from the Automate queue | Row remains fully visible/unchanged in Jobs List - only `discovery_reviewed_at` changes |

</frozen-after-approval>

## Code Map

- `src/jobs/db.py` -- add nullable `source`, `source_job_id`, `source_posted_at`, `discovery_reviewed_at` columns to `SCHEMA`; add a partial unique index on `source_job_id`; add `mark_discovery_reviewed(conn, job_id)` and `list_discovery_queue(conn)`.
- `src/jobs/cli.py` -- new `stage-indeed` subcommand: builds a `JobExtraction`-equivalent directly from Indeed's already-structured fields (no `extract_job` LLM call needed), calls `insert_job` with the new source columns, then runs the existing `_run_sponsor_check`/`_run_salary_check`/`_run_match_score` exactly as `_cmd_intake` does.
- `views/automate.py` (new) -- lists `list_discovery_queue(conn)`, sorted match-score desc then posted-date desc; each row shows title/company/location/posted-date/sponsor+salary+match badges (mirrors `views/jobs_list.py`'s badge rendering) + an apply-link button + a "Mark Reviewed" button.
- `app.py` -- register `views/automate.py` in `st.navigation(...)`.
- `tests/test_jobs_cli.py` -- tests for `stage-indeed` (happy path, duplicate `source_job_id`, no-profile-on-file).
- `tests/test_jobs_db.py` -- tests for the unique index, `mark_discovery_reviewed`, `list_discovery_queue` ordering.
- `tests/test_automate_view.py` (new, `AppTest`-based, mirrors `tests/test_views_error_display.py`'s pattern) -- renders the queue, exercises "Mark Reviewed".

## Tasks & Acceptance

**Execution:**
- [x] `src/jobs/db.py` -- add the 4 nullable columns + partial unique index (`CREATE UNIQUE INDEX ... WHERE source_job_id IS NOT NULL`) + `mark_discovery_reviewed`/`list_discovery_queue` -- foundation for everything else.
- [x] `src/jobs/cli.py` -- add `stage-indeed` subcommand, reusing the existing `_run_*_check` helpers -- the one new pipeline entry point, callable both by a scheduled agent and live-session fallback.
- [x] `views/automate.py` -- new review-queue page.
- [x] `app.py` -- register the new page.
- [x] Tests for all of the above, including the I/O matrix's edge cases.

**Acceptance Criteria:**
- Given a fresh `source_job_id` and full posting text, when `jobs stage-indeed` runs, then a `jobs` row exists with `source='indeed'`, sponsor/salary/match verdicts populated, and `discovery_reviewed_at` NULL.
- Given that same `source_job_id` staged again, when `jobs stage-indeed` runs a second time, then no duplicate row is created and a friendly message prints instead of a crash.
- Given at least one unreviewed Indeed-sourced job, when the Automate page loads, then it appears sorted after higher-match-score/newer-posted rows, with working sponsor/salary/match badges and a working apply link.
- Given a row in the Automate queue, when "Mark Reviewed" is clicked, then the row no longer appears in Automate but is unchanged and visible in Jobs List.

## Spec Change Log

(none - no bad_spec loopback occurred in this run)

## Design Notes

Resolving the source SPEC's open questions, per the user's direction to resolve them during build rather than block on them:

- **Default search terms:** derive keywords from the distinct `job_title` values already in `jobs` (the user's own real target roles - AI Engineer, Data Scientist, ML Engineer, Software Engineer, etc.) rather than hardcoding a list or adding a new profile-parsing LLM call. Location defaults to "United Kingdom" / remote, `country_code="GB"`.
- **85% hard-filter vs. show-all:** show all unreviewed candidates with the match score visible and the list sorted by it, rather than hard-filtering at an unvalidated 85 - mirrors this codebase's "never hide data, let the human decide" convention (e.g. `CANNOT_VERIFY` instead of forcing a guessed sponsor verdict) and matches Mary's point that the existing 70 `strong_match` threshold was itself never validated against real outcomes.
- **Staging retention:** no expiry/cleanup in this pass - unreviewed rows simply persist (same insert-only convention as every other table here); revisit only if the queue grows large enough to matter in practice.
- **Where the schedule runs from:** the `/schedule` skill creates a recurring Claude Code cloud routine whose prompt calls Indeed's `search_jobs`/`get_job_details` MCP tools directly (only reachable from a Claude session, never from the deployed Streamlit app) and shells out to `jobs stage-indeed` per new result. The same prompt, run live in a session on request, is the fallback path - identical code, different trigger. Setting this schedule up is a manual step after this spec's code ships, not a file in this repo.

A bigger simplification versus the originating discussion: no separate "staging table" exists. `jobs` already has everything a staging table would need (insert-once rows, nullable status columns) - Indeed-sourced rows land directly in `jobs`, fully scored, and "review" is just clearing `discovery_reviewed_at`. This satisfies "reuse the pipeline unmodified" more completely than a separate table-plus-copy step would, and the unique index on `source_job_id` is what actually prevents duplicates - a real DB constraint, not application-level bookkeeping.

## Verification

**Commands:**
- `uv run pytest tests/test_jobs_cli.py tests/test_jobs_db.py tests/test_automate_view.py -q` -- expected: all pass, including new ones.
- `uv run pytest -q` -- expected: full suite passes, no regressions.

**Manual checks:**
- Run `jobs stage-indeed` once locally against a real fetched Indeed posting, confirm the row appears correctly in both the new Automate page and the existing Jobs List.

## Suggested Review Order

**Entry point / pipeline reuse**

- New pipeline entry point: no `extract_job` LLM call, reuses the existing three check helpers unmodified.
  [`cli.py:241`](../../src/jobs/cli.py#L241)
- No-op-vs-crash: verified live that `libsql` raises a bare `ValueError` (not `sqlite3.IntegrityError`) for a UNIQUE violation.
  [`cli.py:305`](../../src/jobs/cli.py#L305)

**Schema / dedup**

- Deliberately a separate statement from `SCHEMA`, run only after `_ensure_columns`, so the migration path for a pre-existing DB stays correct.
  [`db.py:82`](../../src/jobs/db.py#L82)
- `source`/`source_job_id` cross-validated so a future caller can't silently bypass the dedup guarantee.
  [`db.py:118`](../../src/jobs/db.py#L118) → [`db.py:138`](../../src/jobs/db.py#L138)

**Review queue behavior**

- Excludes rows already applied/discarded elsewhere, and caps at 20 so an unattended agent can't produce an unbounded queue.
  [`db.py:479`](../../src/jobs/db.py#L479)
- Scoped to `source = 'indeed'` so a non-Indeed id can never be marked reviewed.
  [`db.py:463`](../../src/jobs/db.py#L463)

**UI / disclosure**

- Sponsor-check caveat: discloses the agency-vs-employer limitation instead of presenting it as equally reliable to a manually-pasted job.
  [`automate.py:73`](../../views/automate.py#L73)
- Honest queue-size caption — never implies a false total.
  [`automate.py:61`](../../views/automate.py#L61)
- "Mark Reviewed" clears the one timestamp column; nothing else changes.
  [`automate.py:92`](../../views/automate.py#L92)

**Wiring**

- New subcommand registration and its required/validated args (`--posted-date`, `--apply-url`, `--source-job-id`).
  [`cli.py:1313`](../../src/jobs/cli.py#L1313)
- Page registered in the app's navigation.
  [`app.py:89`](../../app.py#L89)
