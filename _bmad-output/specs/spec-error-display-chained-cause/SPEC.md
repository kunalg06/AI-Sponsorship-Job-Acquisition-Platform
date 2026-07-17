---
id: SPEC-error-display-chained-cause
companions: []
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# error_display_text surfaces a chained exception's message

## Why

A pain to solve. `error_display_text` (`src/jobs/ui_actions.py`) falls back to `f"{type(exc).__name__}: (no error message)"` whenever `str(exc)` is empty. That fallback is opaque to the end user — it names a Python type, not what went wrong — even when the exception was raised via `raise ... from cause` (or implicitly chained through `except: raise ...`) and `cause`'s own `str()` is informative. The fallback currently discards that available detail.

## Capabilities

- **CAP-1**
  - **intent:** When `str(exc).strip()` is empty, `error_display_text` walks `exc`'s chain (`__cause__`, then `__context__`) and surfaces the first non-empty message found instead of the bare type-name fallback.
  - **success:** An exception constructed with an empty `str()` but a `__cause__` (or `__context__`) whose `str()` is non-empty renders that chained message via `error_display_text`, not `f"{type(exc).__name__}: (no error message)"`.

## Constraints

- Walk the full chain (`cause`, then `cause`'s own `__cause__`/`__context__`, and so on), not just one level — stop at the first link whose `str()` is non-empty.
- If no link in the chain (including `exc` itself) has a non-empty `str()`, keep the type-name fallback, naming the innermost (most specific) exception in the chain rather than always the outermost.
- Must not raise or loop forever on a cyclical chain (Python does not prevent constructing one) — track visited exception ids or cap traversal depth.
- Each link's `str()` gets the same try/except protection `error_display_text` already applies to the top-level `exc`, since any exception type's `__str__` can itself raise.

## Non-goals

- Not a redesign of error presentation or copy tone — no new UI, no "caused by:"-style prefixing of the surfaced message (see Open Questions).
- Not touching the 10 `st.error(error_display_text(exc))` call sites in `views/*.py` — they already call this function; only its internal fallback logic changes.

## Success signal

A test raises an exception with an empty `str()` chained (`raise EmptyErr() from ValueError("disk full")`) and asserts `error_display_text(exc) == "disk full"` (or the agreed-on formatted form), where today it would assert the bare type-name fallback.

## Open Questions

- Should the surfaced chained message be prefixed (e.g. `"EmptyErr: (no message) - caused by: disk full"`) to avoid reading as the outer exception's own text, or returned bare? Leaning bare, matching this function's existing plain-passthrough behavior for a normal `str(exc)` — low-stakes copy choice, decide during implementation.
