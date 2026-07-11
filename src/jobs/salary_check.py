"""Salary threshold check for UK Skilled Worker sponsorship eligibility.

A job can be at a fully licensed sponsor and still be legally unable to
sponsor a candidate if the salary is below the required threshold for that
occupation. The rule (gov.uk, rechecked 2026-07-05): the minimum salary is
the HIGHER of a general floor and the "going rate" for the specific SOC
occupation code.

Reference data below (general floor, SOC-code going rates) is a small,
manually-seeded static dataset from the Home Office's published tables -
they change occasionally (not continuously), so a live scraper is
disproportionate for a personal tool. Re-fetch and update if the source
pages change:
  - General floor: https://www.gov.uk/skilled-worker-visa/your-job
  - Going rates:   https://www.gov.uk/government/publications/skilled-worker-visa-going-rates-for-eligible-occupations/skilled-worker-visa-going-rates-for-eligible-occupation-codes
  - Eligible codes: https://www.gov.uk/government/publications/skilled-worker-visa-eligible-occupations/skilled-worker-visa-eligible-occupations-and-codes

Scope: only IT/software/data occupation codes are seeded, since that's the
persona this tool is built for (AI/ML/GenAI/Python engineering roles). The
"lower going rate" column exists for candidates who held a Skilled Worker
CoS continuously since before 4 April 2024 - not relevant for a first-time
applicant, so it isn't used in the threshold calculation here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

GENERAL_THRESHOLD_GBP = 41_700

# code -> (job_type, related_titles incl. our own modern-title heuristics, standard_rate, lower_rate)
SOC_RATES: dict[str, dict] = {
    "2131": {
        "job_type": "IT project managers",
        "related_titles": ["it project manager"],
        "standard_rate": 58_200,
        "lower_rate": 42_600,
    },
    "2132": {
        "job_type": "IT managers",
        "related_titles": [
            "it information manager", "it product manager", "it service delivery manager",
            "it systems manager", "it test manager", "network manager",
            "software development manager", "technical support manager", "it manager",
        ],
        "standard_rate": 55_000,
        "lower_rate": 43_000,
    },
    "2133": {
        "job_type": "IT business analysts, architects and systems designers",
        "related_titles": [
            "computer analyst", "computer scientist", "data architect", "data engineer",
            "it systems architect", "it business analyst", "it solutions architect",
            "solutions designer", "systems designer",
        ],
        "standard_rate": 54_900,
        "lower_rate": 42_400,
    },
    "2134": {
        "job_type": "Programmers and software development professionals",
        "related_titles": [
            "computer games designer", "computer programmer", "software developer",
            "software engineer", "backend developer", "backend engineer",
            "frontend developer", "full stack developer", "full stack engineer",
            "ai engineer", "artificial intelligence engineer", "machine learning engineer",
            "ml engineer", "genai engineer", "generative ai engineer", "nlp engineer",
            "llm engineer", "python developer", "python engineer", "applied ai engineer",
        ],
        "standard_rate": 54_700,
        "lower_rate": 40_000,
    },
    "2135": {
        "job_type": "Cyber security professionals",
        "related_titles": [
            "cyber operational defence specialist", "cyber security management",
            "forensic computer specialist", "secure system development specialist",
            "cyber security engineer", "security engineer",
        ],
        "standard_rate": 48_500,
        "lower_rate": 35_300,
    },
    "2136": {
        "job_type": "IT quality and testing professionals",
        "related_titles": ["qa engineer", "test engineer", "quality assurance engineer", "it tester"],
        "standard_rate": 41_200,
        "lower_rate": 34_500,
    },
    "2137": {
        "job_type": "IT network professionals",
        "related_titles": ["network engineer", "network architect"],
        "standard_rate": 45_600,
        "lower_rate": 38_100,
    },
    "2139": {
        "job_type": "Information technology professionals not elsewhere classified",
        "related_titles": [
            "devops engineer", "mlops engineer", "it consultant", "webmaster",
            "website manager", "site reliability engineer", "sre",
        ],
        "standard_rate": 52_300,
        "lower_rate": 38_700,
    },
    "2141": {
        "job_type": "Web design professionals",
        "related_titles": ["application designer", "ui designer", "ux designer", "ux researcher", "web designer"],
        "standard_rate": 43_800,
        "lower_rate": 31_300,
    },
    "2433": {
        "job_type": "Actuaries, economists and statisticians",
        "related_titles": [
            "actuary", "actuarial analyst", "economist", "mathematician",
            "statistician", "statistical data scientist", "data scientist",
        ],
        "standard_rate": 55_100,
        "lower_rate": 40_700,
    },
    "3131": {
        "job_type": "IT operations technicians",
        "related_titles": [
            "games tester", "network administrator", "systems administrator",
            "quality assurance tester", "software technician",
        ],
        "standard_rate": 35_200,
        "lower_rate": 27_700,
    },
    "3132": {
        "job_type": "IT user support technicians",
        "related_titles": ["it support technician", "helpdesk technician", "service desk analyst"],
        "standard_rate": 33_400,
        "lower_rate": 27_700,
    },
    "3133": {
        "job_type": "Database administrators and web content technicians",
        "related_titles": ["database administrator", "dba", "web content technician"],
        "standard_rate": 34_600,
        "lower_rate": 29_200,
    },
    "3573": {
        "job_type": "Information technology trainers",
        "related_titles": ["it trainer"],
        "standard_rate": 40_000,
        "lower_rate": 32_100,
    },
}

MEETS_THRESHOLD = "meets_threshold"
BELOW_THRESHOLD = "below_threshold"
UNMATCHED_OCCUPATION = "unmatched_occupation"
NO_SALARY_STATED = "no_salary_stated"

_MONEY_RE = re.compile(r"£\s*([\d,]+(?:\.\d+)?)\s*(k\b)?", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SOCMatch:
    code: str
    job_type: str
    matched_on: str


@dataclass(frozen=True)
class SalaryVerdict:
    status: str
    reason: str
    offered_salary: Optional[int] = None
    threshold: Optional[int] = None
    soc_code: Optional[str] = None
    soc_job_type: Optional[str] = None


def parse_salary_gbp(salary_raw: Optional[str]) -> Optional[int]:
    """Extract the lowest £ amount mentioned (the conservative, guaranteed figure).

    Handles "£75,000", "£75000", "£75k". Does not attempt hourly-rate
    conversion - a salary given only as an hourly rate is left unparsed.
    """
    if not salary_raw:
        return None
    amounts = []
    for match in _MONEY_RE.finditer(salary_raw):
        value = float(match.group(1).replace(",", ""))
        if match.group(2):
            value *= 1000
        amounts.append(round(value))
    return min(amounts) if amounts else None


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def match_soc_code(job_title: str) -> Optional[SOCMatch]:
    """Best-effort mapping from a free-text job title to a SOC occupation code.

    Government SOC titles lag behind real industry job titles (there's no
    official code for "GenAI Engineer"), so this is a heuristic subset-token
    match against job types and related titles - not an official
    classification. Requires at least 2 overlapping words so a single
    generic term (e.g. "engineer") can't misclassify (e.g. "Civil Engineer").
    Returns None rather than guessing when nothing matches well.
    """
    title_tokens = _tokenize(job_title)
    best: Optional[SOCMatch] = None
    best_score = 0

    for code, info in SOC_RATES.items():
        candidates = [info["job_type"], *info["related_titles"]]
        for candidate in candidates:
            candidate_tokens = _tokenize(candidate)
            if not candidate_tokens or not candidate_tokens.issubset(title_tokens):
                continue
            score = len(candidate_tokens)
            if score > best_score:
                best_score = score
                best = SOCMatch(code=code, job_type=info["job_type"], matched_on=candidate)

    return best if best_score >= 2 else None


def check_salary_threshold(job_title: str, salary_raw: Optional[str]) -> SalaryVerdict:
    """Check whether a posting's stated salary can legally clear Skilled
    Worker sponsorship - the higher of the general floor and the SOC-code
    going rate. Never guesses: says plainly when it can't fully verify."""
    offered = parse_salary_gbp(salary_raw)
    if offered is None:
        return SalaryVerdict(
            status=NO_SALARY_STATED,
            reason="No parseable salary figure found in the posting - can't check the threshold yet.",
        )

    if offered < GENERAL_THRESHOLD_GBP:
        return SalaryVerdict(
            status=BELOW_THRESHOLD,
            reason=(
                f"£{offered:,} is below the general Skilled Worker floor of "
                f"£{GENERAL_THRESHOLD_GBP:,}/year - this role cannot be sponsored "
                f"regardless of occupation, even at a fully licensed sponsor."
            ),
            offered_salary=offered,
            threshold=GENERAL_THRESHOLD_GBP,
        )

    match = match_soc_code(job_title)
    if match is None:
        return SalaryVerdict(
            status=UNMATCHED_OCCUPATION,
            reason=(
                f"£{offered:,} clears the general floor (£{GENERAL_THRESHOLD_GBP:,}), but "
                f"'{job_title}' couldn't be confidently mapped to a SOC occupation code, "
                f"so the occupation-specific going rate is unverified."
            ),
            offered_salary=offered,
            threshold=GENERAL_THRESHOLD_GBP,
        )

    standard_rate = SOC_RATES[match.code]["standard_rate"]
    threshold = max(GENERAL_THRESHOLD_GBP, standard_rate)

    if offered < threshold:
        return SalaryVerdict(
            status=BELOW_THRESHOLD,
            reason=(
                f"£{offered:,} is below the going rate for SOC {match.code} "
                f"({match.job_type}): £{threshold:,}/year required."
            ),
            offered_salary=offered,
            threshold=threshold,
            soc_code=match.code,
            soc_job_type=match.job_type,
        )

    return SalaryVerdict(
        status=MEETS_THRESHOLD,
        reason=f"£{offered:,} clears the £{threshold:,}/year threshold for SOC {match.code} ({match.job_type}).",
        offered_salary=offered,
        threshold=threshold,
        soc_code=match.code,
        soc_job_type=match.job_type,
    )
