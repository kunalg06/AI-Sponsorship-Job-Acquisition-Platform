---
title: 'streamlit_data_env fixture return shape'
type: 'chore'
created: '2026-07-16'
status: 'done'
route: 'one-shot'
---

# streamlit_data_env fixture return shape

## Intent

**Problem:** `tests/conftest.py`'s `streamlit_data_env` fixture returned bare `tmp_path`, forcing every consumer to re-derive `tmp_path / "data" / "jobs.db"`-style paths inline. Checked current usage: 4 real call sites across 2 files already duplicated the same path-join, exactly as a prior review predicted would happen.

**Approach:** Return a dict of pre-built paths (`root`/`jobs_db`/`profile_db`/`sponsors_db`) instead, following the same dict-keyed-by-DB-name convention `test_ui_actions.py`'s own `ui_tailor_env` fixture already uses — no new pattern invented. Updated the 4 real consumers. Review caught two real gaps in the fix itself: the seeding calls and the returned dict built the same file path two different ways (could silently diverge later), and nothing tested the fixture's own return-shape contract (so 3 of the 4 keys had zero direct coverage) — both fixed.

## Suggested Review Order

**The fixture**

- Single consolidated path computation, reused for both seeding and the returned dict.
  [`conftest.py:17`](../../tests/conftest.py#L17)

- New test locking in the fixture's own contract (keys, types, that the files actually exist) - the coverage gap review found.
  [`test_conftest.py:9`](../../tests/test_conftest.py#L9)

**Consumers** (all identical: path-join replaced with a dict lookup)

- [`test_ui_actions.py:335`](../../tests/test_ui_actions.py#L335), [`test_ui_actions.py:349`](../../tests/test_ui_actions.py#L349)
- [`test_views_error_display.py:66`](../../tests/test_views_error_display.py#L66), [`test_views_error_display.py:99`](../../tests/test_views_error_display.py#L99)
