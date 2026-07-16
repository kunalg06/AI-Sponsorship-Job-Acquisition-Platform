---
title: 'CV supersede-profile dialog dismiss fix'
type: 'bugfix'
created: '2026-07-17'
status: 'done'
route: 'one-shot'
---

# CV supersede-profile dialog dismiss fix

## Intent

**Problem:** `views/admin.py`'s CV-upload "supersede current profile" dialog reopens after being dismissed via X/backdrop/ESC, since only the in-dialog Cancel button cleared the session state that gates re-showing it. The original review called this unfixable without a state-machine redesign, since `st.dialog` had no documented dismissal callback at the time.

**Approach:** That premise no longer held — the actually-installed Streamlit gained an `on_dismiss` parameter (confirmed via web search: added in 1.48.0). Extracted Cancel's cleanup into a shared helper, wired it as `on_dismiss`. Review caught a critical gap this fix itself introduced: the `streamlit>=1.31` floor doesn't guarantee `on_dismiss` exists, and since it's applied at decorator/import time, an environment resolving `>=1.31,<1.48` would crash the *entire* Admin page on load — bumped the floor to `>=1.48`. Review also mutation-tested the original tests and proved they missed a real Cancel/`on_dismiss` divergence regression; added a proper `AppTest`-driven test through the real dialog to close that gap (verified by mutation-testing it myself, before and after).

## Suggested Review Order

**The fix and its critical dependency gap**

- The shared helper and its `on_dismiss` wiring.
  [`admin.py:142`](../../views/admin.py#L142), [`admin.py:152`](../../views/admin.py#L152)

- The version-floor bump that closes the "whole page crashes on an unsatisfying-but->=1.31 environment" gap review caught.
  [`pyproject.toml:11`](../../pyproject.toml#L11)

**Tests**

- The real behavioral proof: drives the actual Cancel button through the real dialog via `AppTest` — mutation-tested to confirm it catches a Cancel/`on_dismiss` divergence.
  [`test_admin.py:69`](../../tests/test_admin.py#L69)

- Direct unit test on the extracted helper (weaker execution model, documented as such; kept as a fast supplementary check).
  [`test_admin.py:36`](../../tests/test_admin.py#L36)

- Source-level check that `on_dismiss` is wired to the shared helper, not a diverged duplicate — `AppTest` can't simulate a real dismiss event to prove this behaviorally.
  [`test_admin.py:56`](../../tests/test_admin.py#L56)
