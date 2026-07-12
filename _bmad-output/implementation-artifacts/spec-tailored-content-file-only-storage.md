---
title: 'Stop persisting tailored resume/cover-letter text in jobs.db'
type: 'refactor'
created: '2026-07-11'
status: 'done'
review_loop_iteration: 2
context: ['{project-root}/_bmad-output/project-context.md']
warnings: []
baseline_commit: 'd9a7d0dd14555f5080cc42ff89a943926a4996a7'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `jobs.db` currently stores the full tailored-resume/cover-letter text (`tailored_resume`, `cover_letter` columns), duplicating what's already written to `cv/generated_cv/<company>/`. Ahead of a Streamlit Cloud deploy, this content should live only as files, never as DB text — and the existing cache-check (`tailor_hash` compared against a full-text DB read) needs to survive that change without a **latent bug**: today's docx file path (`cv/generated_cv/<company>/resume.docx`) is keyed only by company, not by job — a second role at the same company would silently reuse the first role's stale file.

**Approach:** Key every generated **docx** file by `job_id` (matching the existing `{job_id}_resume.txt` txt-export convention already in the codebase, just extended to docx): `cv/generated_cv/<company_slug>/{job_id}_resume.docx`, `{job_id}_cover_letter.docx`. Keep `tailor_hash` (small) in `jobs.db` as the fast "did the input change" check for the **docx path only** (`tailor-docx` CLI + UI); the plain-text `tailor` CLI command drops caching entirely and always regenerates fresh (it's a separate, rarely-used output format with a different directory — not worth a second cache mechanism). A cache hit for the docx path = hash matches AND both files exist on disk; otherwise regenerate. Add a one-time, explicit CLI migration command that (a) backs up any pre-existing DB-resident tailored text to disk, and (b) renames pre-existing old-format company-only-keyed docx files (`resume.docx`/`cover_letter.docx`) to the new job_id-keyed names when the mapping is unambiguous.

## Boundaries & Constraints

**Always:**
- `jobs.db` SCHEMA stops writing to `tailored_resume`/`cover_letter` going forward (new DBs never get these columns; `_ensure_columns()` only adds, never drops, so existing DBs keep the columns but they simply stop being written — do not attempt an `ALTER TABLE DROP COLUMN`).
- `update_tailoring(...)` keeps writing `tailor_hash`, `tailor_evidence_notes`, `tailor_portfolio_gaps`, `tailored_at` — drop the `tailored_resume`/`cover_letter` parameters entirely.
- **Only the docx path (`tailor-docx` CLI + `ui_actions.generate_tailored_docx_for_job`) is cached.** Cache-check: `job["tailor_hash"] == compute_tailor_hash(raw_resume_text, job["raw_text"])` **AND** `{job_id}_resume.docx` **AND** `{job_id}_cover_letter.docx` both exist on disk at the job's company path. Miss on either condition → regenerate and overwrite both files (job_id-keyed, so a resume edit correctly overwrites the same job's files rather than orphaning them). On a cache hit, `evidence_notes`/`portfolio_gaps` are read back from the DB (already small JSON) — no file read needed.
- **The plain-text `tailor` CLI command drops caching entirely.** It always calls the LLM fresh and always (over)writes its `.txt` output files — no hash check, no file-existence check, no dependency on `_get_or_generate_tailor_text`'s docx-specific cache-check. This is a deliberate simplification, not an oversight: that command writes a different artifact (`.txt`) to a different directory (`data/tailored/` by default) than the docx path, and sharing one cache-check function across both formats is exactly what caused the intent-gap bug this amendment fixes.
- `jobs.cli migrate-legacy-tailoring` does two things, both idempotent (skip anything already migrated, no error on re-run):
  1. Scans for rows with non-null `tailored_resume`/`cover_letter` (via `list_legacy_tailored_rows`), writes any missing `{job_id}_resume.txt`/`{job_id}_cover_letter.txt` (plain text) from that DB text.
  2. Scans `cv/generated_cv/<company>/` for old-format `resume.docx`/`cover_letter.docx` (no job_id prefix). For each such company folder, look up how many jobs in `jobs.db` have a `company_name` matching that folder's slug. **Exactly one match** → rename the old files to `{job_id}_resume.docx`/`{job_id}_cover_letter.docx` (skip if the job_id-keyed name already exists — don't overwrite). **Zero or multiple matches** → print a warning naming the ambiguous folder and leave the old files untouched; do not guess.

**Ask First:** none identified — both open design questions (drop `tailor`'s caching vs. give it its own; auto-rename legacy docx vs. leave alone) were resolved with the human in this session.

**Never:**
- Do not touch `jobs.sponsor_check.py`, `jobs.salary_check.py`, `jobs.tracker.py`, `jobs.outreach.py`, `jobs.outreach_db.py`, `register/*`, or `mcp_server/*` — out of scope (outreach message storage is a separate, deferred change).
- Do not implement the semantic "does the new JD align with the old resume" comparison — rejected; costs an LLM call to save an LLM call and can be confidently wrong.
- Do not build a nested-folder-per-job structure — flat, job_id-prefixed filenames in the existing company folder, matching the current txt-export convention.
- Do not remove/rename the `tailored_resume`/`cover_letter` DB columns themselves (no `DROP COLUMN`) — just stop writing new data to them.
- Do not guess which job an ambiguous legacy docx file belongs to — warn and skip instead of guessing wrong.
- Do not add any cache-check (hash or file-existence) to the plain-text `tailor` command — that mechanism was explicitly dropped for this command, not just left unfinished.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First `tailor-docx` for a job | No existing files, no `tailor_hash` | Generates via LLM, writes `{job_id}_resume.docx`/`{job_id}_cover_letter.docx`, updates DB | No error expected |
| `tailor-docx` re-run, nothing changed | `tailor_hash` matches, both files exist | Skips regeneration entirely; no LLM call | No error expected |
| `tailor-docx`, second role, same company | Different `job_id`, same `company_slug`, first job's files already exist | Generates a **new** `{job_id}_resume.docx` — does not touch or reuse the first job's files | No error expected |
| `tailor-docx`, resume updated since last tailor | `tailor_hash` mismatch (same `job_id`) | Regenerates, **overwrites** this job's existing files | No error expected |
| `tailor-docx`, files deleted manually, hash unchanged | `tailor_hash` matches but file(s) missing | Treated as a miss — regenerates and rewrites the files | No error expected |
| Plain `tailor` command, run twice in a row | Same job, unchanged resume+JD | Calls the LLM again both times, always overwrites `.txt` output — this is the intended (no-cache) behavior now | No error expected |
| Legacy DB row (pre-existing `tailored_resume` text, no file yet) | `migrate-legacy-tailoring` run | Writes `{job_id}_resume.txt`/`{job_id}_cover_letter.txt` from the DB text if no file already exists | Skips (no-op) if a file already exists there |
| Legacy old-format docx, one matching job | `resume.docx`/`cover_letter.docx` exist, exactly one job in DB for that company | Renamed to `{job_id}_resume.docx`/`{job_id}_cover_letter.docx` | No error expected |
| Legacy old-format docx, ambiguous | `resume.docx`/`cover_letter.docx` exist, zero or 2+ jobs in DB for that company | Warning printed naming the folder; files left untouched | No error (warning, not exception) |

</frozen-after-approval>

## Spec Change Log

### 2026-07-12 — intent_gap resolved
- **Triggering findings:** (1) `_cmd_tailor` called the shared docx-based cache-check without accounting for its own different output format (`.txt`, different directory) — reproduced directly: repeated calls with unchanged resume+job re-invoked the LLM every time. (2) The migration boundary covered only DB-resident text, not pre-existing old-format company-only-keyed docx files already on disk in the real repo (`cv/generated_cv/Bending_Spoons/resume.docx` existed alongside the new job_id-keyed migration output) — the next `tailor-docx` run for that real job would have silently paid for an unnecessary LLM regeneration, and the file would vanish from the UI's generated-files browser.
- **What was amended:** Approach/Boundaries now explicitly scope caching to the docx path only (plain-text `tailor` drops caching entirely, human-confirmed). `migrate-legacy-tailoring`'s Boundaries now include renaming unambiguous legacy docx files, with an explicit warn-and-skip rule for ambiguous cases (human-confirmed).
- **Known-bad state avoided:** silent recurring LLM-cost regression for the plain-text `tailor` command; orphaned/invisible real production files on the next `tailor-docx` run.
- **KEEP instructions (preserve on re-derivation):** `_tailored_docx_paths(company_name, job_id, out_dir)` job_id-keyed path helper — correct, keep as-is. `_tailor_docx_for_job` shared helper used by both `tailor-docx` CLI and `ui_actions.generate_tailored_docx_for_job` — correct pattern, keep. `list_legacy_tailored_rows`'s `PRAGMA table_info` guard against querying nonexistent columns on a fresh DB — correct, keep. The docx-path cache-hit condition (hash match AND both docx files exist) — correct as originally implemented for `tailor-docx` specifically, keep. `views/jobs_list.py`'s glob-based (`*_resume.docx`) multi-job browser — correct, keep (will naturally pick up renamed legacy files with no further change needed). Additionally fix, in this same pass: the `estimate_page_risk` warning silently disappearing on a docx cache hit (recompute it — it's a local/non-LLM heuristic, cheap either way) is being noted here as one further Adversarial Review Ready fix worth doing; and this time add tests that exercise the actual CLI command wiring (`_cmd_tailor`, `_cmd_tailor_docx`, `_cmd_migrate_legacy_tailoring` via `build_parser()`), not just the internal helper functions directly — the previous pass's test gap is what let the `_cmd_tailor` bug through undetected.

### 2026-07-12 — bad_spec resolved (page-risk cache-hit mechanism)

- **Triggering findings** (adversarial review + edge-case review of the first implementation attempt, run in parallel with no shared context, both converging on the same root cause independently):
  1. The first attempt satisfied "recompute the page-risk warning on a cache hit" by diffing the cached output `.docx` against whatever `.docx` currently sits in the resume source directory (`_diff_rewritten_paragraphs`). `tailor_hash` covers only resume *text* (from `profile.db`) + job text — it has no relationship to the source `.docx` file's actual content. If the source `.docx` is edited/replaced/reformatted without touching `profile.db`, the hash still matches, a cache hit is declared, and the diff silently reconstructs a wrong or incomplete rewritten-paragraph map (mismatched paragraph indices are dropped rather than erroring), producing a misleading warning with no error surfaced.
  2. Worse: this diffing approach calls `_find_source_resume_docx(resume_dir)` **unconditionally**, even on a cache hit — so if the source `.docx` has been deleted since the cached files were generated, a routine "nothing changed" rerun now raises `SystemExit`, even though the frozen Boundaries above explicitly say a cache hit needs "no file read."
- **Root cause:** the original Task list said to "recompute the page-risk warning on a docx cache hit too" but did not specify *how* — the natural-looking implementation (diff the two docx files) reintroduces a file-read dependency and a staleness assumption that directly contradicts the frozen cache-hit contract above. This is a spec gap in the non-frozen Tasks/Code Map, not the frozen Intent.
- **What was amended:** the mechanism is changed from *recompute-by-diffing-on-every-hit* to *compute-once-and-store*: `estimate_page_risk`'s result is computed at generation time (when `freshly_generated` is true, right where `rewritten` is already in hand) and persisted as a new small nullable text field (e.g. `tailor_page_risk_warning`) in `jobs.db` alongside `tailor_evidence_notes`/`tailor_portfolio_gaps`. On a cache hit, the warning is read back from the DB verbatim — no source `.docx` read, no diffing, no staleness assumption, no `_find_source_resume_docx` call on the hit path at all. This is the same pattern already used for `evidence_notes`/`portfolio_gaps` on a cache hit, just extended to cover the warning too. `_diff_rewritten_paragraphs` should not exist in the re-derived code — delete the approach entirely rather than patching it.
- **Known-bad state avoided:** misleading page-risk warnings after a source `.docx` swap; `SystemExit` crashing a routine cache-hit rerun after the source `.docx` is deleted; silent index-mismatch swallowing masking both.
- **Also fold in during re-derivation** (smaller, independently-confirmed findings from the same two reviews — mechanically fixable, no further design decisions needed):
  1. `_cmd_migrate_legacy_tailoring`'s docx-rename matching (`j["company_name"] and _sanitize_filename(j["company_name"]) == company_dir.name`) requires a truthy `company_name`, so a legacy folder that was originally created under the `job_{id}`/`unknown_company` fallback slug (for a job with no `company_name`) can never match and is permanently reported "ambiguous" even when exactly one job corresponds to it. Fix: when computing candidate matches, also compute each company-less job's fallback slug (`f"job_{j['id']}"`, mirroring `_tailored_docx_paths`'s own fallback) and match folders against that too.
  2. The rename step (`old_resume.rename(new_resume)` / `old_cover.rename(new_cover)`) has no exception handling — one `OSError` (locked file, permission denied) on one company folder aborts the entire migration loop for every subsequent folder, working against the command's own "safe, idempotent, re-runnable" design goal. Fix: wrap each rename in `try/except OSError`, print a warning naming the file and the error, and continue to the next company folder.
  3. `_cmd_migrate_legacy_tailoring` queries jobs via a raw `conn.execute("SELECT id, company_name FROM jobs")` instead of a `db.py` helper, inconsistent with this file's own role as the DB access boundary (and with this same diff's `list_legacy_tailored_rows` addition). Fix: add a small `db.py` helper (e.g. `list_job_ids_and_company_names(conn)`) and use it here instead.
  4. `_cmd_tailor_docx` recomputes `_tailored_docx_paths(...)` a second time after calling `_tailor_docx_for_job` purely to print the `.name` of each file — duplicated logic that can drift from the helper's own internal computation. Fix: have `TailorDocxResult` carry `resume_path`/`cover_letter_path` directly instead of just `out_dir`.
  5. No test exercises `--force` on `tailor-docx` (a boolean-logic slip like dropping `not force` from the cache-hit condition would go undetected). Fix: add a test that a forced re-run regenerates even when the hash matches and both files exist.
  6. No test covers the partial-migration state where one of `{job_id}_resume.txt`/`{job_id}_cover_letter.txt` already exists on disk but the other doesn't. Fix: add a test asserting only the missing one is written.
- **Rejected as noise (reviewed and dismissed, not applicable):** an empty-string (not NULL) legacy `tailored_resume`/`cover_letter` value being silently skipped by the migration's truthy check — an empty string has no content to back up, so skipping it loses nothing real. A hypothetical partial-schema state where only one of the two legacy columns exists — unreachable in practice since `_ensure_columns()` adds both together. A hypothetical malformed filename (non-numeric job_id prefix) in the generated-files browser — would require external manual file placement outside the app's control, not a realistic path for a single-user local tool. A speculative "what if the two docx paths passed in don't correspond to the job being processed" defense — there is exactly one call site that constructs these paths (`_tailored_docx_paths(job["company_name"], job["id"], out_dir)`), always from the same job dict being processed, so there is no concrete path by which they could diverge.

## Code Map

- `src/jobs/db.py` -- `SCHEMA`, `update_tailoring(...)` — drop text params/writes for `tailored_resume`/`cover_letter`; add a new nullable `tailor_page_risk_warning` column (`_ensure_columns()`-style additive migration); `update_tailoring(...)` gains a `page_risk_warning: Optional[str]` param and writes it; add `list_legacy_tailored_rows(conn)` for migration; add `list_job_ids_and_company_names(conn)` (small helper — id + company_name for all jobs, used by the legacy-docx-rename matcher instead of a raw ad-hoc query)
- `src/jobs/cli.py` -- `_get_or_generate_tailor_text` (docx-only cache-check; on a cache hit, reads `evidence_notes`/`portfolio_gaps`/`page_risk_warning` back from the DB — no file read at all), `_cmd_tailor` (plain text — drops caching, calls the LLM path directly), `_tailor_docx_for_job` (computes `estimate_page_risk` ONLY when `freshly_generated`, passes it to `update_tailoring(...)` for storage; on a cache hit, uses the DB-stored warning directly — do NOT re-read/diff any `.docx` on a cache hit; delete `_diff_rewritten_paragraphs` entirely, it should not exist in the re-derived code), `_cmd_tailor_docx`, `_sanitize_filename`, `DEFAULT_GENERATED_CV_DIR`, `_cmd_migrate_legacy_tailoring` (uses `list_job_ids_and_company_names(conn)` instead of a raw query; matches company-less jobs' fallback slug too; wraps each `rename()` call in `try/except OSError`, warns and continues) — job_id-keyed docx cache-check, decoupled `_cmd_tailor`, new `migrate-legacy-tailoring` subcommand (DB-text backup + legacy-docx rename)
- `src/jobs/ui_actions.py` -- `generate_tailored_docx_for_job` — mirrors the docx cache-check via the shared `_tailor_docx_for_job` helper
- `views/intake.py` -- the `already_generated` file-existence check — job_id-keyed paths (already correct from the reverted pass — reapply)
- `views/jobs_list.py` -- the generated-files browser and `already_generated` check — job_id-keyed paths (already correct from the reverted pass — reapply)
- `tests/test_jobs_db.py` -- `test_update_tailoring_persists_all_fields` -- no longer asserts full-text columns; asserts `tailor_page_risk_warning` round-trips (including `None`)
- `tests/test_jobs_cli.py` -- new; must include tests that call `_cmd_tailor`/`_cmd_tailor_docx`/`_cmd_migrate_legacy_tailoring` through `build_parser()`/`args.func(args)`, not only the internal helpers; must include a `--force` test on `tailor-docx` and a partial-migration test (one of the two `.txt` files already exists, the other doesn't); must include a cache-hit test where the source `.docx` in the resume dir is deleted/replaced after the cached files were generated, asserting the cache hit still succeeds with no file read and returns the DB-stored warning unchanged
- `data/jobs.db`, `cv/generated_cv/Bending_Spoons/` -- real existing data (1 DB row + old-format docx files) — migration target, not a fixture

## Tasks & Acceptance

**Execution:**
- [x] `src/jobs/db.py` -- remove `tailored_resume`/`cover_letter` from `SCHEMA` and `update_tailoring(...)`; add nullable `tailor_page_risk_warning` column; `update_tailoring(...)` gains and writes a `page_risk_warning` param; add `list_legacy_tailored_rows(conn)` (guard via `PRAGMA table_info` before querying columns that may not exist on a fresh DB); add `list_job_ids_and_company_names(conn)`
- [x] `src/jobs/cli.py` -- rewrite `_get_or_generate_tailor_text` to be used ONLY by the docx path, with the job_id-keyed hash+file-existence cache-check; on a cache hit, read `evidence_notes`/`portfolio_gaps`/`page_risk_warning` back from the DB with NO file read of any kind; rewrite `_cmd_tailor` to call the tailoring generation directly (no cache-check, no dependency on `_get_or_generate_tailor_text`) and always (over)write its `.txt` output; add `migrate-legacy-tailoring` subcommand doing both the DB-text backup AND the unambiguous-legacy-docx rename (with the warn-and-skip rule for ambiguous cases), using `list_job_ids_and_company_names(conn)` and matching company-less jobs via their fallback slug too, with each rename wrapped in `try/except OSError` (warn and continue on failure)
- [x] `src/jobs/cli.py` -- compute `estimate_page_risk` ONLY on fresh generation (never by diffing docx files on a cache hit) and pass it to `update_tailoring(...)` for storage; do not implement `_diff_rewritten_paragraphs` or any equivalent docx-diffing mechanism
- [x] `src/jobs/ui_actions.py` -- keep/reapply the shared `_tailor_docx_for_job` helper for `generate_tailored_docx_for_job`
- [x] `views/intake.py` -- reapply the job_id-keyed `already_generated` check
- [x] `views/jobs_list.py` -- reapply the job_id-keyed browser + `already_generated` check
- [x] `tests/test_jobs_db.py` -- update `test_update_tailoring_persists_all_fields` (incl. `tailor_page_risk_warning` round-trip); add a test for `list_legacy_tailored_rows` (populated legacy columns, and a fresh DB with no legacy columns at all)
- [x] `tests/test_jobs_cli.py` -- cover the full I/O matrix above, INCLUDING calls through `build_parser()`/`args.func(args)` for `_cmd_tailor`, `_cmd_tailor_docx`, and `_cmd_migrate_legacy_tailoring` (not only the internal helper functions); include a `--force` test on `tailor-docx`; a partial-migration test (one `.txt` file exists, the other doesn't); and a cache-hit test where the source `.docx` is deleted/replaced after generation, asserting the hit still succeeds with no file read and the DB-stored warning is returned unchanged

**Acceptance Criteria:**
- Given two different jobs at the same company, when both are `tailor-docx`'d, then each gets its own `{job_id}_resume.docx`/`{job_id}_cover_letter.docx` and neither overwrites the other.
- Given a job already `tailor-docx`'d once with an unchanged resume and unchanged job text, when `tailor-docx` is requested again, then no LLM call is made, the existing files are left untouched, no `.docx` file anywhere is read, and the page-risk warning returned matches what was stored at generation time.
- Given a job already `tailor-docx`'d once, when the source `.docx` in the resume directory is subsequently deleted or replaced and `tailor-docx` is requested again with nothing else changed, then the cache hit still succeeds (no `SystemExit`, no crash) because no source file read is required on a cache hit.
- Given the plain-text `tailor` command run twice in a row on the same job with nothing changed, when the second run happens, then the LLM is called again both times (no caching) and the `.txt` files are overwritten — this is the intended behavior, not a bug.
- Given the real `data/jobs.db` row (id=1) and the real old-format `cv/generated_cv/Bending_Spoons/resume.docx`/`cover_letter.docx`, when `migrate-legacy-tailoring` is run, then `1_resume.txt`/`1_cover_letter.txt` are written from the DB text, AND `resume.docx`/`cover_letter.docx` are renamed to `1_resume.docx`/`1_cover_letter.docx` (exactly one job for that company), and running the command again is a full no-op.
- Given a company folder with old-format docx files but zero or multiple matching jobs in the DB, when `migrate-legacy-tailoring` is run, then a warning is printed and those files are left untouched (not renamed, not deleted).
- Given a legacy docx folder whose only matching job has no `company_name` (folder named via the `job_{id}`/`unknown_company` fallback), when `migrate-legacy-tailoring` is run, then it is matched and renamed like any other unambiguous case, not permanently reported as ambiguous.
- Given a `rename()` call fails with `OSError` for one company folder during migration, when the command runs, then a warning is printed for that folder and migration continues processing the remaining company folders (does not abort the whole run).

## Design Notes

Rejected during design: a semantic "does the new job description still align with the existing generated resume" check as the cache gate — costs an LLM call to save an LLM call, can be confidently wrong. Rejected in this amendment: sharing one cache-check function across both the docx and plain-text output formats — they're different artifacts with different directories and different lifecycles; forcing them through the same check is what caused the intent-gap bug. `tailor_hash` (deterministic from resume+JD) plus job_id-keyed docx paths gives a correct, free cache check for the docx path specifically; the plain-text path simply doesn't need one.

## Verification

**Commands:**
- `uv run pytest` -- expected: full suite green, no regressions
- `uv run python -m jobs.cli migrate-legacy-tailoring` -- expected: reports writing `1_resume.txt`/`1_cover_letter.txt` (or reports nothing to do for the `.txt` step if they already exist from an earlier attempt), reports renaming `resume.docx`/`cover_letter.docx` to `1_resume.docx`/`1_cover_letter.docx`; run twice, second run reports nothing to do
- Manual: paste two different job postings for the same company through the Streamlit intake flow, tailor-docx both, confirm two distinct `{job_id}_resume.docx` files exist under that company's folder
- Manual: run the plain `tailor` CLI command twice in a row on the same job, confirm (via a mock/log) that the LLM is invoked both times
- Manual/test: `tailor-docx` a job, then delete the source `.docx` from the resume directory, then `tailor-docx` the same job again with nothing else changed -- confirm the cache hit still succeeds (no crash) and returns the same warning as before

## Suggested Review Order

**Schema change**

- The nullable column that replaces DB-resident tailored text with a stored risk-warning string — the whole refactor's storage-shape change starts here.
  [`db.py:51`](../../src/jobs/db.py#L51)

- `update_tailoring(...)` drops the `tailored_resume`/`cover_letter` params and writes `tailor_page_risk_warning` instead — the write side of the same change.
  [`db.py:247`](../../src/jobs/db.py#L247)

**Docx cache-check (the core fix)**

- Cache hit reads `evidence_notes`/`portfolio_gaps`/`page_risk_warning` back from the DB with no file read — this is what the previous review round's docx-diffing bug was replaced with.
  [`cli.py:270`](../../src/jobs/cli.py#L270)

- Orchestrates cache hit vs. miss; computes `estimate_page_risk` only on fresh generation, never by re-reading a cached docx.
  [`cli.py:402`](../../src/jobs/cli.py#L402)

- `generate_tailored_docx_for_job` now delegates to the shared helper above — also where the missing `None`-job guard was added.
  [`ui_actions.py:30`](../../src/jobs/ui_actions.py#L30)

**Job-id-keyed paths**

- Shared path helper — job_id-keyed, not company-only-keyed, fixing the original same-company-two-jobs collision.
  [`cli.py:374`](../../src/jobs/cli.py#L374)

- Shared fallback-slug helper — added this round so the docx-path naming and the legacy-migration matcher can't drift apart.
  [`cli.py:363`](../../src/jobs/cli.py#L363)

**Plain-text `tailor` decoupling**

- Rewritten to call the LLM directly with no cache dependency — deliberately uncached, a different artifact/directory than the docx path.
  [`cli.py:322`](../../src/jobs/cli.py#L322)

**Legacy-data migration**

- Entry point — orchestrates the DB-text backup and the legacy-docx rename in one idempotent command.
  [`cli.py:606`](../../src/jobs/cli.py#L606)

- DB-text backup half — writes `.txt` files from pre-existing `tailored_resume`/`cover_letter` columns.
  [`cli.py:491`](../../src/jobs/cli.py#L491)

- Legacy-docx rename half — per-folder failure isolation (`try/except OSError`) added this round so one bad folder can't abort the rest.
  [`cli.py:520`](../../src/jobs/cli.py#L520)

- `list_legacy_tailored_rows` — `PRAGMA table_info` guard so a fresh DB without the legacy columns doesn't error.
  [`db.py:281`](../../src/jobs/db.py#L281)

- `list_job_ids_and_company_names` — used by the migration matcher instead of an ad-hoc query.
  [`db.py:301`](../../src/jobs/db.py#L301)

**UI binding**

- `already_generated` check switched to job_id-keyed paths — reflects the new naming scheme in the intake flow.
  [`intake.py:354`](../../views/intake.py#L354)

- Same switch in the jobs-list view, plus the glob-based multi-job generated-files browser.
  [`jobs_list.py:275`](../../views/jobs_list.py#L275)

**Tests**

- CLI commands tested through `build_parser()`/`args.func(args)`, not just internal helpers — including the not-found and cache-integrity cases added across both review rounds.
  [`test_jobs_cli.py`](../../tests/test_jobs_cli.py)

- `update_tailoring`/legacy-row-listing coverage, including the fresh-DB-with-no-legacy-columns case.
  [`test_jobs_db.py`](../../tests/test_jobs_db.py)
