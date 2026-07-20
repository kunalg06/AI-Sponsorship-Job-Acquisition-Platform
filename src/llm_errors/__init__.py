"""Shared error handling for every `genai.Client().interactions.create()`
call site across jobs/ and resume/ - each domain stays independent (own
model, own prompt, own schema), but they all need the identical answer to
one cross-cutting question: "which exceptions does a real API failure
raise, and how does a caller turn one into a message a Streamlit user can
actually read?" Same shape of problem `dbcompat` solves for SQLite-vs-Turso.

`google.genai.errors` (the public re-export, and what the SDK's own docs
point to) covers the older `generate_content`-style client - confirmed
live it does NOT cover `client.interactions.create()` (the "_gaos"/
Interactions API every one of these call sites actually uses): a real
`APIConnectionError` from a TLS failure sailed straight through an
`except google.genai.errors.APIError` uncaught and crashed the whole
Streamlit page, since that's a same-named but unrelated class.
`interactions.create()`'s real exceptions live in two separate hierarchies
(verified via each class's `__mro__`, neither is a subclass of the other):
`_gaos.lib.compat_errors` for connection/auth/rate-limit/status failures
(`GeminiNextGenAPIClientError` is the common base for all of them), and
`_gaos.errors` for a response the SDK received but couldn't unmarshal into
the expected shape (`ResponseValidationError`).
"""

from __future__ import annotations

import sys
import traceback
from typing import NoReturn

import httpx
from google.genai._gaos import errors as gaos_response_errors
from google.genai._gaos.lib import compat_errors
from pydantic import ValidationError

GEMINI_CALL_EXCEPTIONS = (
    compat_errors.GeminiNextGenAPIClientError,
    gaos_response_errors.ResponseValidationError,
    httpx.HTTPError,
    ValidationError,
    RuntimeError,  # covers the SDK's bare RuntimeError when no API credentials resolve
)


def raise_llm_call_failure(prefix: str, exc: Exception) -> NoReturn:
    """Raises `SystemExit(f"{prefix}: {detail}")` from `exc` - this
    codebase's own convention for a CLI-layer failure that a Streamlit view
    can catch and pass to `jobs.ui_actions.error_display_text`. Every
    caller MUST be reachable from a view that already wraps its call in
    `except SystemExit` - `SystemExit` is not an `Exception` subclass, so
    Streamlit's own top-level handler (which only catches `Exception`)
    does not stop it, and it would otherwise risk taking down the whole
    server process, not just the current page."""
    detail = str(exc).strip() or type(exc).__name__
    # Server-side diagnostic only: the Streamlit UI only ever sees `detail`
    # above via SystemExit, so the full original traceback would otherwise
    # be lost. Formats `exc` explicitly (not `traceback.print_exc()`'s
    # ambient `sys.exc_info()`) so this is safe to call from outside the
    # `except` block that caught it too (e.g. after a retry loop exhausts).
    try:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    except Exception:
        pass
    raise SystemExit(f"{prefix}: {detail}") from exc
