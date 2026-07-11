from jobs.salary_check import (
    BELOW_THRESHOLD,
    GENERAL_THRESHOLD_GBP,
    MEETS_THRESHOLD,
    NO_SALARY_STATED,
    UNMATCHED_OCCUPATION,
    check_salary_threshold,
    match_soc_code,
    parse_salary_gbp,
)


def test_parse_salary_gbp_takes_the_lower_bound_of_a_range():
    assert parse_salary_gbp("£75,000 - £95,000 + equity") == 75_000


def test_parse_salary_gbp_handles_k_suffix():
    assert parse_salary_gbp("£70k - £90k") == 70_000


def test_parse_salary_gbp_returns_none_when_no_amount_present():
    assert parse_salary_gbp("Competitive salary") is None
    assert parse_salary_gbp(None) is None


def test_match_soc_code_finds_genai_engineer_under_programmers_code():
    match = match_soc_code("Senior Machine Learning Engineer (GenAI)")
    assert match is not None
    assert match.code == "2134"


def test_match_soc_code_finds_data_scientist_under_actuaries_economists_statisticians_code():
    # Per gov.uk: 2433's related titles explicitly include "Statistical data
    # scientists" - the official home for modern "Data Scientist" titles.
    match = match_soc_code("Graduate data scientist")
    assert match is not None
    assert match.code == "2433"


def test_match_soc_code_finds_data_engineer_under_business_analysts_code():
    match = match_soc_code("Data Engineer")
    assert match is not None
    assert match.code == "2133"


def test_match_soc_code_does_not_force_a_match_for_unrelated_titles():
    # A single generic word ("Engineer") shouldn't misclassify a non-IT role.
    assert match_soc_code("Civil Engineer") is None
    assert match_soc_code("Warehouse Operative") is None


def test_check_salary_threshold_below_general_floor_regardless_of_occupation():
    verdict = check_salary_threshold("Machine Learning Engineer", "£35,000")
    assert verdict.status == BELOW_THRESHOLD
    assert verdict.threshold == GENERAL_THRESHOLD_GBP


def test_check_salary_threshold_below_occupation_specific_going_rate():
    # 2134 standard rate is £54,700 - above the general floor but below that.
    verdict = check_salary_threshold("Software Engineer", "£45,000")
    assert verdict.status == BELOW_THRESHOLD
    assert verdict.soc_code == "2134"
    assert verdict.threshold == 54_700


def test_check_salary_threshold_meets_threshold():
    verdict = check_salary_threshold("Senior Machine Learning Engineer (GenAI)", "£75,000 - £95,000")
    assert verdict.status == MEETS_THRESHOLD
    assert verdict.soc_code == "2134"
    assert verdict.offered_salary == 75_000


def test_check_salary_threshold_unmatched_occupation_but_above_general_floor():
    verdict = check_salary_threshold("Chief Vibes Officer", "£50,000")
    assert verdict.status == UNMATCHED_OCCUPATION
    assert verdict.offered_salary == 50_000


def test_check_salary_threshold_no_salary_stated():
    verdict = check_salary_threshold("Machine Learning Engineer", "Competitive")
    assert verdict.status == NO_SALARY_STATED
