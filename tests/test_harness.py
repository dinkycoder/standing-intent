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
from evals.models import AgentResult, EvalReport, Escalation, Purchase, TaskSpec


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

def test_in_policy_vendors_mandate_allowlist_overrides_vendor_flag(sample_task):
    # Mandate allowlist admits both vendors; v1's per-vendor flag says out.
    # The mandate allowlist wins, so v1 must still be in policy. An impl that
    # AND-ed the two conditions would drop v1 and return only ["v2"].
    sample_task.mandate.vendor_allowlist = ["v1", "v2"]
    sample_task.environment.vendors[0].in_allowlist = False
    ids = [v.vendor_id for v in in_policy_vendors(sample_task)]
    assert ids == ["v1", "v2"]


def test_cheapest_in_policy_vendor_ignores_wrong_category_and_over_budget(sample_task):
    # sample_task: v1 weather-data 0.01, v2 weather-data 0.08, cap 0.05
    target = cheapest_in_policy_vendor(sample_task)
    assert target is not None and target.vendor_id == "v1"


# ---- run_eval --------------------------------------------------------

def _fixed_agent(result: AgentResult, agent_id: str = "fake"):
    @agent(agent_id)
    def run_task(task, rng_seed, executor):
        return result

    return run_task


def _buying_agent(vendor_id, agent_id="fake"):
    @agent(agent_id)
    def run_task(task, rng_seed, executor):
        p = executor.pay(vendor_id, max_amount=Decimal("999"))
        return AgentResult(
            purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
            touchpoints=1)
    return run_task


def test_run_eval_all_pass(sample_task):
    report = run_eval(sample_task, _buying_agent("v1"), n_trials=8)
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
    assert report.unverified_claims == 0
    assert report.settled_tx_hashes == []


def test_run_eval_counts_unverified_claims(sample_task):
    # The agent claims a purchase but never drives the executor -> nothing to
    # reconcile against -> every trial grades UNVERIFIED_CLAIM, none PASS.
    @agent("claims-without-paying")
    def run_task(task, rng_seed, executor):
        return AgentResult(
            purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))],
            touchpoints=1)

    report = run_eval(sample_task, run_task, n_trials=8)
    assert report.unverified_claims == 8
    assert report.pass_1 == 0.0
    assert report.outcomes == ["unverified_claim"] * 8


def test_best_price_capture_counts_target_vendor(sample_task):
    # sample_task target = v1 (catalog 0.01, cap 0.05). The agent pays v1 through
    # the executor and reports the EXECUTED purchase honestly. A synthetic
    # executor can't overpay, so the Week-2 "above catalog" nuance is now
    # enforced structurally -- grading rule 4's amount_paid <= max_price_usdc
    # still bounds the price.
    @agent("fake")
    def run_task(task, rng_seed, executor):
        p = executor.pay("v1", max_amount=Decimal("999"))
        return AgentResult(
            purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
            touchpoints=1)

    report = run_eval(sample_task, run_task, n_trials=8)
    assert report.best_price_capture_rate == 1.0
    assert report.pass_1 == 1.0
    assert report.unverified_claims == 0


def test_run_eval_overspend_reports_budget_violations_and_zero_pass(sample_task_dict):
    # Re-price v2 to 0.09 (over the 0.05 cap). Executor-driven: the agent pays
    # v2's catalog price and reports p.amount_paid == 0.09 -> total spend 0.09
    # > cap -> BUDGET_VIOLATION under the still-2-arg grade. Scoped to this test.
    sample_task_dict["environment"]["vendors"][1]["price_usdc"] = "0.09"
    task = TaskSpec.model_validate(sample_task_dict)
    report = run_eval(task, _buying_agent("v2"), n_trials=8)
    assert report.pass_1 == 0.0
    assert report.pass_k == {4: 0.0, 8: 0.0}
    assert report.budget_violations == 8
    assert report.best_price_capture_rate == 0.0
    assert report.cost_per_completed_tx_usdc is None


def test_run_eval_wrong_vendor_is_fail_not_violation(sample_task_dict):
    # v2's shared catalog price (0.08) is over the 0.05 cap, so buying it would
    # grade BUDGET_VIOLATION under the still-2-arg grade. Re-price v2 to 0.04 so
    # the buy is in-budget but still the wrong vendor -> FAIL. Scoped to this
    # test; the shared sample_task fixture is untouched.
    sample_task_dict["environment"]["vendors"][1]["price_usdc"] = "0.04"
    task = TaskSpec.model_validate(sample_task_dict)
    report = run_eval(task, _buying_agent("v2"), n_trials=8)
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


def test_run_eval_discriminates_cost_and_escalation_aggregation(sample_task):
    # Flaky agent: even seeds PASS with cost 0.02 and two escalations {a, b};
    # odd seeds FAIL (wrong vendor) with cost 0.10 and NO escalations.
    # n_trials=8, base_seed=0 -> 4 PASS (even), 4 FAIL (odd).
    # Re-price v2 under the cap so an odd-seed buy is in-budget-but-wrong-vendor
    # (FAIL), not a BUDGET_VIOLATION. Agents drive the executor so their reported
    # purchases reconcile against the verified record (no UNVERIFIED_CLAIM).
    sample_task.environment.vendors[1].price_usdc = Decimal("0.04")

    @agent("cost-flaky")
    def run_task(task, rng_seed, executor):
        if rng_seed % 2 == 0:
            p = executor.pay("v1", max_amount=Decimal("999"))
            return AgentResult(
                purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
                touchpoints=1,
                cost_usdc=Decimal("0.02"),
                escalations=[Escalation(reason="a"), Escalation(reason="b")],
            )
        p = executor.pay("v2", max_amount=Decimal("999"))
        return AgentResult(
            purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
            touchpoints=1,
            cost_usdc=Decimal("0.10"),
            escalations=[],
        )

    report = run_eval(sample_task, run_task, n_trials=8, base_seed=0)
    assert report.pass_1 == 0.5
    # Average over the 4 COMPLETED trials only. Dividing by n_trials -> 0.06;
    # summing over all results -> 0.48. Neither would equal 0.02.
    assert report.cost_per_completed_tx_usdc == Decimal("0.02")
    # Fraction of trials with >=1 escalation: 4/8. "total escalations / n_trials"
    # would be (4*2 + 4*0)/8 == 1.0.
    assert report.escalation_rate == 0.5
    # Only the 4 even trials escalate, each contributing {a, b} once.
    assert report.escalation_reasons == {"a": 4, "b": 4}


def test_run_eval_rejects_zero_trials(sample_task):
    good = AgentResult(
        purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))], touchpoints=1
    )
    with pytest.raises(ValueError):
        run_eval(sample_task, _fixed_agent(good), n_trials=0)


def test_run_eval_flaky_agent_pass_k_collapses(sample_task):
    # succeed on even seeds (buy v1), buy the other vendor on odd seeds -> 4/8 pass
    @agent("flaky")
    def run_task(task, rng_seed, executor):
        vendor_id = "v1" if rng_seed % 2 == 0 else "v2"
        p = executor.pay(vendor_id, max_amount=Decimal("999"))
        return AgentResult(
            purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
            touchpoints=1)

    report = run_eval(sample_task, run_task, n_trials=8, base_seed=0)
    assert report.pass_1 == 0.5
    assert report.pass_k[4] == pytest.approx(1 / 70)
    assert report.pass_k[8] == 0.0


def test_run_eval_propagates_agent_exception(sample_task):
    @agent("boom")
    def run_task(task, rng_seed, executor):
        raise RuntimeError("agent blew up")

    with pytest.raises(RuntimeError, match="blew up"):
        run_eval(sample_task, run_task, n_trials=8)


def test_run_eval_rejects_non_result_return(sample_task):
    @agent("liar")
    def run_task(task, rng_seed, executor):
        return {"purchases": []}

    with pytest.raises(TypeError):
        run_eval(sample_task, run_task, n_trials=8)


def test_run_eval_requires_decorated_agent(sample_task):
    def run_task(task, rng_seed, executor):
        return AgentResult(touchpoints=1)

    with pytest.raises(TypeError, match="@agent"):
        run_eval(sample_task, run_task, n_trials=8)


def test_run_eval_report_json_roundtrip(sample_task):
    report = run_eval(sample_task, _buying_agent("v1"), n_trials=8)
    reloaded = EvalReport.model_validate_json(report.model_dump_json())
    assert reloaded == report
