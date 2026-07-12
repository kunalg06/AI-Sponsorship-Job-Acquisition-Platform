---
title: 'Audit trail for MCP-triggered track_application mutations'
type: 'feature'
created: '2026-07-12'
status: 'done'
review_loop_iteration: 2
context: ['{project-root}/_bmad-output/project-context.md']
baseline_commit: 'c95f7864c20a5c04d58b025293a8eab94614789f'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `mcp_server.tools.track_application` can permanently mutate `jobs.db` (mark a job applied/discarded) with zero logging of the invocation — an MCP client (an autonomous agent) can change tracker state and there is no way afterward to reconstruct who/when/what changed, or that the change came from an agent rather than the human using the CLI/Streamlit UI directly.

**Approach:** Add a small, MCP-scoped audit table (`mcp_audit_log`) to `jobs.db`, written by `track_application` for every attempt that reaches a real DB lookup — successful mutations and unknown-job-id rejections alike — capturing timestamp, job_id, action, the job's previous `applied_status`, and the outcome. Scoped deliberately to the MCP layer only: the CLI and Streamlit UI already act with the human directly at the keyboard, so only the MCP path has the "was this even me?" gap this closes.

## Boundaries & Constraints

**Always:**
- New table lives in `jobs.db` (the same file `track_application` already connects to) but is created/managed entirely from within `src/mcp_server/` — do not add it to `jobs/db.py`'s `SCHEMA` or touch that file, keeping the audit feature self-contained to the MCP layer that owns the gap.
- Log every `track_application` attempt that reaches a DB connection: a successful mutation, an unknown-`job_id` rejection, AND a mutation call that raises partway through (e.g. `mark_applied`/`mark_discarded` itself failing) — all three get a row. An invalid `action` string is the one exception — see the **first `Never` bullet below**, added by this amendment.
- Each log row captures: UTC ISO timestamp (`datetime.now(timezone.utc).isoformat()`, matching this codebase's existing convention), `job_id` (`NOT NULL` — every logged path has a real job_id by the time a row is written), `action`, `previous_status` (the job's `applied_status` before mutation, `NULL` if the job lookup itself failed), `result` (`"success"` or `"error"`), and `error` (`NULL` on success, the exception message on failure).
- The audit INSERT for a **rejection** (unknown job_id, or the mutation call itself raising) happens *before* the `ValueError`/exception is re-raised, and a failure in that INSERT must not suppress or replace the original exception — the caller must still see the original `ValueError`/exception either way.
- The audit INSERT for a **success** must not raise back to the caller if it itself fails (e.g. a lock timeout writing the log row) — the mutation already committed, so the caller gets the correct successful return value regardless of whether logging it succeeded. Best-effort logging; the primary operation's outcome is never masked by a logging failure.
- Table creation is idempotent (`CREATE TABLE IF NOT EXISTS`) and additive-column-safe (mirror `jobs/db.py`'s `_ensure_columns()` pattern at a small scale, so a future column addition to `mcp_audit_log` doesn't break inserts against a table created by an older version of this code), following the exact pattern `jobs/db.py`'s own `connect()` already uses for the `jobs` table.

**Ask First:** none identified — the one open design question (whether to log invalid-action calls, which would require connecting before validating and so create `jobs.db` as a side effect of a call that previously had none) was resolved with the human in this session — see `Never` below and the Spec Change Log.

**Never:**
- **Do not open a DB connection to validate the `action` string.** `if action not in _ACTIONS` must stay the very first thing `track_application` does, exactly as before this feature existed — zero DB/filesystem I/O for a bad action string, no `jobs.db` created as a side effect, and consequently **no audit row is logged for this specific rejection case**. This was an intent_gap found in review: the original "log every invocation attempt" language conflicted with "don't change existing behavior," because logging an invalid-action call would require connecting before validating it, which creates `jobs.db` where none existed before. Resolved by carving this one case out of "log every attempt."
- Do not modify `jobs/sponsor_check.py`, `jobs/salary_check.py`, `jobs/tracker.py`, `jobs/db.py`, `jobs/outreach.py`, `jobs/outreach_db.py`, `register/*`, `views/*`, or `jobs/cli.py` — this is scoped entirely to the MCP layer's own blind spot; the CLI/UI mutation paths are out of scope (they're not the gap this closes).
- Do not add authentication, per-user identity, or multi-tenant attribution — this is a single-user local tool; "actor" is implicitly "via MCP" by virtue of which table the row is in, not a per-caller identity system.
- Do not change `track_application`'s return value, its `ValueError` messages, or its existing validation order — this is additive logging only, not a behavior change to the tool's public contract (the invalid-action check must keep running, and keep failing fast, exactly as before).
- Do not add a general-purpose application-wide audit log covering CLI/UI mutations too — deliberately narrow to the MCP-invocation gap the deferred-work item names.
- Do not claim or rely on true cross-statement atomicity between the mutation and its audit row — `mark_applied`/`mark_discarded` each commit their own transaction (`with conn:`) before the audit INSERT runs; these are two separate commits on the same connection, not one atomic unit. A crash in the narrow window between them is a known, accepted gap (see Design Notes) — do not add cross-process locking or a shared transaction to close it.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Successful mark-applied | `track_application(job_id, "applied")` on an existing job | Mutation succeeds as today; a new `mcp_audit_log` row records `job_id`, `action="applied"`, `previous_status` (prior value), `result="success"`, `error=NULL` | No error expected |
| Successful mark-discarded | `track_application(job_id, "discarded")` on an existing job | Same as above with `action="discarded"` | No error expected |
| Invalid action | `track_application(job_id, "maybe")` | `ValueError` raised as today (unchanged message), zero DB/filesystem I/O — no connection opened, no row logged, `jobs.db` not created if absent | `ValueError` still propagates to caller, unchanged from before this feature |
| Unknown job id | `track_application(999999, "applied")` | `ValueError` raised as today (unchanged message); a row is logged with `job_id=999999`, `previous_status=NULL`, `result="error"`, `error` containing "no job with id 999999" | `ValueError` still propagates to caller |
| Mutation itself raises | `mark_applied`/`mark_discarded` raises after the job lookup succeeds | Original exception propagates unchanged | A row is still logged with `result="error"`, `error` containing the exception message, before re-raising |
| Audit table missing (first-ever qualifying call against an old `jobs.db`) | Pre-existing `jobs.db` with no `mcp_audit_log` table yet | Table is created on the fly (idempotent); the call's own row is logged normally | No error expected |

</frozen-after-approval>

## Spec Change Log

### 2026-07-12 — intent_gap resolved

- **Triggering findings:** independent adversarial + edge-case review of the first implementation both converged on the same contradiction: the frozen spec required logging every invocation attempt (including an invalid `action` string) while also forbidding any change to `track_application`'s existing behavior. The only way to log an invalid-action rejection is to open a DB connection before the action-validity check runs, but `connect_jobs()` unconditionally creates `jobs.db` (directory + file + schema) if it doesn't exist — so a previously side-effect-free rejection (bad action string against a not-yet-created `jobs.db`) would now silently create that file. This is a deterministic behavior change, not a rare race, and it directly violated the frozen "don't change existing behavior" line.
- **What was amended:** carved the invalid-action case out of "log every attempt" — it now stays a zero-I/O fast-fail exactly as it was before this feature existed, and is the one attempt type that is never logged. Only attempts that already require a DB connection anyway (unknown-job-id rejections, mutation failures, successes) are logged. Also folded in, while re-deriving, several smaller robustness fixes both reviews found: audit-write failures must never mask a successful mutation's return value (best-effort logging on the success path) nor suppress the original exception on a rejection path; `job_id` is `NOT NULL` in the schema; a small additive-column migration guard for `mcp_audit_log` mirrors `jobs/db.py`'s own `_ensure_columns()` pattern; the mutation-itself-raises case (`mark_applied`/`mark_discarded` failing after a successful job lookup) is now also logged, which the first attempt missed entirely.
- **Known-bad state avoided:** `jobs.db` silently created as a side effect of a malformed/typo'd action string call; a successful mutation returning an error to the caller (or vice versa — an error being replaced by an unrelated logging exception) purely because the audit write had a transient hiccup.
- **KEEP instructions (preserve on re-derivation):** the overall design — a dedicated `mcp_audit_log` table, created/managed entirely inside `src/mcp_server/tools.py`, capturing timestamp/job_id/action/previous_status/result/error — is correct and unchanged; keep it. The `tmp_path`-based SQLite test fixture pattern already used in `tests/test_mcp_tools.py` is correct; keep following it. The decision NOT to add authentication/actor-identity, NOT to build a general application-wide audit log, and NOT to add retention/pruning/indexing (out of scope for this single-user hobby-scale tool) all stand — those review findings were correctly rejected in the first pass and remain rejected now.

## Code Map

- `src/mcp_server/tools.py` -- `track_application(...)` -- keep the `action not in _ACTIONS` check as the first line with zero I/O (no connection, no logging); after that, connect and ensure the audit table/columns exist; log the unknown-job-id rejection, a mutation-raises rejection, and a success, each exactly once; wrap the success-path audit write in `try/except` so a logging failure can't mask a successful return; wrap the rejection-path audit writes so a logging failure can't suppress the original exception
- `tests/test_mcp_tools.py` -- add audit-log assertions to the existing `track_application` tests (success case), a test proving the invalid-action path opens no connection/creates no file and logs nothing, a test for the unknown-job-id rejection, a test for a mutation-raises rejection (mock `mark_applied`/`mark_discarded` to raise), and a test for the additive-column migration guard — following this file's existing `tmp_path` SQLite fixture pattern

## Tasks & Acceptance

**Execution:**
- [x] `src/mcp_server/tools.py` -- add `_ensure_audit_table(conn)` (idempotent `CREATE TABLE IF NOT EXISTS mcp_audit_log` with `job_id INTEGER NOT NULL`, plus an `_ensure_columns`-style additive-column guard mirroring `jobs/db.py`'s pattern) and `_record_audit(conn, job_id, action, previous_status, result, error=None)`; wire into `track_application` so the action-validity check stays first with zero I/O (no logging for that case), and every other code path (unknown job_id, mutation-raises, success) logs exactly one row; success-path logging is best-effort (wrapped so a logging failure never replaces a successful return); rejection-path logging must never suppress the original exception
- [x] `tests/test_mcp_tools.py` -- assert a `mcp_audit_log` row is written for: a successful `"applied"` call, a successful `"discarded"` call, and an unknown-job-id call; assert an invalid-action call opens no DB connection (no `jobs.db` file created when none existed) and logs no row; assert a mutation-raises case still logs a row and still raises the original exception; assert the additive-column migration guard doesn't break inserts against a pre-existing, differently-shaped `mcp_audit_log` table

**Acceptance Criteria:**
- Given a job successfully marked applied via `track_application`, when `mcp_audit_log` is queried for that job_id, then exactly one new row exists with `action="applied"`, `result="success"`, and a non-null timestamp.
- Given an invalid action passed to `track_application` against a `jobs_db` path with no existing file, when the call raises `ValueError` (unchanged behavior), then no file is created at that path and no row is written to any audit table.
- Given an unknown job_id, or a mutation call that raises after a successful job lookup, when `track_application` raises (unchanged/original exception), then a row is still written to `mcp_audit_log` with `result="error"` and a non-null `error` message.
- Given a `jobs.db` file that predates this change (no `mcp_audit_log` table), when `track_application` is called against it in a way that reaches logging, then the table is created automatically with no error.

## Verification

**Commands:**
- `uv run pytest tests/test_mcp_tools.py -v` -- expected: all existing tests still pass, plus new audit-log assertions green (19 passed)
- `uv run pytest` -- expected: full suite green, no regressions (153 passed)

## Suggested Review Order

- `src/mcp_server/tools.py:25` -- new `_ensure_columns` import, reused directly from `jobs/db.py` instead of a duplicated column-diff loop
- `src/mcp_server/tools.py:52-61` -- `_AUDIT_SCHEMA` -- new `mcp_audit_log` table definition, self-contained to this module
- `src/mcp_server/tools.py:65-70` -- `_ensure_audit_table` -- idempotent create + additive-column guard via the shared `_ensure_columns` helper
- `src/mcp_server/tools.py:82-102` -- `_record_audit` -- single-row insert helper, no swallowing of its own
- `src/mcp_server/tools.py:123-176` -- `track_application` -- action-validity check stays a zero-I/O first line; `_ensure_audit_table` call wrapped best-effort; three logged paths (unknown job_id, mutation-raises, success) each wrap their audit write so a logging failure can never mask the caller-visible outcome; mutation-raises path now records `f"{type(exc).__name__}: {exc}"` for stronger diagnostics
- `tests/test_mcp_tools.py:91-138` -- success-path tests, including the new re-tracking test asserting a real non-null `previous_status`
- `tests/test_mcp_tools.py:131-160` -- invalid-action zero-I/O tests, including the new existing-db variant
- `tests/test_mcp_tools.py:224-256` -- new logging-failure-safety tests: success/unknown-job-id/mutation-raises outcomes all survive a `_record_audit` failure
