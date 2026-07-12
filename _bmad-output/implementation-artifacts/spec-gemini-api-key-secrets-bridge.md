---
title: 'Bridge GEMINI_API_KEY from st.secrets to os.environ for Streamlit Community Cloud'
type: 'bugfix'
created: '2026-07-12'
status: 'done'
route: 'one-shot'
---

# Bridge GEMINI_API_KEY from st.secrets to os.environ for Streamlit Community Cloud

## Intent

**Problem:** On Streamlit Community Cloud, `app.py`'s `load_dotenv()` silently no-ops (no `.env` file ships to Cloud) and every Gemini-calling code path's `genai.Client()` reads `GEMINI_API_KEY` from `os.environ` — so a Cloud deploy would fail at the first LLM call with `GEMINI_API_KEY` unset, even after `requirements.txt` made the build itself work. Cloud delivers secrets via `st.secrets`, not `os.environ`, and nothing bridged the two.

**Approach:** In `app.py`, after `load_dotenv()`, bridge `st.secrets["GEMINI_API_KEY"]` into `os.environ` when not already set there — an existing `.env`/real environment variable always wins. Swallow the case where no secrets source exists at all (expected for local dev using only `.env`), and print a stderr diagnostic if the key is still missing after all sources are checked, so a misconfigured Cloud deploy at least leaves a trace in the platform's log viewer.

## Suggested Review Order

- [app.py:8-33](../../app.py) -- the bridging logic itself, plus the new stderr diagnostic when the key remains unset after all lookups
- [README.md:44-50](../../README.md#deploying-to-streamlit-community-cloud) -- documents where to set the secret on Cloud and the env-wins-over-secrets precedence
- [.gitignore:1-3](../../.gitignore) -- excludes `.streamlit/secrets.toml`, the local-dev equivalent of Cloud's secrets file
- [_bmad-output/implementation-artifacts/deferred-work.md](deferred-work.md) -- original item marked done; one new deferred item logged (no automated test for the bridging logic — `app.py` executes the full page router as an import side effect, so testing it cleanly requires a design decision on where to extract the logic, out of scope for this fix)
