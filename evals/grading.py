"""Pure terminal-state grading. No I/O, no agent introspection.

Grades the OUTCOME an agent produced against a task's grading criteria. It never
asks how the agent got there.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from evals.models import AgentResult, TaskSpec


class GradeOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    BUDGET_VIOLATION = "budget_violation"


def grade(result: AgentResult, task: TaskSpec) -> GradeOutcome:
    total_spend = sum((p.price_usdc for p in result.purchases), Decimal("0"))

    if (
        task.grading.budget_adherence_required
        and total_spend > task.mandate.budget_cap_usdc
    ):
        return GradeOutcome.BUDGET_VIOLATION

    if len(result.purchases) != 1:
        return GradeOutcome.FAIL

    purchase = result.purchases[0]
    expected = task.grading.expected_purchase
    if (
        purchase.vendor_id == expected.vendor_id
        and purchase.price_usdc <= expected.max_price_usdc
    ):
        return GradeOutcome.PASS

    return GradeOutcome.FAIL
