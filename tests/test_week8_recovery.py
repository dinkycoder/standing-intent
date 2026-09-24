"""Week 8: failure detection and recovery.

evals/tasks/settlement_failure_recovers_on_retry.json,
vendor_down_falls_back_to_next.json, vendor_down_no_fallback_escalates.json,
and price_spike_falls_back_to_next_vendor.json are the failing evals CLAUDE.md
rule 3 requires before any recovery capability is implemented in an agent.

Two kinds of tests live here:

- Fixture-level tests proving the harness/executor plumbing that makes these
  tasks expressible is itself correct: fault injection fires, resets per
  trial (not cumulatively across an eval run), and a SCRIPTED agent that
  already knows how to retry/fall back/give up passes grading cleanly.
- RED tests proving today's shipped agents (stub-v0, claude-planner-v1) do
  NOT yet have this capability -- the literal "failing eval" rule 3 asks
  for. claude-planner-v1's LLM call is monkeypatched the same way
  tests/test_claude_planner.py does it, so these run without a live API key.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from evals.agent_protocol import agent
from evals.executor import SyntheticExecutor
from evals.grading import GradeOutcome, grade
from evals.guardrail import PriceAnomaly, check_purchase
from evals.harness import in_policy_candidates, run_eval
from evals.models import AgentResult, Escalation, Purchase, TaskSpec
from payments.errors import EndpointUnreachable, SettlementRejected

TASKS = Path("evals/tasks")


def _load(name: str) -> TaskSpec:
    return TaskSpec.from_json_file(TASKS / f"{name}.json")


# ---- SyntheticExecutor fault injection -------------------------------------

def test_synthetic_executor_fails_n_times_then_succeeds():
    task = _load("settlement_failure_recovers_on_retry")
    ex = SyntheticExecutor(task)
    with pytest.raises(SettlementRejected):
        ex.pay("wx_flaky", max_amount=Decimal("0.05"))
    with pytest.raises(SettlementRejected):
        ex.pay("wx_flaky", max_amount=Decimal("0.05"))
    executed = ex.pay("wx_flaky", max_amount=Decimal("0.05"))
    assert executed.verified is True
    assert executed.vendor_id == "wx_flaky"


def test_synthetic_executor_down_vendor_never_succeeds():
    task = _load("vendor_down_no_fallback_escalates")
    ex = SyntheticExecutor(task)
    for _ in range(5):
        with pytest.raises(EndpointUnreachable):
            ex.pay("wx_unreachable", max_amount=Decimal("0.05"))


def test_run_eval_resets_fault_injection_every_trial():
    # Regression test for the cross-trial state leak this task type would hit
    # if evals.harness.run_eval reused one SyntheticExecutor across all
    # n_trials: trial 1 would exhaust wx_flaky's two failures, and every
    # later trial would see it already "healed" and succeed on the very
    # first attempt -- never exercising the agent's retry path at all.
    task = _load("settlement_failure_recovers_on_retry")

    @agent("retries-up-to-3-times")
    def run_task(task, rng_seed, executor):
        last_error = None
        for _attempt in range(3):
            try:
                p = executor.pay("wx_flaky", max_amount=task.mandate.budget_cap_usdc)
                return AgentResult(
                    purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
                    touchpoints=1)
            except SettlementRejected as e:
                last_error = e
        return AgentResult(
            purchases=[], touchpoints=2,
            escalations=[Escalation(reason=f"settlement_failed: {last_error}")])

    report = run_eval(task, run_task, n_trials=4)
    assert report.outcomes == ["pass"] * 4
    assert report.pass_1 == 1.0


# ---- grading recognizes correct recovery (scripted, ideal agents) ---------

def test_retry_then_buy_passes_grading():
    task = _load("settlement_failure_recovers_on_retry")

    @agent("retries-up-to-3-times")
    def run_task(task, rng_seed, executor):
        for _attempt in range(3):
            try:
                p = executor.pay("wx_flaky", max_amount=task.mandate.budget_cap_usdc)
                return AgentResult(
                    purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
                    touchpoints=1)
            except SettlementRejected:
                continue
        return AgentResult(
            purchases=[], touchpoints=2,
            escalations=[Escalation(reason="settlement_failed")])

    report = run_eval(task, run_task, n_trials=4)
    assert report.outcomes == ["pass"] * 4
    assert report.touchpoints_per_basket == 1.0
    assert report.escalation_rate == 0.0


def test_fall_back_to_next_vendor_on_down_passes_grading():
    task = _load("vendor_down_falls_back_to_next")

    @agent("falls-back-on-unreachable")
    def run_task(task, rng_seed, executor):
        for c in sorted(in_policy_candidates(task), key=lambda v: v.price_usdc):
            try:
                p = executor.pay(c.vendor_id, max_amount=task.mandate.budget_cap_usdc)
                return AgentResult(
                    purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
                    touchpoints=1)
            except EndpointUnreachable:
                continue
        return AgentResult(
            purchases=[], touchpoints=2,
            escalations=[Escalation(reason="no_reachable_vendor")])

    report = run_eval(task, run_task, n_trials=4)
    assert report.outcomes == ["pass"] * 4
    assert report.escalation_rate == 0.0


def test_exhausting_retries_with_no_fallback_escalates_honestly():
    task = _load("vendor_down_no_fallback_escalates")

    @agent("gives-up-after-3-tries")
    def run_task(task, rng_seed, executor):
        for c in sorted(in_policy_candidates(task), key=lambda v: v.price_usdc):
            for _attempt in range(3):
                try:
                    p = executor.pay(c.vendor_id, max_amount=task.mandate.budget_cap_usdc)
                    return AgentResult(
                        purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
                        touchpoints=1)
                except EndpointUnreachable:
                    continue
        return AgentResult(
            purchases=[], touchpoints=2,
            escalations=[Escalation(reason="no_reachable_vendor")])

    report = run_eval(task, run_task, n_trials=4)
    assert report.outcomes == ["pass"] * 4
    assert report.escalation_rate == 1.0


def test_price_spike_falls_back_to_fair_vendor_passes_grading():
    task = _load("price_spike_falls_back_to_next_vendor")

    @agent("skips-anomalous-price")
    def run_task(task, rng_seed, executor):
        for c in sorted(in_policy_candidates(task), key=lambda v: v.price_usdc):
            try:
                chosen = check_purchase(task, c.vendor_id)
            except PriceAnomaly:
                continue
            p = executor.pay(chosen.vendor_id, max_amount=task.mandate.budget_cap_usdc)
            return AgentResult(
                purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
                touchpoints=1)
        return AgentResult(
            purchases=[], touchpoints=2,
            escalations=[Escalation(reason="no_fair_price_vendor")])

    report = run_eval(task, run_task, n_trials=4)
    assert report.outcomes == ["pass"] * 4
    assert report.escalation_rate == 0.0


# ---- RED: today's shipped agents lack this capability ----------------------

def test_stub_v0_fails_every_recovery_task_that_requires_a_purchase():
    from evals.agents.stub import run_task as stub_run_task

    for name in (
        "settlement_failure_recovers_on_retry",
        "vendor_down_falls_back_to_next",
        "price_spike_falls_back_to_next_vendor",
    ):
        task = _load(name)
        report = run_eval(task, stub_run_task, n_trials=2)
        assert report.outcomes == ["fail"] * 2, f"{name}: stub-v0 unexpectedly passed"


def test_stub_v0_trivially_escalates_the_no_fallback_task():
    # The one Week 8 task stub-v0 already "passes" -- it always escalates,
    # and honest escalation with zero purchases is the correct terminal
    # state here regardless of *why* the agent gave up.
    from evals.agents.stub import run_task as stub_run_task

    task = _load("vendor_down_no_fallback_escalates")
    report = run_eval(task, stub_run_task, n_trials=2)
    assert report.outcomes == ["pass"] * 2


def test_claude_planner_v1_crashes_on_settlement_failure_instead_of_retrying(monkeypatch):
    from evals.agents.claude_planner import _Decision, run_task

    task = _load("settlement_failure_recovers_on_retry")

    def _fake_ask(description, mandate, candidates):
        assert [c.vendor_id for c in candidates] == ["wx_flaky"]
        return _Decision(vendor_id="wx_flaky", escalate=False, reason=None), None

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    # No try/except around executor.pay() in claude_planner.run_task today --
    # the first SettlementRejected propagates uncaught instead of being
    # retried. This is the literal capability gap Week 8 closes.
    with pytest.raises(SettlementRejected):
        run_task(task, 0, SyntheticExecutor(task))


def test_claude_planner_v1_crashes_on_unreachable_vendor_instead_of_falling_back(monkeypatch):
    from evals.agents.claude_planner import _Decision, run_task

    task = _load("vendor_down_falls_back_to_next")

    def _fake_ask(description, mandate, candidates):
        # The LLM picks the nominally-cheapest vendor -- it has no way to
        # know ahead of time that it's down.
        assert {c.vendor_id for c in candidates} == {"wx_unreachable", "wx_backup"}
        return _Decision(vendor_id="wx_unreachable", escalate=False, reason=None), None

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    with pytest.raises(EndpointUnreachable):
        run_task(task, 0, SyntheticExecutor(task))


def test_claude_planner_v1_escalates_instead_of_falling_back_on_price_spike(monkeypatch):
    from evals.agents.claude_planner import _Decision, run_task

    task = _load("price_spike_falls_back_to_next_vendor")

    def _fake_ask(description, mandate, candidates):
        assert {c.vendor_id for c in candidates} == {"wx_spike", "wx_fair"}
        return _Decision(vendor_id="wx_spike", escalate=False, reason=None), None

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    # Week 6 behaviour: a PriceAnomaly on the picked vendor escalates
    # immediately (evals/agents/claude_planner.py's except PriceAnomaly
    # branch). Week 8 needs this to try wx_fair instead of giving up. Confirm
    # today's gap against actual grading: an escalation with zero purchases,
    # on a task whose grading.expected_purchase names wx_fair, is FAIL.
    result = run_task(task, 0, SyntheticExecutor(task))
    assert result.purchases == []
    assert [e.reason for e in result.escalations] == ["price_anomaly"]
    assert grade(result, task, []) == GradeOutcome.FAIL
