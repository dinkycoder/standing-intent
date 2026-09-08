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


def _match_index(claim, remaining: list[ExecutedPurchase]) -> int | None:
    for i, e in enumerate(remaining):
        if (e.verified and e.vendor_id == claim.vendor_id
                and abs(e.amount_paid - claim.price_usdc) <= _TOL):
            return i
    return None


def grade(
    result: AgentResult, task: TaskSpec, executed: list[ExecutedPurchase]
) -> GradeOutcome:
    # Greedy 1:1 pairing: each claim must reconcile against a DISTINCT verified
    # execution. N identical claims backed by one execution is a misreport and is
    # flagged, not waved through (M-2).
    remaining = list(executed)
    for claim in result.purchases:
        idx = _match_index(claim, remaining)
        if idx is None:
            return GradeOutcome.UNVERIFIED_CLAIM
        remaining.pop(idx)

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
