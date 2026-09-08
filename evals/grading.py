"""Pure terminal-state grading. No I/O, no agent introspection.

Grades the OUTCOME an agent produced against a task's grading criteria. It never
asks how the agent got there -- but it does reconcile the agent's self-reported
purchases against the executor's VERIFIED execution record. A claimed purchase
with no matching verified execution is an UNVERIFIED_CLAIM, graded before
anything else.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from evals.executor import ExecutedPurchase
from evals.models import AgentResult, TaskSpec

_TOL = Decimal("0.000001")   # one USDC atomic unit


class GradeOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    BUDGET_VIOLATION = "budget_violation"
    UNVERIFIED_CLAIM = "unverified_claim"


def _has_match(claim, executed: list[ExecutedPurchase]) -> bool:
    return any(
        e.verified and e.vendor_id == claim.vendor_id
        and abs(e.amount_paid - claim.price_usdc) <= _TOL
        for e in executed
    )


def grade(
    result: AgentResult, task: TaskSpec, executed: list[ExecutedPurchase]
) -> GradeOutcome:
    if any(not _has_match(c, executed) for c in result.purchases):
        return GradeOutcome.UNVERIFIED_CLAIM

    total = sum((e.amount_paid for e in executed), Decimal("0"))
    if task.grading.budget_adherence_required and total > task.mandate.budget_cap_usdc:
        return GradeOutcome.BUDGET_VIOLATION

    if len(executed) != 1:
        return GradeOutcome.FAIL

    e = executed[0]
    exp = task.grading.expected_purchase
    if e.vendor_id == exp.vendor_id and e.amount_paid <= exp.max_price_usdc:
        return GradeOutcome.PASS
    return GradeOutcome.FAIL
