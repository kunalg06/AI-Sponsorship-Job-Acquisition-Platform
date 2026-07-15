---
id: SPEC-streamlit-version-floor
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Streamlit version floor

## Why

A mandate to meet. `pyproject.toml` declares `streamlit` with no version floor, yet `views/admin.py` already has a hard dependency on `st.dialog` (added in Streamlit 1.31) and `UploadedFile.file_id`. An environment that resolves an older Streamlit fails outright with an unrelated `AttributeError`, not a clear version-conflict message. Flagged in the Blind Hunter adversarial review (2026-07-14) of the admin-destructive-safety diff.

## Capabilities

- **CAP-1**
  - **intent:** `pyproject.toml`'s `streamlit` dependency declares its real minimum version, documenting an API requirement the codebase already has.
  - **success:** `pyproject.toml`'s `streamlit` entry specifies `>=1.31`; a dependency resolve against an environment offering only `streamlit<1.31` fails at install time with a version-conflict message, not later at runtime with an unrelated `AttributeError`.

## Constraints

- No other dependency's version specifier changes — every other entry (`pydantic`, `google-genai`, `python-docx`, `mcp`, `pytest`) keeps its existing unbounded floor, matching this project's deliberate convention elsewhere.

## Non-goals

- A project-wide dependency-pinning policy decision — the separate, still-open deferred-work item about `requirements.txt`'s floating `-e .` install is untouched.
- Adding CI or any automated check that verifies the floor is respected — this project intentionally has no CI.

## Success signal

- A developer or deploy environment resolving dependencies against an old Streamlit gets a clear, actionable version-conflict error instead of a confusing runtime `AttributeError` deep in `views/admin.py`.
