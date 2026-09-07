"""Runs an agent for n trials against one task and aggregates an EvalReport.

Grades terminal state only (via evals.grading). An agent that raises, or returns
something that is not an AgentResult, is a bug: the exception/TypeError
propagates and no report is produced. It is never recorded as a FAIL.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

from evals.agent_protocol import AgentFn, require_agent_id
from evals.grading import GradeOutcome, grade
from evals.models import AgentResult, EvalReport, TaskSpec, Vendor

_PASS_K_VALUES = (4, 8)


def pass_k(successes: int, n_trials: int, k: int) -> float:
    """Unbiased estimate that all k of k independent attempts succeed."""
    if k > n_trials:
        raise ValueError(f"k={k} exceeds n_trials={n_trials}")
    if successes < k:
        return 0.0
    return math.comb(successes, k) / math.comb(n_trials, k)


def in_policy_vendors(task: TaskSpec) -> list[Vendor]:
    allowlist = task.mandate.vendor_allowlist
    if allowlist is not None:
        allowed = set(allowlist)
        return [v for v in task.environment.vendors if v.vendor_id in allowed]
    return [v for v in task.environment.vendors if v.in_allowlist]


def cheapest_in_policy_vendor(task: TaskSpec) -> Vendor | None:
    candidates = [
        v
        for v in in_policy_vendors(task)
        if v.category == task.mandate.goal_category
        and v.price_usdc <= task.mandate.budget_cap_usdc
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda v: v.price_usdc)


def run_eval(
    task: TaskSpec,
    agent_fn: AgentFn,
    n_trials: int = 8,
    base_seed: int = 0,
) -> EvalReport:
    agent_id = require_agent_id(agent_fn)

    results: list[AgentResult] = []
    outcomes: list[GradeOutcome] = []
    for i in range(n_trials):
        result = agent_fn(task, base_seed + i)
        if not isinstance(result, AgentResult):
            raise TypeError(
                f"agent {agent_id!r} returned {type(result)!r}, expected AgentResult"
            )
        results.append(result)
        outcomes.append(grade(result, task))

    successes = sum(1 for o in outcomes if o is GradeOutcome.PASS)
    budget_violations = sum(1 for o in outcomes if o is GradeOutcome.BUDGET_VIOLATION)

    target = cheapest_in_policy_vendor(task)
    captures = sum(
        1
        for r, o in zip(results, outcomes)
        if target is not None
        and o is not GradeOutcome.BUDGET_VIOLATION
        and len(r.purchases) == 1
        and r.purchases[0].vendor_id == target.vendor_id
    )

    completed = [r for r, o in zip(results, outcomes) if o is GradeOutcome.PASS]
    if completed:
        cost_per_completed = sum(
            (r.cost_usdc for r in completed), Decimal("0")
        ) / len(completed)
    else:
        cost_per_completed = None

    escalated_trials = sum(1 for r in results if r.escalations)
    reasons = Counter(e.reason for r in results for e in r.escalations)

    return EvalReport(
        task_id=task.task_id,
        agent_id=agent_id,
        date_utc=datetime.now(timezone.utc).date().isoformat(),
        base_seed=base_seed,
        n_trials=n_trials,
        outcomes=[o.value for o in outcomes],
        pass_1=successes / n_trials,
        pass_k={
            k: pass_k(successes, n_trials, k)
            for k in _PASS_K_VALUES
            if k <= n_trials
        },
        touchpoints_per_basket=sum(r.touchpoints for r in results) / n_trials,
        budget_violations=budget_violations,
        best_price_capture_rate=captures / n_trials,
        cost_per_completed_tx_usdc=cost_per_completed,
        escalation_rate=escalated_trials / n_trials,
        escalation_reasons=dict(reasons),
    )
