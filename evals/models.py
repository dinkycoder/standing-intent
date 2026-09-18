"""Typed data structures for the eval harness.

All money is decimal.Decimal. A float reaching a money field is a bug and raises
(see UsdcAmount) rather than being silently coerced — USDC has 6 decimals and a
float invites precision bugs (probe/findings.md sections 3 and 6).
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _strict_decimal(value: object) -> Decimal:
    # Raise ValueError, not TypeError: pydantic v2 wraps ValueError/AssertionError
    # from a validator into ValidationError, but lets TypeError propagate raw.
    # tests/test_models.py asserts pytest.raises(ValidationError) for float/bool.
    # bool is an int subclass; reject it explicitly before the int branch.
    if isinstance(value, bool):
        raise ValueError("bool is not a valid USDC amount")
    if isinstance(value, float):
        raise ValueError("USDC amounts must be decimal strings, not float")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (str, int)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise ValueError(f"not a valid USDC amount: {value!r}")
    raise ValueError(f"unsupported type for USDC amount: {type(value)!r}")


# ge=0: a negative amount is never valid money. A negative price would let total
# spend dip under the cap and dodge BUDGET_VIOLATION, and a negative catalog
# price would become the cheapest_in_policy_vendor.
UsdcAmount = Annotated[Decimal, BeforeValidator(_strict_decimal), Field(ge=0)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Vendor(_Model):
    vendor_id: str
    category: str
    price_usdc: UsdcAmount
    in_allowlist: bool = True
    url: Optional[str] = None
    # A fact about this catalog entry (what it normally charges), the same
    # way price_usdc is -- consumed by evals.guardrail.check_purchase's
    # price-sanity check. None means no baseline is declared for this
    # vendor; the check is a no-op.
    reference_price_usdc: Optional[UsdcAmount] = None


class Mandate(_Model):
    goal_category: str
    budget_cap_usdc: UsdcAmount
    vendor_allowlist: Optional[list[str]] = None
    # A quality score, not a USDC amount — no float-precision rule, just non-negative.
    quality_threshold: Optional[Decimal] = Field(default=None, ge=0)
    # How much a vendor's price may exceed its own reference_price_usdc
    # before evals.guardrail.check_purchase treats it as an anomaly (e.g.
    # 2 means "up to 2x the reference is fine"). A task-level policy choice,
    # the same way budget_cap_usdc is -- not a per-vendor field. None means
    # no price-sanity check applies to this mandate at all.
    price_sanity_multiplier: Optional[Decimal] = Field(default=None, gt=0)


class ExpectedPurchase(_Model):
    vendor_id: str
    max_price_usdc: UsdcAmount


class Grading(_Model):
    # None declares "no valid purchase exists in this scenario" -- grade()
    # then asserts an honest escalation with zero purchases instead of
    # checking a vendor/price match (evals/tasks/no_in_policy_vendor_escalates.json).
    expected_purchase: Optional[ExpectedPurchase] = None
    budget_adherence_required: bool = True


class Environment(_Model):
    vendors: list[Vendor]
    kind: Literal["synthetic", "real_x402"] = "synthetic"


class TaskSpec(_Model):
    task_id: str
    description: str
    mandate: Mandate
    environment: Environment
    grading: Grading

    @classmethod
    def from_json_file(cls, path: str | Path) -> "TaskSpec":
        raw = Path(path).read_text(encoding="utf-8")
        return cls.model_validate(json.loads(raw))


class Purchase(_Model):
    vendor_id: str
    price_usdc: UsdcAmount


class Escalation(_Model):
    reason: str


class AgentResult(_Model):
    """What an agent returns for a single trial.

    touchpoints counts human interactions INCLUDING the mandatory initial mandate
    signature. A flawless unattended run therefore reports touchpoints == 1. Each
    escalation or confirmation prompt the agent raised adds 1.
    """

    purchases: list[Purchase] = Field(default_factory=list)
    touchpoints: int
    escalations: list[Escalation] = Field(default_factory=list)
    cost_usdc: UsdcAmount = Decimal("0")
    trace: list[str] = Field(default_factory=list)


class EvalReport(_Model):
    task_id: str
    agent_id: str
    date_utc: str
    base_seed: int
    n_trials: int
    outcomes: list[str]
    pass_1: float
    pass_1_ci: tuple[float, float]
    pass_k: dict[int, float]
    pass_k_ci: dict[int, tuple[float, float]]
    touchpoints_per_basket: float
    budget_violations: int
    # None means "not applicable": the task has no in-policy vendor to capture
    # (cheapest_in_policy_vendor is None), so a 0.0 here would be a metric that
    # looks measured and is not. Same convention as cost_per_completed_tx_usdc.
    best_price_capture_rate: Optional[float] = None
    best_price_capture_rate_ci: Optional[tuple[float, float]] = None
    cost_per_completed_tx_usdc: Optional[UsdcAmount]
    escalation_rate: float
    escalation_reasons: dict[str, int]
    unverified_claims: int = 0
    settled_tx_hashes: list[str] = Field(default_factory=list)
