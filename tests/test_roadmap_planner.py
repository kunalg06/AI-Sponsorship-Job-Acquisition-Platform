from datetime import date

from roadmap.planner import RISKY, SKIP, WORTH_IT, days_until, evaluate_new_goal


def test_days_until_counts_calendar_days_forward():
    assert days_until("2026-07-15", today=date(2026, 7, 5)) == 10


def test_days_until_negative_when_past():
    assert days_until("2026-07-01", today=date(2026, 7, 5)) == -4


def test_evaluate_new_goal_risky_when_no_jobs_on_file():
    result = evaluate_new_goal([], ["AWS"], time_cost_days=2, target_date="2026-12-10", today=date(2026, 7, 5))
    assert result.verdict == RISKY
    assert result.jobs_checked == 0


def test_evaluate_new_goal_skip_when_keyword_not_found_in_any_posting():
    jobs = [(1, "AI Engineer", "we use Python and LangChain"), (2, "ML Engineer", "PyTorch and TensorFlow experience")]
    result = evaluate_new_goal(jobs, ["Kubernetes"], time_cost_days=3, target_date="2026-12-10", today=date(2026, 7, 5))
    assert result.verdict == SKIP
    assert result.matching_jobs == []


def test_evaluate_new_goal_skip_when_deadline_passed():
    jobs = [(1, "AI Engineer", "AWS certified preferred")]
    result = evaluate_new_goal(jobs, ["AWS"], time_cost_days=1, target_date="2026-07-01", today=date(2026, 7, 5))
    assert result.verdict == SKIP
    assert result.days_remaining < 0


def test_evaluate_new_goal_risky_when_time_cost_is_large_fraction_of_remaining():
    jobs = [(1, "AI Engineer", "AWS certified preferred for this role")]
    # 10 days remaining, cost of 5 days is 50% - well over the 10% risk threshold.
    result = evaluate_new_goal(jobs, ["AWS"], time_cost_days=5, target_date="2026-07-15", today=date(2026, 7, 5))
    assert result.verdict == RISKY
    assert len(result.matching_jobs) == 1


def test_evaluate_new_goal_worth_it_when_matched_and_cheap():
    jobs = [(1, "AI Engineer", "AWS certified preferred for this role")]
    # 150 days remaining, cost of 2 days is well under 10%.
    result = evaluate_new_goal(jobs, ["AWS"], time_cost_days=2, target_date="2026-12-10", today=date(2026, 7, 5))
    assert result.verdict == WORTH_IT


def test_evaluate_new_goal_keyword_matching_is_case_insensitive():
    jobs = [(1, "AI Engineer", "must be AWS Certified")]
    result = evaluate_new_goal(jobs, ["aws certified"], time_cost_days=1, target_date="2026-12-10", today=date(2026, 7, 5))
    assert len(result.matching_jobs) == 1
