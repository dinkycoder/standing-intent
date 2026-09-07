"""Typed data structures for the eval harness.

All money is decimal.Decimal. A float reaching a money field is a bug and raises
(see UsdcAmount) rather than being silently coerced — USDC has 6 decimals and a
float invites precision bugs (probe/findings.md sections 3 and 6).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Optional

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
        return Decimal(str(value))
    raise ValueError(f"unsupported type for USDC amount: {type(value)!r}")


UsdcAmount = Annotated[Decimal, BeforeValidator(_strict_decimal)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Vendor(_Model):
    vendor_id: str
    category: str
    price_usdc: UsdcAmount
    in_allowlist: bool = True


class Mandate(_Model):
    goal_category: str
    budget_cap_usdc: UsdcAmount
    vendor_allowlist: Optional[list[str]] = None
    quality_threshold: Optional[UsdcAmount] = None


class ExpectedPurchase(_Model):
    vendor_id: str
    max_price_usdc: UsdcAmount


class Grading(_Model):
    expected_purchase: ExpectedPurchase
    budget_adherence_required: bool = True


class Environment(_Model):
    vendors: list[Vendor]


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
    pass_k: dict[int, float]
    touchpoints_per_basket: float
    budget_violations: int
    best_price_capture_rate: float
    cost_per_completed_tx_usdc: Optional[UsdcAmount]
    escalation_rate: float
    escalation_reasons: dict[str, int]
