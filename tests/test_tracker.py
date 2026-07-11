from datetime import datetime, timedelta, timezone

from jobs.tracker import days_since, due_milestone


def _iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_days_since_computes_whole_days_elapsed():
    assert days_since(_iso_days_ago(3.5)) == 3


def test_due_milestone_none_when_not_yet_due():
    assert due_milestone(_iso_days_ago(2), None, None, None) is None


def test_due_milestone_day_3_due():
    assert due_milestone(_iso_days_ago(3), None, None, None) == 3


def test_due_milestone_none_when_already_sent():
    assert due_milestone(_iso_days_ago(3), _iso_days_ago(0), None, None) is None


def test_due_milestone_catches_up_to_latest_overdue():
    # 10 days since applying, nothing sent yet - day 7 is the latest passed milestone (day 14 not reached).
    assert due_milestone(_iso_days_ago(10), None, None, None) == 7


def test_due_milestone_day_14_after_3_and_7_already_sent():
    assert due_milestone(_iso_days_ago(14), _iso_days_ago(11), _iso_days_ago(7), None) == 14
