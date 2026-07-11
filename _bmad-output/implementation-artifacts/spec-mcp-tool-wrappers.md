---
title: 'MCP tool wrappers over the job-search pipeline'
type: 'feature'
created: '2026-07-11'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context: ['{project-root}/_bmad-output/project-context.md']
warnings: ['oversized']
baseline_revision: 'd5a2494f8ff489ae05a57d72dc78a4f4152fe50b'
final_revision: '4fc8104f2bae4ea8fe3fbc11a11225bc762026c4'
---

<intent-contract>

## Intent

**Problem:** A separate review session decided MCP should expose the existing job-search pipeline as tools for an MCP client (Claude Desktop / Claude Code), but no MCP code exists yet in this repo, and the `mcp` SDK isn't installed.

**Approach:** Add a new `src/mcp_server/` package that thinly wraps four already-correct pipeline functions (sponsor check, salary check, application tracking) as MCP tools — no new business logic, no changes to `register`/`jobs` modules.

## Boundaries & Constraints

**Always:**
- Wrap existing functions, never reimplement: `jobs.sponsor_check.check_sponsor_status`, `jobs.salary_check.check_salary_threshold`, `jobs.db.mark_applied`/`mark_discarded`/`list_applied_jobs`/`get_job`, `jobs.tracker.due_milestone`, `register.db.connect`.
- Each wrapper function opens its own DB connection and closes it in `finally` before returning — never hold a connection open across calls (the MCP server is a long-running process).
- Put all business logic in `src/mcp_server/tools.py` with **zero import of the `mcp` package** — it must stay importable and unit-testable even if `mcp` isn't installed. Put the `FastMCP` registration only in `src/mcp_server/server.py`.
- Default DB paths mirror existing CLI defaults: `data/sponsors.db`, `data/jobs.db`.
- Serialize dataclass verdicts (`SponsorVerdict`, `SalaryVerdict`) with `dataclasses.asdict` so tool return values are plain JSON-safe dicts.
- `server.py` calls `load_dotenv()` at module level (per this repo's existing per-entry-point convention).
- Add `mcp` to `pyproject.toml` dependencies and to `[tool.hatch.build.targets.wheel] packages`. In this sandboxed dev environment, resolving `mcp` from PyPI requires the system cert store (confirmed via `uv pip install mcp --dry-run --native-tls`, which resolved `mcp==1.28.1`); the persisted setting is `[tool.uv] system-certs = true` in `pyproject.toml` (uv's current, non-deprecated name for this — `native-tls` is the deprecated alias) so plain `uv sync`/`uv add` keep working here without a flag.

**Block If:** none — the MCP decisions (which functions to wrap, tool naming, connection-lifecycle rule) were already settled in a prior session and are restated above; `mcp` package resolvability was already verified.

**Never:**
- Do not modify `jobs/sponsor_check.py`, `jobs/salary_check.py`, `jobs/tracker.py`, `jobs/db.py`, or `register/db.py`.
- Do not add LangGraph, agent orchestration, or any multi-step planning under the MCP layer.
- Do not wrap the Gemini-calling functions (`extract_job`, tailoring, outreach) as MCP tools — out of scope; only the four tools named above.
- Do not add a shared/cached DB connection held across tool calls.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Sponsor confirmed | `check_sponsor("Acme AI Ltd")`, register has "Acme AI Limited" | dict with `status: "confirmed"`, matched name/town/rating/route | No error expected |
| Sponsor name redacted | `check_sponsor(None)` | dict with `status: "cannot_verify"` | No error expected |
| Salary below threshold | `check_salary_threshold("AI Engineer", "£30,000")` | dict with `status: "below_threshold"` | No error expected |
| Mark applied | `track_application(job_id, "applied")` on an existing job | dict of updated job row, `applied_status: "applied"`, non-null `applied_at` | No error expected |
| Invalid action | `track_application(job_id, "maybe")` | — | Raises `ValueError` naming the bad action |
| Unknown job id | `track_application(999999, "applied")` | — | Raises `ValueError` — "no job with id 999999" |
| No due reminders | `list_applications(due_only=True)` with only recently-applied jobs | `[]` | No error expected |

</intent-contract>

## Code Map

- `pyproject.toml` -- add `mcp` dependency, `src/mcp_server` build package, `[tool.uv] native-tls = true`
- `src/mcp_server/__init__.py` -- new, empty package marker
- `src/mcp_server/tools.py` -- new, plain wrapper functions (no `mcp` import)
- `src/mcp_server/server.py` -- new, `FastMCP` instance + `@mcp.tool()` registrations
- `tests/test_mcp_tools.py` -- new, unit tests for all four wrapper functions
- `src/jobs/sponsor_check.py`, `src/jobs/salary_check.py`, `src/jobs/tracker.py`, `src/jobs/db.py`, `src/register/db.py` -- read-only references, imported not modified

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml` -- run `uv add mcp --native-tls`, then add `"src/mcp_server"` to `[tool.hatch.build.targets.wheel] packages` and `[tool.uv]\nsystem-certs = true` -- makes the SDK installed and the new package buildable/importable
- [x] `src/mcp_server/__init__.py` -- empty file -- makes `mcp_server` an importable package
- [x] `src/mcp_server/tools.py` -- implement `check_sponsor(employer_name, *, sponsor_db=...)`, `check_salary_threshold(job_title, salary_raw=None)`, `track_application(job_id, action, *, jobs_db=...)`, `list_applications(due_only=False, *, jobs_db=...)`, each opening/closing its own connection and returning JSON-safe dicts -- the four tools from Decision 2
- [x] `src/mcp_server/server.py` -- `load_dotenv()`, `FastMCP("sponsorship-job-platform")` instance, one `@mcp.tool()` per function in `tools.py` delegating straight through, `if __name__ == "__main__": mcp.run()` -- exposes the tools over the MCP transport
- [x] `tests/test_mcp_tools.py` -- cover every row of the I/O & Edge-Case Matrix using `tmp_path` SQLite dbs, following the existing `_register_with`/`insert_job` test fixture patterns in `tests/test_sponsor_check.py` and `tests/test_jobs_db.py` -- verifies wrapper correctness without a live MCP client

**Acceptance Criteria:**
- Given a tmp `sponsors.db` seeded with a `SponsorRecord`, when `check_sponsor` is called with a name matching it (different suffix/case), then the returned dict has `status == "confirmed"` and the register's town_city/rating/route.
- Given a tmp `jobs.db` with one inserted job, when `track_application(job_id, "applied")` is called, then the returned dict's `applied_status == "applied"` and `applied_at` is non-null.
- Given the `mcp` package, when `tests/test_mcp_tools.py` imports only `mcp_server.tools` (not `mcp_server.server`), then the import succeeds even without `mcp` installed, proving the business-logic/registration split holds.
- Given `uv run python -c "from mcp_server import server"`, when run after `uv add mcp --native-tls`, then it imports without error.

## Design Notes

The `tools.py`/`server.py` split exists because this sandboxed environment needed the system cert store just to resolve `mcp` from PyPI (default bundled TLS fails with `UnknownIssuer`) — keeping the wrapper logic free of any `mcp` import means the existing test suite and CI-less local dev loop never depend on that SDK being present, only the actual MCP transport does. Connection-per-call (not a shared/cached connection) mirrors the existing CLI convention in `jobs/cli.py` and avoids the long-running-process staleness risk already flagged in `project-context.md`.

## Verification

**Commands:**
- `uv add mcp --native-tls` -- expected: `mcp` added to `pyproject.toml`/`uv.lock` with no resolution error
- `uv run pytest tests/test_mcp_tools.py -v` -- expected: all new tests pass
- `uv run pytest` -- expected: full existing suite still green, no regressions
- `uv run python -c "from mcp_server import server"` -- expected: clean import, no exception

## Review Triage Log

### 2026-07-11 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 5 (high 1, medium 1, low 3)
- defer: 1 (low 1)
- reject: 9
- addressed_findings:
  - `[high]` `[patch]` Default `sponsor_db`/`jobs_db` paths were CWD-relative strings (`"data/sponsors.db"`); an MCP client spawns the server with an arbitrary working directory, and `connect()` auto-creates a schema-valid but empty DB at any missing path instead of erroring — silently pointing every tool at the wrong, empty database. Fixed by anchoring both defaults to the project root via `Path(__file__).resolve().parents[2]` in `tools.py`.
  - `[medium]` `[patch]` `server.py` (the FastMCP registration layer) had zero test coverage despite `mcp` now being a hard dependency. Added `tests/test_mcp_server.py` asserting all four tools are registered via the real installed `FastMCP.list_tools()` API.
  - `[low]` `[patch]` No `PRAGMA busy_timeout` on connections opened in `tools.py`, so a genuine collision with the Streamlit app writing the same SQLite file would raise immediately instead of waiting briefly. Added `busy_timeout = 5000` after each `connect(...)`.
  - `[low]` `[patch]` `employer_name` had no default, forcing an MCP client to pass explicit `null` instead of omitting it. Defaulted to `None` in both `tools.check_sponsor` and `server.check_sponsor`.
  - `[low]` `[patch]` `server.py`'s DB-path params were positional-or-keyword while `tools.py`'s were keyword-only. Made `server.py`'s keyword-only to match.
  - `[low]` `[defer]` No audit trail for `track_application`'s mutating calls (who/when/what changed) — legitimate future logging feature, out of scope for this story. Logged to `deferred-work.md`.
  - Rejected (reviewer lacked full repo/spec context, or premise didn't hold): path-traversal validation on DB-path params (matches the existing single-user, unvalidated `--db` convention across every CLI in this repo); `conn.close()` exceptions masking a return value inside `finally` (pre-existing pattern replicated everywhere in this codebase, not introduced by this diff); `mcp>=1.28.1` unbounded (matches every other dependency's convention in `pyproject.toml`); `[tool.uv] system-certs = true` flagged as an unrelated smuggled-in change (it was explicitly required and documented in this spec's Design Notes, reviewer lacked that context); docstring "duplication" between `tools.py` and `server.py` (intentional — MCP client-facing schema text vs. Python implementation doc are different audiences); dataclass JSON-serialization safety for hypothetical non-JSON fields (no such fields exist in `SponsorVerdict`/`SalaryVerdict` today); missing-file/missing-schema `OperationalError` (incorrect premise — `connect()` already auto-creates the schema); row deleted between mutation and re-fetch causing `dict(None)` (impossible — no `delete_job` function exists anywhere in this codebase; jobs are insert-only).

## Auto Run Result

**Summary:** Added `src/mcp_server/` exposing the job-search pipeline's sponsor check, salary check, and application tracker as four MCP tools (`check_sponsor`, `check_salary_threshold`, `track_application`, `list_applications`), per the MCP integration decisions reconciled earlier this session. Pure wrapper layer — zero changes to `register`/`jobs` business logic.

**Files changed:**
- `pyproject.toml` -- added `mcp>=1.28.1` dependency, `src/mcp_server` to wheel packages, `[tool.uv] system-certs = true`
- `uv.lock` -- updated by `uv add mcp`
- `src/mcp_server/__init__.py` -- new, empty package marker
- `src/mcp_server/tools.py` -- new, four business-logic wrappers, no `mcp` import, connection-per-call, project-root-anchored DB defaults, `busy_timeout` pragma
- `src/mcp_server/server.py` -- new, `FastMCP` instance + `@mcp.tool()` registrations delegating to `tools.py`
- `tests/test_mcp_tools.py` -- new, 9 tests covering the I/O & Edge-Case Matrix plus the tools/server import-split structural check
- `tests/test_mcp_server.py` -- new, 2 tests confirming the `FastMCP` instance imports and all four tools are registered

**Review findings breakdown:** 5 patched (1 high, 1 medium, 3 low), 1 deferred (logged to `deferred-work.md`), 9 rejected as noise or based on an incorrect premise. No intent gaps, no spec-level rewrites needed.

**Verification performed:**
- `uv run pytest -q` → 122 passed, 0 failures (up from the pre-existing 120; no regressions)
- `uv run python -c "from mcp_server import tools; print(tools.DEFAULT_SPONSOR_DB); print(tools.DEFAULT_JOBS_DB)"` → both resolve to absolute paths under the real project root's `data/` directory, independent of CWD
- `uv run python -c "from mcp_server import server"` → clean import

**Residual risks:**
- No audit trail for `track_application` mutations — deferred, see `deferred-work.md`.
- This has not yet been run against a live MCP client (Claude Desktop/Code) end-to-end — only unit-tested. First real invocation may surface transport-level issues unit tests can't catch (e.g. `FastMCP` config, tool schema quirks).
- SQLite lock contention between the Streamlit app and a running MCP server is mitigated (`busy_timeout`) but not eliminated — a sustained collision would still surface as an error to the caller.
