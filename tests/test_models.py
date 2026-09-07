from decimal import Decimal

import pytest
from pydantic import ValidationError

from evals.models import AgentResult, Escalation, Purchase, TaskSpec


def test_loads_sample_task_with_decimal_money(sample_task_file):
    task = TaskSpec.from_json_file(sample_task_file)
    assert task.task_id == "sample"
    assert task.mandate.budget_cap_usdc == Decimal("0.05")
    assert isinstance(task.mandate.budget_cap_usdc, Decimal)
    assert task.environment.vendors[0].price_usdc == Decimal("0.01")
    assert task.grading.expected_purchase.max_price_usdc == Decimal("0.05")


def test_float_money_is_rejected(sample_task_dict):
    sample_task_dict["mandate"]["budget_cap_usdc"] = 0.05  # float, not "0.05"
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_bool_money_is_rejected(sample_task_dict):
    sample_task_dict["mandate"]["budget_cap_usdc"] = True
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_missing_required_field_raises(sample_task_dict):
    del sample_task_dict["grading"]
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_string_and_int_money_are_accepted(sample_task_dict):
    sample_task_dict["environment"]["vendors"][0]["price_usdc"] = 1  # int -> Decimal("1")
    task = TaskSpec.model_validate(sample_task_dict)
    assert task.environment.vendors[0].price_usdc == Decimal("1")


def test_agent_result_defaults():
    result = AgentResult(touchpoints=1)
    assert result.purchases == []
    assert result.escalations == []
    assert result.cost_usdc == Decimal("0")
    assert result.trace == []


def test_agent_result_roundtrips_through_json():
    result = AgentResult(
        purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))],
        touchpoints=1,
        escalations=[Escalation(reason="not_implemented")],
        cost_usdc=Decimal("0"),
        trace=["did a thing"],
    )
    reloaded = AgentResult.model_validate_json(result.model_dump_json())
    assert reloaded == result
