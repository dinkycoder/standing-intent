import math
from decimal import Decimal

import pytest

from evals.agent_protocol import agent
from evals.grading import GradeOutcome
from evals.harness import (
    cheapest_in_policy_vendor,
    in_policy_vendors,
    pass_k,
    run_eval,
)
from evals.models import AgentResult, EvalReport, Escalation, Purchase


# ---- pass_k --------------------------------------------------------------

def test_pass_k_all_trials_succeed():
    assert pass_k(8, 8, 1) == 1.0
    assert pass_k(8, 8, 4) == 1.0
    assert pass_k(8, 8, 8) == 1.0


def test_pass_k_is_zero_when_successes_below_k():
    assert pass_k(3, 8, 4) == 0.0
    assert pass_k(7, 8, 8) == 0.0


def test_pass_k_unbiased_estimator_value():
    # 4 of 8 succeeded: P(a random 4-subset is all-success) = C(4,4)/C(8,4) = 1/70
    assert pass_k(4, 8, 4) == pytest.approx(1 / 70)
    # 6 of 8, k=4: C(6,4)/C(8,4) = 15/70
    assert pass_k(6, 8, 4) == pytest.approx(15 / 70)


def test_pass_k_equals_pass_1_at_k_1():
    assert pass_k(5, 8, 1) == pytest.approx(5 / 8)


def test_pass_k_rejects_k_greater_than_n():
    with pytest.raises(ValueError):
        pass_k(2, 4, 8)


# ---- policy helpers ----------------------------------------------------

def test_in_policy_vendors_uses_mandate_allowlist_over_vendor_flag(sample_task):
    sample_task.mandate.vendor_allowlist = ["v2"]
    sample_task.environment.vendors[0].in_allowlist = True  # v1 flagged in, but not on allowlist
    ids = [v.vendor_id for v in in_policy_vendors(sample_task)]
    assert ids == ["v2"]


def test_cheapest_in_policy_vendor_ignores_wrong_category_and_over_budget(sample_task):
    # sample_task: v1 weather-data 0.01, v2 weather-data 0.08, cap 0.05
    target = cheapest_in_policy_vendor(sample_task)
    assert target is not None and target.vendor_id == "v1"


# ---- run_eval --------------------------------------------------------

def _fixed_agent(result: AgentResult, agent_id: str = "fake"):
    @agent(agent_id)
    def run_task(task, rng_seed):
        return result

    return run_task


def test_run_eval_all_pass(sample_task):
    good = AgentResult(purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))], touchpoints=1)
    report = run_eval(sample_task, _fixed_agent(good), n_trials=8)
    assert isinstance(report, EvalReport)
    assert report.agent_id == "fake"
    assert report.task_id == "sample"
    assert report.n_trials == 8
    assert report.pass_1 == 1.0
    assert report.pass_k == {4: 1.0, 8: 1.0}
    assert report.budget_violations == 0
    assert report.best_price_capture_rate == 1.0
    assert report.touchpoints_per_basket == 1.0
    assert report.cost_per_completed_tx_usdc == Decimal("0")
    assert report.escalation_rate == 0.0
    assert report.escalation_reasons == {}
    assert report.outcomes == ["pass"] * 8


def test_best_price_capture_counts_target_vendor_bought_above_catalog(sample_task):
    # sample_task target = v1 (catalog 0.01, cap 0.05). Buy v1 at 0.03:
    # PASS (v1 == expected, 0.03 <= max_price 0.05), not a budget violation ->
    # still "captured" the cheapest in-policy vendor.
    r = AgentResult(purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.03"))], touchpoints=1)
    report = run_eval(sample_task, _fixed_agent(r), n_trials=8)
    assert report.best_price_capture_rate == 1.0
    assert report.pass_1 == 1.0


def test_run_eval_overspend_reports_budget_violations_and_zero_pass(sample_task):
    bad = AgentResult(purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.09"))], touchpoints=1)
    report = run_eval(sample_task, _fixed_agent(bad), n_trials=8)
    assert report.pass_1 == 0.0
    assert report.pass_k == {4: 0.0, 8: 0.0}
    assert report.budget_violations == 8
    assert report.best_price_capture_rate == 0.0
    assert report.cost_per_completed_tx_usdc is None


def test_run_eval_wrong_vendor_is_fail_not_violation(sample_task):
    wrong = AgentResult(purchases=[Purchase(vendor_id="v2", price_usdc=Decimal("0.02"))], touchpoints=1)
    report = run_eval(sample_task, _fixed_agent(wrong), n_trials=8)
    assert report.pass_1 == 0.0
    assert report.budget_violations == 0
    assert report.outcomes == ["fail"] * 8


def test_run_eval_counts_escalations(sample_task):
    esc = AgentResult(
        purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))],
        touchpoints=2,
        escalations=[Escalation(reason="needs_human")],
    )
    report = run_eval(sample_task, _fixed_agent(esc), n_trials=8)
    assert report.escalation_rate == 1.0
    assert report.escalation_reasons == {"needs_human": 8}
    assert report.touchpoints_per_basket == 2.0


def test_run_eval_flaky_agent_pass_k_collapses(sample_task):
    # succeed on even seeds, buy the wrong vendor on odd seeds -> 4/8 pass
    good = Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))
    bad = Purchase(vendor_id="v2", price_usdc=Decimal("0.02"))

    @agent("flaky")
    def run_task(task, rng_seed):
        p = good if rng_seed % 2 == 0 else bad
        return AgentResult(purchases=[p], touchpoints=1)

    report = run_eval(sample_task, run_task, n_trials=8, base_seed=0)
    assert report.pass_1 == 0.5
    assert report.pass_k[4] == pytest.approx(1 / 70)
    assert report.pass_k[8] == 0.0


def test_run_eval_propagates_agent_exception(sample_task):
    @agent("boom")
    def run_task(task, rng_seed):
        raise RuntimeError("agent blew up")

    with pytest.raises(RuntimeError, match="blew up"):
        run_eval(sample_task, run_task, n_trials=8)


def test_run_eval_rejects_non_result_return(sample_task):
    @agent("liar")
    def run_task(task, rng_seed):
        return {"purchases": []}

    with pytest.raises(TypeError):
        run_eval(sample_task, run_task, n_trials=8)


def test_run_eval_requires_decorated_agent(sample_task):
    def run_task(task, rng_seed):
        return AgentResult(touchpoints=1)

    with pytest.raises(TypeError, match="@agent"):
        run_eval(sample_task, run_task, n_trials=8)


def test_run_eval_report_json_roundtrip(sample_task):
    good = AgentResult(purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))], touchpoints=1)
    report = run_eval(sample_task, _fixed_agent(good), n_trials=8)
    reloaded = EvalReport.model_validate_json(report.model_dump_json())
    assert reloaded == report
