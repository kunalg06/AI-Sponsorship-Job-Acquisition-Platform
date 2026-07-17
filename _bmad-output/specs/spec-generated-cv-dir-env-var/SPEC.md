---
id: SPEC-generated-cv-dir-env-var
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# GENERATED_CV_DIR environment variable

## Why

A pain to solve. The CLI's `tailor-docx`/`outreach`/`follow-up`/`migrate-legacy-outreach` commands accept a `--out-dir` override, but the Streamlit UI always reads and writes at the hardcoded `DEFAULT_GENERATED_CV_DIR` ("cv/generated_cv") — a message drafted via the CLI with a custom `--out-dir` shows as "(message file not found)" in the UI's Message-history expander, since the two paths silently diverge.

## Capabilities

- **CAP-1**
  - **intent:** `DEFAULT_GENERATED_CV_DIR` reads from a `GENERATED_CV_DIR` environment variable when set, falling back to the current `"cv/generated_cv"` default when unset.
  - **success:** With `GENERATED_CV_DIR` set in the environment, `jobs.cli.DEFAULT_GENERATED_CV_DIR` equals that value; with it unset, the constant is unchanged (`"cv/generated_cv"`).

- **CAP-2**
  - **intent:** A single `GENERATED_CV_DIR` env var setting makes the CLI's own `--out-dir` defaults and every UI read/write site consistent, without any of them needing individual changes.
  - **success:** With `GENERATED_CV_DIR` set, a job tailored via the CLI's default `--out-dir` produces files the UI finds at the same path, and vice versa.

## Constraints

- Must not change current default behavior when `GENERATED_CV_DIR` is unset — existing installs with no `.env` entry for it must resolve to the exact same `"cv/generated_cv"` path as today.
- Must read the env var at the same module-load point `DEFAULT_GENERATED_CV_DIR` is currently defined (after `load_dotenv()` already runs in `jobs/cli.py`), not lazily per-call, so every consumer that already imports the constant as a plain string keeps working unchanged — no consumer needs to switch from importing a constant to calling a function.

## Non-goals

- Not a UI settings panel or any per-session/per-user override — a single process-wide env var, matching this codebase's existing `GEMINI_API_KEY` convention exactly.
- Not making the UI follow an explicit one-off `--out-dir` override on a single CLI invocation — only the shared, env-var-configured default is unified; a deliberate ad-hoc override remains a CLI-only, UI-invisible choice, same as today.

## Success signal

A test sets `GENERATED_CV_DIR` in the environment before importing/reloading `jobs.cli` and asserts `DEFAULT_GENERATED_CV_DIR` reflects it; another test confirms it's unchanged when the env var is absent.
