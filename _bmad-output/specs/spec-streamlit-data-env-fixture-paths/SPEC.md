---
id: SPEC-streamlit-data-env-fixture-paths
companions: ["../../project-context.md"]
sources: ["../../implementation-artifacts/deferred-work.md"]
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# streamlit_data_env fixture return shape

## Why

A pain to solve, flagged in the Blind Hunter adversarial review of `spec-streamlit-view-testability.md`. `tests/conftest.py`'s `streamlit_data_env` fixture seeds `data/jobs.db`, `data/profile.db`, and `data/sponsors.db` under a chdir'd `tmp_path`, but returns only `tmp_path` itself — forcing every consumer to re-derive a `tmp_path / "data" / "jobs.db"`-style path inline. The original review called this "worth deciding once, before more test files start depending on it and lock in the current shape by precedent." That prediction has already happened: 4 real call sites across `test_ui_actions.py` and `test_views_error_display.py` now duplicate the same path-join.

## Capabilities

- **CAP-1**
  - **intent:** `streamlit_data_env` returns ready-made paths for every DB it seeds (plus the sandbox root), so consumers use a lookup instead of re-deriving a `data/<name>.db` path inline.
  - **success:** All 4 existing consumer call sites (`test_ui_actions.py:335,349`; `test_views_error_display.py:66,99`) use the fixture's returned lookup instead of path-joining, and every currently-passing test in these 3 files still passes unchanged in behavior.

## Constraints

- Return shape is a dict keyed `root`/`jobs_db`/`profile_db`/`sponsors_db` — matching this same test suite's own existing precedent (`test_ui_actions.py`'s `ui_tailor_env` fixture already returns a dict with `jobs_db`/`profile_db` keys accessed the same way), not a new dataclass/namedtuple pattern competing with it.
- The fixture's seeding behavior (chdir into `tmp_path`, create `data/`, connect+close each of the 3 DBs) is unchanged — only the return value's shape changes.
- `test_app.py`'s 3 usages need no changes — they only use the fixture for its chdir+seed side effect, never touching the returned value.

## Non-goals

- No consolidation of `streamlit_data_env` and `ui_tailor_env` into one shared fixture — they seed different things (all 3 empty DBs for `AppTest` page runs, vs. one specific job + profile + source `.docx` for direct-call tests) and merging them is a bigger refactor than this fix.
- No change to what the `data/*.db` paths actually resolve to on disk — purely how consumers access those same paths.

## Success signal

A future test file needing one of these seeded DB paths looks up a dict key instead of re-deriving `tmp_path / "data" / "<name>.db"`, and the pattern to follow is unambiguous because it already matches this test suite's own precedent.
