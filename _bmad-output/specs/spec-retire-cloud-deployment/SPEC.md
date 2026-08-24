---
id: SPEC-retire-cloud-deployment
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Retire the cloud-deployment surface

## Why

A mandate to meet, created by a decision already taken. On 2026-08-24 the user deleted the Turso account and removed the Streamlit Community Cloud deployment, making this a local-only personal tool again — which is what `project-context.md` described before the cloud work landed. Roughly 400 lines of code now exist to serve a backend and a host that are gone. That code is not merely idle: `dbcompat.connect()` still branches on `TURSO_*` environment variables and would attempt a sync against a deleted account if any ever reappeared, and the libsql duplicate-detection accommodations in `jobs/cli.py` and `jobs/db.py` catch a bare `ValueError` that plain `sqlite3` can only raise for genuinely unrelated reasons. Dead code that still has a live branch is a trap, not just clutter.

## Capabilities

- **CAP-1**
  - **intent:** Each of the four domain database modules opens its SQLite file directly, with no compatibility layer in between.
  - **success:** `src/dbcompat/` and `tests/test_dbcompat.py` no longer exist; `jobs/db.py`, `register/db.py`, `resume/db.py` and `roadmap/db.py` each call `sqlite3.connect(...)` and set `row_factory = sqlite3.Row`; no module imports `dbcompat`.

- **CAP-2**
  - **intent:** Duplicate detection relies only on the exception plain SQLite actually raises.
  - **success:** `jobs/cli.py`'s `_cmd_stage_indeed` and `jobs/db.py`'s insert path catch `sqlite3.IntegrityError` alone; the bare-`ValueError` branch and its "UNIQUE constraint failed" message check are gone, and restaging an existing `source_job_id` still prints "Already staged ... skipping" without creating a duplicate row.

- **CAP-3**
  - **intent:** The app reads its configuration from the environment alone, with no hosting-platform secrets bridge.
  - **success:** `app.py` contains no reference to `st.secrets`; a run with only `GEMINI_API_KEY` in `.env` starts and reaches every page.

- **CAP-4**
  - **intent:** Packaging and container artifacts that existed only to satisfy Streamlit Community Cloud are removed.
  - **success:** `requirements.txt`, `packages.txt` and `.devcontainer/devcontainer.json` no longer exist; `libsql` is absent from `pyproject.toml`; `uv sync` resolves and `uv run pytest` passes from a clean checkout.

- **CAP-5**
  - **intent:** Comments, ignore rules and the deferred-work ledger stop describing infrastructure that no longer exists.
  - **success:** `.gitignore`'s `turso.env`, `data/*.pre-turso-backup` and `data/*.rescue-*` entries are removed; `register/db.py`'s `INSERT_BATCH_ROWS` and `BUSY_TIMEOUT_MS` comments no longer cite a Turso round trip or Streamlit Cloud as their justification; the open `requirements.txt` dependency-drift ledger entry is closed as resolved-by-removal rather than deleted.

## Constraints

- `src/jobs/pdf_export.py` and LibreOffice support are out of scope and must not be touched. `packages.txt` was only Cloud's apt manifest — `pdf_export.py` locates `soffice` on PATH or at the Windows install path, so PDF export must remain a working local feature after `packages.txt` is deleted.
- No data migration, and no database file is rewritten. `data/*.db` are already plain SQLite files serving the app today. Row counts must be identical after the change: jobs 117, sponsors 142,649, profile 1, roadmap goal 1 / milestones 18.
- `register/db.py`'s `INSERT_BATCH_ROWS = 2000` and `BUSY_TIMEOUT_MS = 15000` keep their values. Both were Turso- and Cloud-motivated, but both are harmless locally, and changing either is a separate performance decision carrying its own risk. Only their justifying comments change.
- The suite must pass at the same count minus the deleted `tests/test_dbcompat.py` cases, with no test weakened or skipped to accommodate the removal.
- No user-visible behaviour changes anywhere: same pages, same CLI commands, same verdicts.

## Non-goals

- Not unpinning `.python-version`. The 3.13 pin exists solely because `libsql` had no Windows wheel above cp313, so removing `libsql` frees it — but taking that freedom is a separate call with its own testing surface.
- Not reverting the multi-row `INSERT` batching or the busy-timeout tuning in `register/db.py`.
- Not refreshing `project-context.md`. It is stale for six weeks of unrelated reasons too; bringing it current is its own job.
- Not adding, evaluating or scaffolding any replacement hosting or persistence backend. Local-only is the destination, not a waypoint.
- Not removing `pdf_export.py`, `python-docx`, or any application feature.

## Success signal

A fresh clone with only `GEMINI_API_KEY` in `.env` runs `uv sync && uv run streamlit run app.py` successfully, every page loads against the existing `data/*.db` files with unchanged row counts, and searching the tree for `turso`, `libsql` or `st.secrets` returns hits only inside historical spec documents under `_bmad-output/`.

## Assumptions

- `data/jobs.db.rescue-20260824T174119Z` is retained until this change is verified, then falls under the user's ordinary cleanup rather than this spec's scope.
- Nothing outside this repository reads `requirements.txt` or `packages.txt` now that the Cloud app is gone.

## Open Questions

- `.python-version` is pinned to 3.13 solely because of `libsql`'s Windows wheel availability, as stated in `pyproject.toml`. Unpin as part of this change, or leave it pinned and decide separately?
