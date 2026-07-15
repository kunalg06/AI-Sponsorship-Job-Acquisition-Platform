---
title: 'Streamlit view testability'
type: 'feature'
created: '2026-07-15'
status: 'done'
review_loop_iteration: 0
baseline_commit: '453ed9839bf0642e77217584991a39b27b37a309'
context: ['{project-root}/_bmad-output/specs/spec-streamlit-view-testability/SPEC.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `app.py`'s `GEMINI_API_KEY` secrets-bridging and the `error_display_text` wiring across `views/admin.py`/`views/intake.py`/`views/jobs_list.py` have zero automated test coverage — both execute as top-level side effects of import, so a plain `pytest` import can't isolate them. A future typo or revert at either would regress silently.

**Approach:** Use `streamlit.testing.v1.AppTest` (already installed, `streamlit==1.58.0`) to run the real scripts in a sandboxed runtime. A shared `pytest` fixture seeds fresh `data/jobs.db`/`data/profile.db`/`data/sponsors.db` in a `tmp_path` and `chdir`s into it (these DB paths are hardcoded module-level constants in the view files, not injectable). No production code changes.

## Boundaries & Constraints

**Always:** Every `AppTest`-based test runs with `monkeypatch.chdir` into a `tmp_path` seeded via one `connect()` call per DB module (`jobs.db`/`resume.db`/`register.db` all run `CREATE TABLE IF NOT EXISTS`) — never touch the real project `data/` directory. `GEMINI_API_KEY` env manipulation uses `monkeypatch.setenv`/`delenv`, never direct `os.environ` mutation, so state never leaks to other tests. Monkeypatch functions imported via `from module import name` (e.g. `register.db.connect`, `jobs.ui_actions.generate_tailored_docx_for_job`) at their **source module**, before `AppTest.run()` re-executes the script's imports.

**Ask First:** None expected — scope is fully bounded by the approved SPEC.md kernel.

**Never:** Change any production code in `app.py`/`views/*.py`/`jobs/ui_actions.py`. Aim for exhaustive coverage of all 10 `error_display_text` call sites or full view user-flow coverage — one representative site per view file is the target.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Secrets present, env unset | `.streamlit/secrets.toml` has `GEMINI_API_KEY`, no env/`.env` value | `os.environ["GEMINI_API_KEY"]` set to the secrets value after `app.py` runs | N/A |
| Env already set | `GEMINI_API_KEY` set via `monkeypatch.setenv`, secrets.toml has a *different* value | `os.environ["GEMINI_API_KEY"]` still equals the env value — untouched | N/A |
| admin.py DB connect fails | `register.db.connect` monkeypatched to raise bare `OSError()` | Module-level `except Exception` fires; `at.error[0].value` names `OSError`, non-empty | N/A |
| intake.py tailoring fails | `saved_job_id` seeded in session state; `generate_tailored_docx_for_job` monkeypatched to raise bare `SystemExit()` | Clicking the tailor button surfaces `at.error[0].value` naming `SystemExit`, non-empty | N/A |
| jobs_list.py tailoring fails | One job row seeded in `jobs.db`; same monkeypatch as intake.py | Clicking `tailor_{job_id}` button surfaces `at.error[0].value` naming `SystemExit`, non-empty | N/A |

</frozen-after-approval>

## Code Map

- `tests/conftest.py` -- **new file** -- shared `streamlit_data_env(tmp_path, monkeypatch)` fixture: chdir into `tmp_path`, create `data/` dir, seed `data/jobs.db`/`data/profile.db`/`data/sponsors.db` via each module's `connect()`
- `tests/test_app.py` -- **new file** -- CAP-1: two tests for `app.py`'s secrets-bridging (present/absent-env cases)
- `tests/test_views_error_display.py` -- **new file** -- CAP-2: three tests, one per view file

## Tasks & Acceptance

**Execution:**
- [x] `tests/conftest.py` -- add `streamlit_data_env` fixture (chdir + seed 3 DBs via `connect()`) -- the one shared mechanism both new test files depend on
- [x] `tests/test_app.py` -- `test_app_bridges_gemini_api_key_from_secrets_when_env_unset`: `monkeypatch.delenv("GEMINI_API_KEY", raising=False)`, set `at.secrets["GEMINI_API_KEY"]`, `AppTest.from_file(APP_PY).run()`, assert `os.environ["GEMINI_API_KEY"]` equals the secrets value
- [x] `tests/test_app.py` -- `test_app_leaves_existing_env_gemini_api_key_unchanged`: `monkeypatch.setenv("GEMINI_API_KEY", "already-set")`, set `at.secrets[...]` to a *different* value, run, assert `os.environ["GEMINI_API_KEY"] == "already-set"`
- [x] `tests/test_views_error_display.py` -- `test_admin_page_shows_error_display_text_for_empty_message_exception`: monkeypatch `register.db.connect` to raise `OSError()`, `AppTest.from_file(ADMIN_PY).run()`, assert `at.error[0].value` is non-empty and contains `"OSError"`
- [x] `tests/test_views_error_display.py` -- `test_intake_page_shows_error_display_text_for_empty_message_exception`: seed `jobs.db` with one job, monkeypatch `jobs.ui_actions.generate_tailored_docx_for_job` to raise bare `SystemExit()`, run `views/intake.py` with `extraction`/`resolved_employer`/`saved_job_id` preset in session state, click the tailor button, `.run()`, assert `at.error[0].value` is non-empty and contains `"SystemExit"`
- [x] `tests/test_views_error_display.py` -- `test_jobs_list_page_shows_error_display_text_for_empty_message_exception`: seed `jobs.db` with one job, same monkeypatch, run `views/jobs_list.py`, click the `tailor_{job_id}`-keyed button, `.run()`, assert `at.error[0].value` is non-empty and contains `"SystemExit"`

**Acceptance Criteria:**
- Given `app.py` runs with `st.secrets` containing `GEMINI_API_KEY` and no env value set, when the script finishes, then `os.environ["GEMINI_API_KEY"]` equals the secrets value.
- Given `app.py` runs with `GEMINI_API_KEY` already set in the environment, when `st.secrets` also has a different value, then the environment value is left unchanged.
- Given each of `admin.py`/`intake.py`/`jobs_list.py` triggers a caught exception with an empty `str()`, when the page renders the error, then `at.error[0].value` is non-empty and names the exception type — proving the site still routes through `error_display_text`, not bare `str(exc)`.

## Spec Change Log

<!-- Empty until the first bad_spec loopback. -->
<!-- Token-count check (step-02): ~1800 tokens, over the 1600 target. User chose [K] Keep full spec — CAP-1 and CAP-2 share the identical AppTest+chdir+seeding mechanism and the same new conftest.py fixture; splitting would duplicate that shared infrastructure across two specs. -->

## Design Notes

`AppTest.from_file(path).run()` executes the target script fresh each call, re-running its top-level imports — so a `monkeypatch.setattr` on a function's **source module** (e.g. `register.db.connect`, not `views.admin.connect`) still takes effect, since the view's `from module import name` re-binds at each run. `intake.py`'s tailor button is gated on `st.session_state.get("saved_job_id")`; `AppTest` supports presetting `at.session_state[...]` before `.run()`, avoiding the need to simulate the full paste-a-job-posting flow just to reach this one button.

Two refinements found during implementation, both same observable behavior as the frozen I/O matrix describes, no spec renegotiation needed:
- `AppTest` exposes `at.secrets` as a plain writable dict applied to `st.secrets` during `.run()` — used directly instead of writing a `.streamlit/secrets.toml` file, avoiding any filesystem side effect.
- `AppTest.from_file(...)` resolves its path relative to the process's cwd at call time. Since `streamlit_data_env` already `chdir`s into the tmp sandbox, the script path must be captured as an absolute path at module import time (before any test runs), or `AppTest` can't find the real `app.py`/`views/*.py` on disk. Same reasoning applies to `dotenv.load_dotenv()`, which searches upward from `app.py`'s own file location regardless of cwd — it was found to load this machine's real `.env` and had to be monkeypatched to a no-op in the `test_app.py` tests to avoid depending on (or being masked by) the developer's local secrets.

## Verification

**Commands:**
- `python -m pytest tests/test_app.py tests/test_views_error_display.py -v` -- expect all 5 new tests to pass
- `python -m pytest --ignore=tests/test_mcp_server.py` -- expect no regressions
- Manual: confirm no test run touches the real `data/*.db` files (`git status` shows no changes to `data/` after the run)

**Manual checks (if no CLI):**
- None needed -- fully covered by the automated tests above.

## Suggested Review Order

**Shared fixture**

- Entry point: chdir + seed 3 fresh DBs at the exact relative paths app.py/views/*.py hardcode.
  [`conftest.py:19`](../../tests/conftest.py#L19)

**app.py secrets bridging (CAP-1)**

- Uses `at.secrets` dict directly instead of writing a `.streamlit/secrets.toml` file — a refinement found during implementation.
  [`test_app.py:19`](../../tests/test_app.py#L19)

- Proves env always wins over secrets when both are present.
  [`test_app.py:33`](../../tests/test_app.py#L33)

- The third branch (neither present): env stays unset, stderr warning fires — added after review flagged it as untested.
  [`test_app.py:44`](../../tests/test_app.py#L44)

**View error-display wiring (CAP-2)**

- Module-level call site, no button click needed — the simplest of the three to trigger.
  [`test_views_error_display.py:51`](../../tests/test_views_error_display.py#L51)

- Presets `extraction`/`resolved_employer`/`saved_job_id` directly into session state, skipping the full paste-a-job UI flow.
  [`test_views_error_display.py:65`](../../tests/test_views_error_display.py#L65)

- Seeds 2 jobs and asserts the mock was called with the *second* job's id — catches a wrong-loop-variable bug a single-job test couldn't.
  [`test_views_error_display.py:89`](../../tests/test_views_error_display.py#L89)
