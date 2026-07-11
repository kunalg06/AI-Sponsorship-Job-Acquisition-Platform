"""Goal/roadmap planning: fixed-deadline awareness + grounded goal readjustment.

Deliberately has no LLM call. Whether a new goal (e.g. "should I get a
certification") is worth the time is a question of real data - does it show
up in job postings you've actually seen, and what does the time cost against
your remaining runway - not a question an LLM should be asked to feel good
about. No default encouragement; a plain, checkable verdict instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

WORTH_IT = "worth_it"
RISKY = "risky"
SKIP = "skip"

# The real deadline for a *signed offer* - not Dec 31. UK hiring materially
# slows from mid-December through early January, and Certificate of
# Sponsorship + visa processing adds real weeks after an offer.
DEFAULT_TARGET_DATE = "2026-12-10"
DEFAULT_GOAL_DESCRIPTION = "Land a signed UK Skilled Worker sponsorship offer"

# Seeded from the agreed July-December 2026 plan: prep and applying run in
# parallel from week one, never "study first, apply once ready."
DEFAULT_MILESTONES: list[tuple[str, str]] = [
    ("2026-07", "Lock profile/one-pager, get sponsor+salary+match pipeline running"),
    ("2026-07", "DSA fundamentals refresh: arrays, hashmaps, two pointers, sliding window"),
    ("2026-07", "Start portfolio project #1"),
    ("2026-07", "Apply immediately to anything clearing the match threshold - don't wait to feel ready"),
    ("2026-08", "DSA: trees, graphs, light DP"),
    ("2026-08", "AI system design fundamentals: RAG pipelines, LLM serving trade-offs, vector DB choices"),
    ("2026-08", "Keep applying weekly"),
    ("2026-08", "First mock interviews"),
    ("2026-09", "Timed DSA practice under pressure, harder patterns"),
    ("2026-09", "AI system design deeper: multi-agent orchestration, latency/cost trade-offs"),
    ("2026-09", "Portfolio project #2 if #1 landed cleanly"),
    ("2026-09", "First real interviews should be landing if July applications are converting"),
    ("2026-10", "Interview cycle running - spaced repetition on weak spots, behavioral prep"),
    ("2026-10", "Mock interviews with real feedback"),
    ("2026-10", "Never let the application pipeline hit zero, even mid-loop"),
    ("2026-11", "Peak interview + offer-negotiation window"),
    ("2026-11", "Triage anything not moving - last full month before the December slowdown"),
    ("2026-12", "Close, sign, start Certificate of Sponsorship / visa paperwork"),
]


@dataclass(frozen=True)
class GoalEvaluation:
    keywords: list[str]
    time_cost_days: float
    days_remaining: int
    jobs_checked: int
    matching_jobs: list[tuple[int, str]]
    verdict: str
    reasoning: str


def days_until(target_date: str, today: Optional[date] = None) -> int:
    today = today or date.today()
    return (date.fromisoformat(target_date) - today).days


def evaluate_new_goal(
    job_rows: list[tuple[int, str, str]],
    keywords: list[str],
    time_cost_days: float,
    target_date: str,
    *,
    today: Optional[date] = None,
) -> GoalEvaluation:
    """job_rows: (job_id, job_title, raw_text) for every job posting on file."""
    lowered = [k.strip().lower() for k in keywords if k.strip()]
    matching = [
        (job_id, job_title)
        for job_id, job_title, raw_text in job_rows
        if any(k in raw_text.lower() for k in lowered)
    ]
    remaining = days_until(target_date, today)
    keyword_list = ", ".join(keywords)

    if not job_rows:
        verdict = RISKY
        reasoning = (
            "No job postings on file yet to check this against - can't ground the "
            "decision in real data. Paste in a few real postings first, or treat "
            "this as a guess, not a grounded call."
        )
    elif not matching:
        verdict = SKIP
        reasoning = (
            f"'{keyword_list}' doesn't appear in any of the {len(job_rows)} job postings "
            f"you've pasted in. Don't spend {time_cost_days:g} days on it without real "
            f"evidence it's asked for - that time is better spent applying or prepping."
        )
    elif remaining <= 0:
        verdict = SKIP
        reasoning = f"The deadline ({target_date}) has already passed or is today - no time budget left for anything new."
    elif time_cost_days > remaining * 0.1:
        verdict = RISKY
        reasoning = (
            f"'{keyword_list}' appears in {len(matching)}/{len(job_rows)} postings you've seen, "
            f"so there's real signal. But {time_cost_days:g} days is "
            f"{time_cost_days / remaining:.0%} of your {remaining} remaining days - weigh it "
            f"against what else that time buys (interview prep, more applications)."
        )
    else:
        verdict = WORTH_IT
        reasoning = (
            f"'{keyword_list}' appears in {len(matching)}/{len(job_rows)} postings you've seen, "
            f"and {time_cost_days:g} days is a small slice of your {remaining} remaining days. "
            f"Reasonable to spend the time."
        )

    return GoalEvaluation(
        keywords=keywords,
        time_cost_days=time_cost_days,
        days_remaining=remaining,
        jobs_checked=len(job_rows),
        matching_jobs=matching,
        verdict=verdict,
        reasoning=reasoning,
    )
