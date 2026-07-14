---
id: SPEC-admin-destructive-safety
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Admin Page Destructive-Action Safety Guards

## Why

The Admin page (`views/admin.py`) wraps two mutating actions — a whole-table sponsor-register wipe+reload, and an insert-only CV-upload profile registration — that adversarial and edge-case review (2026-07-12, reconfirmed by sweep triage 2026-07-14) found under-guarded relative to their blast radius and to this codebase's own conventions elsewhere (e.g. `mcp_server/tools.py` already sets a connection-level concurrency guard; other single-click mutations in the app only ever touch one row). This is a pain to solve for the Admin page's sole operator (the app owner, deploying/maintaining a personal single-user tool): a mis-click or double-click here can silently duplicate data, burn a paid Gemini call, wipe the sponsor register into a lock error, or invisibly change what every in-flight job match/tailor reads as the active CV — with no confirmation, no dedup, and no "nothing changed" signal to catch it.

## Capabilities

- **CAP-1**
  - **intent:** The Admin page can tell the operator when a sponsor-register refresh fetched the same data that was already loaded, instead of reporting generic success.
  - **success:** Refreshing the register twice in a row (same source) shows a distinct "already up to date" message on the second click; refreshing after the source genuinely changed shows the existing success message.

- **CAP-2**
  - **intent:** The sponsor-register wipe+reload (`replace_all`) can run under a concurrency guard so an overlapping refresh or reader waits instead of the operation surfacing a raw driver error.
  - **success:** Two overlapping register-refresh calls against the same DB no longer raise an unhandled `sqlite3.OperationalError` ("database is locked"); the second either completes after a bounded wait or fails with a clear, caught message.

- **CAP-3**
  - **intent:** The operator can confirm before "Refresh sponsor register now" fires its destructive wipe+reload.
  - **success:** Clicking "Refresh sponsor register now" opens a confirmation step; the wipe+reload only executes after an explicit second confirming action, and is not triggered by the first click alone.

- **CAP-4**
  - **intent:** The operator can submit "Extract & Register Profile" without a double-click or repeat submission creating more than one profile row or more than one Gemini call for the same upload.
  - **success:** Rapidly double-clicking (or otherwise repeat-submitting) "Extract & Register Profile" for one uploaded file results in exactly one new row in `profiles` and one Gemini extraction call.

- **CAP-5**
  - **intent:** The operator can see the currently-latest profile and confirm before a newly uploaded CV supersedes it as the profile match-scoring/tailoring reads.
  - **success:** Uploading and submitting a new CV shows the current latest profile (name/seniority) and requires an explicit confirming action before the new profile is inserted and becomes `get_latest_profile`'s result.

## Constraints

- CAP-2 must reuse the exact `PRAGMA busy_timeout = 5000` value and connection-open-time placement already used in `mcp_server/tools.py` (lines 103, 140, 181) — not a different timeout or a different mechanism (e.g. Python-level retry loop).
- No new dependencies. Streamlit 1.58.0 is pinned (`uv.lock`) — `st.dialog` (native modal, available since 1.31) is the confirmation mechanism for CAP-3 and CAP-5.
- No `st.cache_data`/`st.cache_resource` anywhere in this codebase by explicit project convention — CAP-1's no-op detection and CAP-4's in-flight guard must be implemented via `st.session_state` across Streamlit's rerun-per-interaction model, not caching.

## Non-goals

- Authentication/access control on the Admin page — single-user local tool, out of scope.
- A general-purpose, reusable confirmation-dialog component — only the two destructive actions in CAP-3 and CAP-5 get guarded.
- Fixing the systemic `st.error(str(exc))` blank-box issue, or adding atomic (temp-file-then-rename) writes elsewhere in the codebase — both are separate, already-logged `deferred-work.md` entries tracked independently of this spec.
- Changing `register.cli.DEFAULT_SOURCE` to point at a live "latest register" endpoint instead of a fixed dated snapshot — CAP-1 only surfaces when a refresh was a no-op against the current source; it does not fix the source's underlying staleness.
- A way to delete or roll back a superseded CV profile — CAP-5's confirmation only gates new uploads going forward; `profiles` stays insert-only per existing project convention.

## Success signal

On the Admin page: refreshing the sponsor register twice in a row shows "already up to date" on the second attempt; two overlapping refreshes no longer crash with a raw lock error; "Refresh sponsor register now" requires a confirming second click before it wipes and reloads; double-submitting "Extract & Register Profile" produces exactly one profile row and one Gemini call; and uploading a new CV shows the current latest profile and requires confirmation before it's replaced.

## Assumptions

- `st.dialog` is available and is the intended confirmation mechanism for CAP-3 and CAP-5, since the pinned Streamlit version (1.58.0) postdates its introduction (1.31) and no lighter-weight in-repo confirm pattern exists to match instead.

## Open Questions

- None — all five capabilities and their implementation constraints were resolvable from `deferred-work.md`'s existing evidence plus the current codebase.
