---
title: 'requirements.txt for Streamlit Community Cloud deployment'
type: 'chore'
created: '2026-07-12'
status: 'done'
route: 'one-shot'
---

# requirements.txt for Streamlit Community Cloud deployment

## Intent

**Problem:** Streamlit Community Cloud deploys with plain `pip install -r requirements.txt` and has no support for `uv`/`uv.lock`, but this repo had no `requirements.txt` at all — a fresh Cloud deploy had no way to install the app's dependencies.

**Approach:** Add a single-line `requirements.txt` containing `-e .`, so pip performs an editable install of the project and pulls its dependency list straight from `pyproject.toml`. Verified with a clean `pip install -r requirements.txt` in an isolated venv (no `uv` involved).

## Suggested Review Order

- [requirements.txt](../../requirements.txt) -- the one-line addition itself
- [README.md:44-50](../../README.md#deploying-to-streamlit-community-cloud) -- new "Deploying to Streamlit Community Cloud" note explaining the file's purpose and its relationship to `uv.lock`
- [_bmad-output/implementation-artifacts/deferred-work.md](deferred-work.md) -- original item marked done; two new deploy-readiness gaps logged (secrets bridging via `st.secrets`, dependency-pinning drift between `requirements.txt` and `uv.lock`)
