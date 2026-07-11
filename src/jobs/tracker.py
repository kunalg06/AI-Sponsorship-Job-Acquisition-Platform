"""Application tracker: due-reminder computation (no I/O, no side effects).

Per docs/v1-scope.md: two actions only (applied/discard). Reminders are
repeating day 3/7/14 nudges, never auto-sent - just surfaced with a drafted
follow-up for you to review and send yourself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

REMINDER_DAYS = (3, 7, 14)

APPLIED = "applied"
DISCARDED = "discarded"


def days_since(applied_at_iso: str) -> int:
    applied_dt = datetime.fromisoformat(applied_at_iso)
    now = datetime.now(timezone.utc)
    return (now - applied_dt).days


def due_milestone(
    applied_at_iso: str,
    reminder_3_sent_at: Optional[str],
    reminder_7_sent_at: Optional[str],
    reminder_14_sent_at: Optional[str],
) -> Optional[int]:
    """The most urgent overdue, not-yet-actioned reminder milestone (3, 7, or
    14), or None if nothing is currently due. If several milestones have
    passed since the last follow-up (e.g. you missed day 3 and it's now day
    10), only the latest is surfaced - one follow-up covers the gap."""
    days = days_since(applied_at_iso)
    sent_at = {3: reminder_3_sent_at, 7: reminder_7_sent_at, 14: reminder_14_sent_at}
    overdue = [d for d in REMINDER_DAYS if days >= d and sent_at[d] is None]
    return max(overdue) if overdue else None
