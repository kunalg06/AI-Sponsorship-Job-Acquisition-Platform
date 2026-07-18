"""Entry point / router for the Streamlit app.

Run with: uv run streamlit run app.py
"""

from __future__ import annotations

import os
import sys

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# On Streamlit Community Cloud there is no .env file, so load_dotenv() above
# is a no-op - secrets are delivered via st.secrets instead. Bridge it into
# os.environ (the only place genai.Client() and other os.getenv()-based
# lookups check) so the rest of the pipeline doesn't need to know which
# environment it's running in. st.secrets raises if no secrets.toml/directory
# exists anywhere (e.g. local dev using only .env) - that's expected, not an
# error, so it's swallowed the same way load_dotenv() silently no-ops when
# .env is missing. A real environment variable / .env value always wins over
# st.secrets if both are somehow set.
if "GEMINI_API_KEY" not in os.environ:
    try:
        os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

if "GEMINI_API_KEY" not in os.environ:
    print(
        "GEMINI_API_KEY not found in the environment, .env, or st.secrets - "
        "Gemini calls will fail until one of these is configured.",
        file=sys.stderr,
    )

# Same bridge as GEMINI_API_KEY above, for jobs.cli.DEFAULT_GENERATED_CV_DIR's
# optional GENERATED_CV_DIR override - unlike the API key, this one has a
# working default (cv/generated_cv), so there's no matching "not found" warning.
if "GENERATED_CV_DIR" not in os.environ:
    try:
        os.environ["GENERATED_CV_DIR"] = st.secrets["GENERATED_CV_DIR"]
    except Exception:
        pass

# Same bridge again, for dbcompat.connect()'s Turso lookup (see
# src/dbcompat/__init__.py) - each of the 4 domain databases (jobs,
# sponsors, profile, roadmap) has its own optional URL/token pair. Both
# vars have to be present for a given database to actually use Turso, so
# there's no "not found" warning here either - a database missing either
# one just falls back to local SQLite, which is the correct behavior for
# local dev (no Turso secrets configured at all) rather than an error.
for _prefix in ("JOBS", "SPONSORS", "PROFILE", "ROADMAP"):
    for _suffix in ("URL", "TOKEN"):
        _key = f"TURSO_{_prefix}_{_suffix}"
        if _key not in os.environ:
            try:
                os.environ[_key] = st.secrets[_key]
            except Exception:
                pass

st.set_page_config(page_title="Sponsorship Job Assistant", page_icon="\U0001f9ed", layout="centered")

from views.theme import inject_base_css  # noqa: E402 (must follow set_page_config)

inject_base_css()

pg = st.navigation(
    [
        st.Page("views/intake.py", title="Paste a Job Posting", icon="\U0001f9ed", default=True),
        st.Page("views/digest.py", title="Daily Digest", icon="☕"),
        st.Page("views/roadmap.py", title="Roadmap", icon="\U0001f5fa"),
        st.Page("views/jobs_list.py", title="Jobs List", icon="\U0001f4cb"),
        st.Page("views/admin.py", title="Admin", icon="\u2699"),
    ]
)
pg.run()
