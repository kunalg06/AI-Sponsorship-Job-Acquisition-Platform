---
title: 'Admin page: CV-upload resume profile registration'
type: 'feature'
created: '2026-07-12'
status: 'done'
review_loop_iteration: 0
context: ['{project-root}/_bmad-output/project-context.md']
baseline_commit: '7d772b85b9f6d908098980999481c27d1e311e71'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Streamlit Community Cloud has no shell access, and `data/`/`cv/` are gitignored, so a fresh Cloud deploy also has no candidate profile — there is currently no way to register one except `uv run python -m resume.cli add --file ...` from a local terminal, which Cloud doesn't offer. This is the (a) half of the original combined "Admin page" deferred item (the sponsor-register-ingest (b) half already shipped).

**Approach:** Add a "Resume / CV Profile" section to the existing `views/admin.py` Admin page: a file uploader accepting `.docx` or `.txt`, and a button that extracts raw text (new `resume.extract.extract_text_from_docx` for `.docx`; direct UTF-8 decode for `.txt`, matching the CLI's existing plain-text path) then runs the already-complete `resume.extract.extract_profile` → `resume.db.insert_profile` pipeline, exactly as `resume/cli.py`'s `_cmd_add` already does.

## Boundaries & Constraints

**Always:**
- Reuse `resume.extract.extract_profile` and `resume.db.insert_profile`/`get_latest_profile` unchanged — do not duplicate or reimplement the Gemini extraction or DB-insert logic.
- Add exactly one new function, `extract_text_from_docx(file) -> str`, to `resume/extract.py` (pure `python-docx` paragraph-join, no Gemini call, no `client` kwarg needed) — the missing piece the CLI's plain-text-only `_read_input` doesn't have.
- Show the latest stored profile (name/seniority, via `get_latest_profile`) on page load, or "No profile stored yet", before any upload happens.
- Gate the "Extract & Register Profile" button on a file actually being uploaded (`disabled=uploaded_file is None`), matching `views/intake.py`'s existing button-disabling convention.
- Wrap extraction+insert in `st.spinner(...)` and `try/except Exception as exc: st.error(str(exc))`, matching this codebase's existing pattern (and the sponsor-register section already in `views/admin.py`). On success, `st.success(...)` naming the stored profile, then `st.rerun()`.
- Define `PROFILE_DB = "data/profile.db"` as a local module constant in `views/admin.py`, matching `views/intake.py`'s existing identical constant — do not import `DEFAULT_DB` from `resume.cli` (keeps this section's DB-path style consistent with the rest of `views/`, unlike the sponsor-register section's spec-directed CLI-constant reuse).

**Ask First:** none identified.

**Never:**
- Do not modify `resume/db.py`, `resume/cli.py`, `jobs/docx_tailor.py`, or `register/*` — this section only adds one new pure-text-extraction function to `resume/extract.py` plus new UI in `views/admin.py`.
- Do not add narrative-core upload/registration to this page — that's a separate stored concept (`resume.db.insert_narrative`) not named by this deferred item; out of scope.
- Do not add a preview/edit step for the extracted profile before saving — insert directly, matching the CLI's own `_cmd_add` (no review step there either).
- Do not add authentication or access control — single-user personal tool, same decision already made for the MCP audit-trail and sponsor-register-ingest features.
- Do not add support for other CV formats (`.pdf`, `.rtf`, etc.) — only `.docx` (via the new helper) and `.txt` (via direct decode), matching what the CLI already effectively supports.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No profile yet, nothing uploaded | Fresh `data/profile.db` (or none yet) | Page shows "No profile stored yet"; upload widget present; button disabled | N/A |
| Successful .docx upload | Valid `.docx` CV uploaded, button clicked | Spinner shown; text extracted via `extract_text_from_docx`; profile extracted and stored; success message names the profile; latest-profile display updates after rerun | N/A |
| Successful .txt upload | Valid UTF-8 `.txt` CV uploaded, button clicked | Raw bytes decoded directly (no docx parsing); same success path as `.docx` | N/A |
| Corrupted/invalid .docx | File with `.docx` extension but not a valid docx package | `python-docx` raises; original exception shown via `st.error`; no profile row inserted | Caught by the shared `except Exception` |
| Non-UTF-8 .txt | `.txt` file with invalid encoding | `UnicodeDecodeError` shown via `st.error`; no profile row inserted | Caught by the shared `except Exception` |

</frozen-after-approval>

## Code Map

- `src/resume/extract.py` -- add `extract_text_from_docx(file) -> str` using `docx.Document(file)` + paragraph join
- `views/admin.py` -- add a "Resume / CV Profile" section: latest-profile display, file uploader, extract-and-register button

## Tasks & Acceptance

**Execution:**
- [x] `src/resume/extract.py` -- add `import docx` and `extract_text_from_docx(file) -> str` (`"\n".join(p.text for p in docx.Document(file).paragraphs)`)
- [x] `views/admin.py` -- add `PROFILE_DB = "data/profile.db"`; a "Resume / CV Profile" section showing `get_latest_profile` (or "No profile stored yet"); `st.file_uploader("Upload your CV", type=["docx", "txt"])`; an "Extract & Register Profile" button (disabled until a file is uploaded) that routes `.docx` through `extract_text_from_docx` and anything else through direct UTF-8 decode, then calls `extract_profile` → `insert_profile`, wrapped in `st.spinner`/`try-except`/`st.success`+`st.rerun()` on success
- [x] `tests/test_resume_extract.py` -- add a test for `extract_text_from_docx` building a real in-memory/`tmp_path` `python-docx` `Document()` and asserting the joined paragraph text comes back correctly (matches this file's existing no-mocking-for-non-LLM-logic convention)

**Acceptance Criteria:**
- Given no `data/profile.db` exists yet and no file uploaded, when the Admin page loads, then it shows "No profile stored yet" without raising, and the button is disabled.
- Given a valid `.docx` CV is uploaded and the button is clicked, when extraction succeeds, then a new profile row is inserted, a success message appears, and the latest-profile display updates after rerun.
- Given a valid `.txt` CV is uploaded, when the button is clicked, then the same success path completes via direct UTF-8 decode (no docx parsing attempted).
- Given an invalid/corrupted `.docx` is uploaded, when the button is clicked, then the original exception is shown via `st.error` and no profile row is inserted.

## Verification

**Commands:**
- `uv run pytest tests/test_resume_extract.py -v` -- expected: existing tests pass, new `extract_text_from_docx` test green
- `uv run pytest` -- expected: full suite green, no regressions

**Manual checks (if no CLI):**
- Run `uv run streamlit run app.py`, open "Admin", upload a real `.docx` CV, confirm the profile extracts/stores correctly and compare against `uv run python -m resume.cli add --file <same file as .txt>` for a sanity check on parity.

## Suggested Review Order

**Text extraction**

- New pure helper: paragraph-join only (tables/headers deliberately out of scope — see deferred-work.md).
  [`extract.py:56`](../../src/resume/extract.py#L56)

**Admin page wiring**

- Upload → extract → register flow: stream-safety (`seek(0)`), case-insensitive `.docx` detection, empty-text guard, and success message parity with the CLI's `#{profile_id}` output — all patched after review.
  [`admin.py:75`](../../views/admin.py#L75)

- Latest-profile display and file uploader, gated correctly with a disabled button until a file is selected.
  [`admin.py:60`](../../views/admin.py#L60)

**Peripherals**

- New test for the docx-text-extraction helper (pure logic, no mocking needed).
  [`test_resume_extract.py:32`](../../tests/test_resume_extract.py#L32)

- Ledger: original combined Admin-page item's (a) half marked done; 3 new findings logged for later attention.
  [`deferred-work.md`](deferred-work.md)
