"""Shared visual-identity layer for every Streamlit page - the warm/analog
redesign (Fraunces + IBM Plex, parchment/espresso palette - see
.streamlit/config.toml for the font-face/color tokens themselves).

Streamlit's theme system covers fonts and flat colors but has no concept of
texture, shadow, or a variable font's non-standard axes (Fraunces' "WONK"
axis, which controls how handcrafted/quirky its letterforms look) - this
module covers exactly that gap via one scoped `unsafe_allow_html` block,
and nothing else. It never touches Streamlit's own DOM structure/class
names (those aren't a stable API across versions), only adds new rules and
sets CSS custom properties/variables that existing elements already read
(headings, `st.container(border=True)`, `st.divider()`, `st.metric`)."""

from __future__ import annotations

import streamlit as st

_BASE_CSS = """
<style>
/* Subtle paper-grain texture behind everything - two faint radial washes,
   not a repeating noise image (keeps this file dependency-free and tiny). */
[data-testid="stAppViewContainer"] {
  background-image:
    radial-gradient(circle at 12% 8%, rgba(181, 83, 60, 0.05) 0%, transparent 40%),
    radial-gradient(circle at 88% 92%, rgba(181, 83, 60, 0.04) 0%, transparent 45%);
  background-attachment: fixed;
}

/* Headings default to a warm, moderately handcrafted Fraunces instance -
   the WONK axis is the actual mechanism behind "some pages feel like a
   coach, one page stays a quiet working table." A page can raise or lower
   its own headings' WONK via set_page_wonk() below, which overrides this
   with a more specific selector. */
h1, h2, h3 {
  font-variation-settings: "WONK" 0.55, "opsz" 40;
  letter-spacing: 0.005em;
}

/* Softened cards instead of Streamlit's flat hard-edged bordered containers -
   "cheap and load-bearing": one shadow rule, applies everywhere a
   bordered container is already used, no new component. */
[data-testid="stVerticalBlockBorderWrapper"] {
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12), 0 1px 2px rgba(0, 0, 0, 0.08);
}

/* A warmer divider than Streamlit's default flat rule. */
hr {
  border-top: 1px dashed var(--st-border-color, #DCCBA8);
  opacity: 0.7;
}

/* Mono utility for inline data/labels (dates, ids, scores) - pairs with the
   IBMPlexMono fontFaces already declared in config.toml. */
.mono-label {
  font-family: "IBMPlexMono", monospace;
  font-size: 0.78rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  opacity: 0.75;
}
</style>
"""


def inject_base_css() -> None:
    """Call once, near the top of app.py (after `st.set_page_config`) - CSS
    is global to the page load regardless of which view renders inside it,
    so every other view inherits this without calling it again."""
    st.markdown(_BASE_CSS, unsafe_allow_html=True)


def set_page_wonk(level: str) -> None:
    """Nudge this page's headings toward Fraunces' handcrafted extreme
    ("high" - Intake, Digest: the "coach," not a dashboard) or its calm,
    near-static extreme ("low" - Jobs List: a dense working table, per
    Paige's readability note during the redesign). Anything else (Roadmap,
    Admin) keeps the global default set in `inject_base_css` and doesn't
    need to call this at all."""
    if level not in ("high", "low"):
        raise ValueError(f"set_page_wonk expects 'high' or 'low', got {level!r}")
    # A page's own headings live inside the same stAppViewContainer as
    # everything else - Streamlit gives no per-page DOM scope to hook, so
    # this relies on injection order + selector specificity: this rule is
    # more specific than the base h1/h2/h3 rule above, so it always wins
    # regardless of where in the page body this call happens to run.
    st.markdown(
        f"""<style>
        [data-testid="stAppViewContainer"] h1,
        [data-testid="stAppViewContainer"] h2,
        [data-testid="stAppViewContainer"] h3 {{
          font-variation-settings: {'"WONK" 1, "opsz" 72' if level == "high" else '"WONK" 0, "opsz" 14'};
        }}
        </style>""",
        unsafe_allow_html=True,
    )


def mono(text: str) -> str:
    """Wrap `text` for inline mono-label styling (dates, ids, short data
    tags) - pass the result to `st.markdown(..., unsafe_allow_html=True)`."""
    return f'<span class="mono-label">{text}</span>'
