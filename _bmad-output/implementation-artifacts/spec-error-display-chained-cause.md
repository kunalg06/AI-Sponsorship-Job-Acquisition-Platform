---
title: 'error_display_text surfaces a chained exception message'
type: 'bugfix'
created: '2026-07-17'
status: 'done'
route: 'one-shot'
---

# error_display_text surfaces a chained exception message

## Intent

**Problem:** `error_display_text`'s fallback for an exception with an empty `str()` was just `f"{type(exc).__name__}: (no error message)"` — opaque to the end user even when the exception was chained (`raise ... from cause`, or an implicit `except: raise ...`) from a more informative one.

**Approach:** When `str(exc)` is empty, walk `exc.__cause__`/`exc.__context__` for the first chain link with a non-empty message before falling back to naming a type. Review caught that the naive walk (`exc.__cause__ or exc.__context__`) ignores `raise ... from None` (`__suppress_context__`) — Python's explicit "don't chain this" signal — which would have leaked suppressed context; fixed by mirroring Python's own traceback-formatter rule (explicit `__cause__` always wins, `__context__` only consulted when not suppressed), verified via mutation testing that the new test catches the regression.

## Suggested Review Order

**The fix and the bug it almost introduced**

- The chain-walk and the `__suppress_context__` handling — this is the load-bearing correctness fix the review forced.
  [`ui_actions.py:33`](../../src/jobs/ui_actions.py#L33)

**Tests**

- The `from None` / suppressed-context test is the one that would have caught the original bug (mutation-tested to confirm).
  [`test_ui_actions.py`](../../tests/test_ui_actions.py)
