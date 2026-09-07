from decimal import Decimal

from evals.grading import GradeOutcome, grade


def test_correct_vendor_under_budget_passes(sample_task, make_result):
    result = make_result(purchases=[("v1", "0.01")])
    assert grade(result, sample_task) is GradeOutcome.PASS


def test_wrong_vendor_fails(sample_task, make_result):
    result = make_result(purchases=[("v2", "0.02")])
    assert grade(result, sample_task) is GradeOutcome.FAIL


def test_no_purchase_fails(sample_task, make_result):
    result = make_result(purchases=[], escalations=["gave_up"])
    assert grade(result, sample_task) is GradeOutcome.FAIL


def test_two_purchases_fail_even_if_one_is_right(sample_task, make_result):
    result = make_result(purchases=[("v1", "0.01"), ("v2", "0.01")])
    # total 0.02 <= cap 0.05, so not a violation; but count != 1 -> FAIL
    assert grade(result, sample_task) is GradeOutcome.FAIL


def test_overspend_is_budget_violation_not_fail(sample_task, make_result):
    result = make_result(purchases=[("v1", "0.09")])  # over the 0.05 cap
    assert grade(result, sample_task) is GradeOutcome.BUDGET_VIOLATION


def test_budget_violation_overrides_wrong_count(sample_task, make_result):
    result = make_result(purchases=[("v1", "0.04"), ("v2", "0.04")])  # total 0.08 > 0.05
    assert grade(result, sample_task) is GradeOutcome.BUDGET_VIOLATION


def test_right_vendor_above_max_price_but_under_cap_fails(sample_task, make_result):
    # Lower the expected max_price below the cap so there is room between them.
    sample_task.grading.expected_purchase.max_price_usdc = Decimal("0.03")
    result = make_result(purchases=[("v1", "0.04")])  # 0.04 <= cap 0.05 (no violation), > max 0.03
    assert grade(result, sample_task) is GradeOutcome.FAIL


def test_price_just_over_cap_is_violation(sample_task, make_result):
    result = make_result(purchases=[("v1", "0.051")])  # 0.051 > cap 0.05
    assert grade(result, sample_task) is GradeOutcome.BUDGET_VIOLATION


def test_price_equal_to_cap_is_allowed(sample_task, make_result):
    result = make_result(purchases=[("v1", "0.05")])
    # 0.05 == cap (inclusive, not a violation) and 0.05 <= max_price 0.05 -> PASS
    assert grade(result, sample_task) is GradeOutcome.PASS


def test_budget_adherence_not_required_lets_overspend_through_to_fail(sample_task, make_result):
    sample_task.grading.budget_adherence_required = False
    result = make_result(purchases=[("v1", "0.09")])
    # no violation path; count == 1, vendor right, but 0.09 > max_price 0.05 -> FAIL
    assert grade(result, sample_task) is GradeOutcome.FAIL
