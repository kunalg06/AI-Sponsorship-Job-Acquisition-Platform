---
title: 'Admin page: sponsor-register-ingest button'
type: 'feature'
created: '2026-07-12'
status: 'done'
review_loop_iteration: 0
context: ['{project-root}/_bmad-output/project-context.md']
baseline_commit: '4f6a274578eeb42f03c2137a4e6e52c47a609b66'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Streamlit Community Cloud has no shell access, and `data/`/`cv/`/`.env` are all gitignored, so a fresh Cloud deploy starts with an empty `sponsors.db` — there is currently no way to load the UK sponsor register except running `uv run python -m register.cli ingest` from a local terminal, which Cloud doesn't offer.

**Approach:** Add a new "Admin" Streamlit page with a single button that wraps the already-complete `register.ingest.ingest(...)` pipeline (the same one the CLI already calls) — fetch, parse, normalize, and wholesale-replace the `sponsors` table — surfacing the same summary the CLI prints today, inside the UI instead.

## Boundaries & Constraints

**Always:**
- Reuse `register.ingest.ingest(source, db_path)` and the existing `register.cli.DEFAULT_SOURCE`/`DEFAULT_DB` constants unchanged — do not duplicate the source URL or db path as new literals in the view.
- Show the current sponsor count (`register.db.count`) on page load, before any ingest runs, so the admin can see whether the register is already populated.
- Wrap the ingest call in `st.spinner(...)` (it fetches and loads ~122k rows and can take real time) and in `try/except Exception as exc: st.error(str(exc))`, matching this codebase's existing pattern in `views/intake.py`/`views/jobs_list.py` for every other CLI-layer-wrapping button.
- On success, show a success message with `rows_loaded`, `source_updated`, and `rows_in_db` (the same fields the CLI's `_cmd_ingest` prints), then `st.rerun()` so the on-page count reflects the new total.
- Register the new page in `app.py`'s existing `st.navigation([...])` list, matching the existing `st.Page(...)` call style for `views/intake.py`/`views/roadmap.py`/`views/jobs_list.py`.

**Ask First:** none identified.

**Never:**
- Do not modify `register/ingest.py`, `register/db.py`, or `register/cli.py` — this is a UI wrapper only, reusing the pipeline exactly as the CLI already does.
- Do not add a custom source URL/file override input on this page — only the existing `DEFAULT_SOURCE` is wired up; a custom-source control is a separate, later enhancement if ever needed.
- Do not add authentication or access control to the Admin page — this is a single-user personal tool, same decision already made for the MCP audit-trail feature.
- Do not touch the CV-upload/resume-registration half of the original combined "Admin page" deferred-work item — that's tracked separately (see `deferred-work.md`) and is explicitly out of scope here.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fresh empty DB | No `data/sponsors.db` file exists yet | Page loads and shows "0 sponsors currently loaded"; `register.db.connect` creates the empty DB/schema as a read side effect, same as it already does elsewhere | N/A |
| Successful ingest | Button clicked, network reachable, CSV well-formed | Spinner shown during fetch/load; success message shows rows loaded, register date, and new total; count display updates after rerun | N/A |
| Network/fetch failure | Button clicked, source URL unreachable or times out | Original exception surfaced via `st.error(str(exc))`; `sponsors` table untouched (the failure happens before `replace_all` runs) | Caught by the shared `except Exception` |
| Malformed CSV | Button clicked, source missing a required column | `ValueError` from `parse_rows` surfaced via `st.error`; `sponsors` table untouched | Caught by the shared `except Exception` |

</frozen-after-approval>

## Code Map

- `views/admin.py` (new) -- Streamlit page: shows current sponsor count, one button wrapping `register.ingest.ingest(DEFAULT_SOURCE, DEFAULT_DB)`
- `app.py` -- add the new page to the existing `st.navigation([...])` list

## Tasks & Acceptance

**Execution:**
- [x] `views/admin.py` -- create the page: open `register.db.connect(DEFAULT_DB)`, show `count(conn)` as "N sponsors currently loaded", close the connection; a "Refresh sponsor register now" button that calls `register.ingest.ingest(DEFAULT_SOURCE, DEFAULT_DB)` inside `st.spinner`/`try-except`, showing `st.success(...)` with the summary dict's fields on success or `st.error(str(exc))` on failure, then `st.rerun()` on success
- [x] `app.py` -- add `st.Page("views/admin.py", title="Admin", icon="⚙️")` to the navigation list

**Acceptance Criteria:**
- Given no `data/sponsors.db` exists yet, when the Admin page loads, then it shows 0 sponsors loaded without raising.
- Given the ingest succeeds, when the button is clicked, then a success message with rows-loaded/register-date/total appears and the on-page count reflects the new total after rerun.
- Given the ingest raises (network failure or malformed CSV), when the button is clicked, then the original exception message is shown via `st.error` and the sponsors table is left untouched.

## Verification

**Commands:**
- `uv run pytest` -- expected: full suite green, no regressions (this page has no dedicated test file, matching the existing untested-views convention for `app.py`/`views/*.py`)

**Manual checks (if no CLI):**
- Run `uv run streamlit run app.py`, open the new "Admin" page, confirm the sponsor count shows correctly, click "Refresh sponsor register now" against the real default source, and confirm the success message and updated count match what `uv run python -m register.cli ingest` already produces from the terminal.

## Suggested Review Order

**Admin page logic**

- Entry point: page-load count query now fails gracefully (not just the button click) if the DB can't be read.
  [`admin.py:28`](../../views/admin.py#L28)

- The button's fetch/parse/normalize/replace-all call, wrapped in the same spinner + try/except/else pattern used elsewhere in this codebase.
  [`admin.py:40`](../../views/admin.py#L40)

- Docstring now calls out that the default source is a frozen dated snapshot, not an auto-updating feed.
  [`admin.py:10`](../../views/admin.py#L10)

**Navigation wiring**

- New page registered in the existing `st.navigation([...])` list, icon style matched to the other entries.
  [`app.py:45`](../../app.py#L45)

**Peripherals**

- Ledger: original Admin-page item split in two; new page's own item marked done; 4 new findings from review logged for later attention.
  [`deferred-work.md`](deferred-work.md)
