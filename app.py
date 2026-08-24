"""Entry point / router for the Streamlit app.

Run with: uv run streamlit run app.py
"""

from __future__ import annotations

import os
import sys

import streamlit as st
import truststore
from dotenv import load_dotenv

load_dotenv()

# httpx (used by the Gemini SDK for every LLM call) verifies TLS against
# certifi's bundled CAs by default - on a machine whose trust anchor isn't in
# that bundle (confirmed live: CERTIFICATE_VERIFY_FAILED against any HTTPS
# host, not just Gemini's), every LLM call fails before reaching the API at
# all. The OS trust store already has what's needed - it's the same gap
# [tool.uv]'s system-certs = true works around for package installs, just
# for this process's own outbound calls instead. inject_into_ssl() patches
# ssl.SSLContext process-wide, so this one call covers every httpx client
# built anywhere downstream (jobs.tailor, jobs.extract, jobs.match_score,
# jobs.docx_tailor, jobs.outreach, resume.extract), not just this file's own
# requests.
truststore.inject_into_ssl()

# This app runs locally only, so `.env` (loaded above) is the single source
# of configuration - there is no hosting platform delivering secrets by
# another route. GENERATED_CV_DIR is optional and has a working default
# (cv/generated_cv), so GEMINI_API_KEY is the only value worth warning about.
if "GEMINI_API_KEY" not in os.environ:
    print(
        "GEMINI_API_KEY not found in the environment or .env - "
        "Gemini calls will fail until it is configured.",
        file=sys.stderr,
    )

st.set_page_config(page_title="Sponsorship Job Assistant", page_icon="\U0001f9ed", layout="centered")

from views.theme import inject_base_css  # noqa: E402 (must follow set_page_config)

inject_base_css()

pg = st.navigation(
    [
        st.Page("views/intake.py", title="Paste a Job Posting", icon="\U0001f9ed", default=True),
        st.Page("views/digest.py", title="Daily Digest", icon="☕"),
        st.Page("views/roadmap.py", title="Roadmap", icon="\U0001f5fa"),
        st.Page("views/jobs_list.py", title="Jobs List", icon="\U0001f4cb"),
        st.Page("views/automate.py", title="Automate", icon="\U0001f916"),
        st.Page("views/admin.py", title="Admin", icon="\u2699"),
    ]
)
pg.run()
