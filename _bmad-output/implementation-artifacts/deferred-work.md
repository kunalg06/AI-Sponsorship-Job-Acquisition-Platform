# Deferred Work Ledger

- source_spec: `_bmad-output/implementation-artifacts/spec-mcp-tool-wrappers.md`
  summary: `mcp_server.tools.track_application` has no audit trail (who/when/what) for its mutating calls (mark applied/discarded).
  evidence: An MCP client can trigger a permanent tracker-state mutation with no logging anywhere of the invocation, making it impossible to reconstruct after the fact what an autonomous agent changed and when — flagged in the 2026-07-11 adversarial review of `spec-mcp-tool-wrappers.md`.
  status: done 2026-07-12
  resolution: Implemented via `_bmad-output/implementation-artifacts/spec-mcp-track-application-audit-trail.md` — new `mcp_audit_log` table written by `track_application` for every attempt reaching a DB connection (success, unknown-job-id rejection, mutation-raises rejection); invalid-action calls stay a zero-I/O fast-fail and are not logged (resolved intent_gap). 153/153 tests passing.

- source_spec: none
  summary: Add a `requirements.txt` (with `-e .`) so this app can be deployed to Streamlit Community Cloud, which doesn't use `uv`.
  evidence: Split from a combined "prep for Streamlit Cloud deployment" intent on 2026-07-11 — independently shippable, no coupling to the tailoring-storage change or the Admin page, deferred in favor of tackling the higher-risk tailoring-storage change first.
  status: done 2026-07-12
  resolution: Implemented via `_bmad-output/implementation-artifacts/spec-requirements-txt-streamlit-cloud.md` — added a one-line `requirements.txt` (`-e .`); verified with a clean `pip install -r requirements.txt` in an isolated venv (no `uv`) that it correctly builds and installs the app plus all dependencies. Documented in README. Review surfaced two new deploy-readiness gaps (secrets bridging, dependency-pinning drift), logged as separate deferred entries above — the requirements.txt file itself is complete and working.

- source_spec: none
  summary: Add an "Admin" Streamlit page with (a) CV upload -> `resume.extract`/`resume.db` profile registration and (b) a sponsor-register-ingest button calling `register.ingest.ingest(...)` — needed because Streamlit Cloud has no shell access and `data/`/`cv/`/`.env` are gitignored, so a fresh cloud deploy starts empty.
  evidence: Split from the same "prep for Streamlit Cloud deployment" intent on 2026-07-11 — independently shippable, deferred in favor of tackling the higher-risk tailoring-storage change first.

- source_spec: `_bmad-output/implementation-artifacts/spec-tailored-content-file-only-storage.md`
  summary: Stop persisting outreach-message text (`outreach_messages.message`) in `jobs.db` — write drafted outreach messages to `cv/generated_cv/<company>/{job_id}_outreach_{channel}.txt` instead, keeping only metadata (channel, contact_name, char_count) in the DB.
  evidence: Split out on 2026-07-11 because the spec was ~2900 tokens (well over the 1600 target). Outreach has no caching bug to fix (it was never cache-checked, always freshly generated), unlike resume/cover-letter — bundled only by the shared "stop storing full text in DB" theme, not by any shared mechanism or risk. Narrowing the spec to the resume/cover-letter fix + legacy-data migration keeps the two genuinely coupled concerns together.

- source_spec: `_bmad-output/implementation-artifacts/spec-tailored-content-file-only-storage.md`
  summary: `views/intake.py`'s and `views/jobs_list.py`'s "Regenerate tailored resume & cover letter" button always calls `generate_tailored_docx_for_job` with the default `force=False`, so clicking it when the docx cache is already valid is silently a no-op cache hit, not an actual regeneration — the button's label overpromises.
  evidence: Flagged in round-2 adversarial review (2026-07-12) of `spec-tailored-content-file-only-storage.md`. Pre-existing gap, not introduced by this spec's refactor — the UI never had a way to force regeneration before or after this change; the refactor only touched the caching mechanism, not this UI wiring. A real fix would add an explicit "force regenerate" control, which is a UI-design decision out of scope for this refactor.

- source_spec: `_bmad-output/implementation-artifacts/spec-tailored-content-file-only-storage.md`
  summary: `_cmd_tailor` (and the shared tailoring-generation path) assumes `TailoredApplication.evidence_notes`/`.portfolio_gaps` are always lists with no defensive check; every test mocks the LLM call so this assumption is never exercised against a malformed real response.
  evidence: Flagged in round-2 adversarial review (2026-07-12). Pre-existing assumption that predates this refactor (relies on the `TailoredApplication` pydantic model's contract) — not caused by this diff, just surfaced incidentally while reviewing it.

- source_spec: `_bmad-output/implementation-artifacts/spec-tailored-content-file-only-storage.md`
  summary: None of the `.txt`/`.docx` write paths in `jobs/cli.py` (tailoring output, legacy-migration backup) use a temp-file-then-rename pattern, so a crash mid-write can leave a partial file that still passes the "does it exist" cache/already-generated checks used throughout this codebase.
  evidence: Flagged in round-2 adversarial + edge-case review (2026-07-12). Pre-existing pattern across the whole codebase (no file write anywhere uses atomic replace), not specific to this diff — a real hardening item but broader than this spec's scope.

- source_spec: none
  summary: `.gitignore` excludes `data/*.db` and `cv/` (personal resume/CV content) but not `data/tailored/` — the plain-text `tailor` CLI command and `migrate-legacy-tailoring`'s DB-text-backup step both write real tailored-resume/cover-letter text there, which is currently untracked-but-committable in this public repo.
  evidence: Discovered 2026-07-12 while committing the tailored-content-file-only-storage spec's implementation — `data/tailored/1_resume.txt`/`1_cover_letter.txt` (real personal content, written by this session's `migrate-legacy-tailoring` run) showed up as untracked (`??`) rather than ignored. Deliberately left out of that commit; `.gitignore` should add `data/tailored/` (or a broader `data/` pattern) before any future `git add` in this area.
  status: done 2026-07-12
  resolution: Added `data/tailored/` to `.gitignore`; confirmed via `git status` that the directory no longer shows as untracked.

- source_spec: `_bmad-output/implementation-artifacts/spec-requirements-txt-streamlit-cloud.md`
  summary: On a real Streamlit Community Cloud deploy, `app.py`'s `load_dotenv()` will silently no-op (no `.env` file ships to Cloud) and `GEMINI_API_KEY` will be `None` — Cloud delivers secrets via `st.secrets`, not `os.environ`, and nothing in the codebase bridges the two.
  evidence: Flagged in the adversarial review (2026-07-12) of the `requirements.txt` one-shot change. `requirements.txt` only fixes the *build* step; every Gemini-calling code path (`jobs/extract.py`, `jobs/tailor.py`, `jobs/outreach.py`) would still fail at the first LLM call on a fresh Cloud deploy without this fix.

- source_spec: `_bmad-output/implementation-artifacts/spec-requirements-txt-streamlit-cloud.md`
  summary: `requirements.txt` uses a floating `-e .` install (pip resolves fresh against `pyproject.toml`'s loose version floors) rather than a frozen list generated from `uv.lock`, so Streamlit Cloud can silently resolve a different dependency graph than what's tested locally — and nothing detects that drift since this repo intentionally has no CI.
  evidence: Flagged in the adversarial review (2026-07-12) of the `requirements.txt` one-shot change. A deliberate trade-off for now (matches the deferred-work item's original "-e ." instruction and this project's no-CI-by-design convention), but worth revisiting if a Cloud deploy ever breaks from an unexpected dependency bump.
