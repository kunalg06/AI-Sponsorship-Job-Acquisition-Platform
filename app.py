"""Entry point / router for the Streamlit app.

Run with: uv run streamlit run app.py
"""

from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Sponsorship Job Assistant", page_icon="\U0001f9ed", layout="centered")

pg = st.navigation(
    [
        st.Page("views/intake.py", title="Paste a Job Posting", icon="\U0001f9ed", default=True),
        st.Page("views/roadmap.py", title="Roadmap", icon="\U0001f5fa"),
        st.Page("views/jobs_list.py", title="Jobs List", icon="\U0001f4cb"),
    ]
)
pg.run()
